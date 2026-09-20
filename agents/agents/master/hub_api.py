"""The surface `app/backend` talks to. The other end of `LiveMasterClient`.

Until this existed, `HAWKEYE_MODE=live` had nowhere to point: the hub's live
client posted to `/v1/state`, `/v1/stream` and `/v1/shutter/grant` and master
served none of them, so every surface ran off the scripted incident in
`master/simulated.py`. This is T20, and it is the seam that makes the three
apps show what the mesh actually found rather than what a script says it found.

## Where the line is

This router is **not** an agent-to-agent channel and must never become one.
Agent to agent is `/a2a`, signed, verified, nonce-bound. This is the hub's
channel, and the hub is on the human side of the boundary: it renders to a
watch, a phone and a browser.

So the rule here is the inverse of the one on `/a2a`. Nothing on this surface
is trusted; everything on it is *reported*. The claims it serves have already
been through `TrustGate` on the way in, and what crosses here is the gate's
verdict alongside the claim, so a surface can render a discard as loudly as an
acceptance.

## What it does not do

**It does not classify, decide, or act.** Every endpoint reads state the agent
already holds, or forwards one human decision into the agent. The one exception
is `POST /v1/shutter/grant`, which signs - and that is a signature over a nonce
`shutter` itself issued, on behalf of a decision the hub's own endpoint already
made with a human behind it.

**It never dials.** `POST /a2a/start-call` calls `MasterAgent.release_for_call`,
which raises on anything not raised by a person. The hub holds an independent
copy of the same guard. Two processes, two checks, same rule: Hawk Eye never
calls 911 on its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.models.events import (
    Envelope,
    EventPayload,
    IncidentEvent,
    IncidentPhase,
    StateEvent,
    VerificationEvent,
)
from hawkeye_backend.models.hub import AgentReachability, Reachability, SensorLiveness
from hawkeye_backend.models.incident import Incident as HubIncident
from hawkeye_backend.models.incident import (
    ContextNote,
    IncidentClassification,
    IncidentStatus,
    IncidentType,
    RaisedBy,
)
from hawkeye_backend.models.state import (
    Calibration,
    Floorplan,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from pydantic import BaseModel, Field

from agents.core.identity import ROSTER, identity
from agents.master.agent import AutonomousDialRefused, MasterAgent
from agents.master.gate import AdmittedClaim
from agents.shutter.grant import GrantEnvelope, sign_grant

if TYPE_CHECKING:  # pragma: no cover
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

#: How long a grant signed here stays valid. Must match `shutter_client.GRANT_TTL`
#: and `shutter/grant.py`: seconds, not minutes, because a grant that outlives
#: the situation that produced it is a replay waiting to happen.
GRANT_TTL = timedelta(seconds=10)

#: How often the hub-facing state is recomposed and pushed. Twice master's own
#: tick, so a surface never waits a full tick to see a change, and slow enough
#: that a watch is not being sent a state document it cannot draw.
PUBLISH_INTERVAL_S = 0.5

#: Ticks of no observation at all before an agent is reported unreachable rather
#: than merely quiet. `master` re-reads every peer every tick, so this is a small
#: number of seconds and not a retry budget.
UNREACHABLE_AFTER_S = 6.0


class GrantRequest(BaseModel):
    """What the hub asks for when a human, or a motion verdict, wants the shield moved.

    `nonce` is the shutter's own challenge and is never generated here. Binding
    a grant to a nonce the *verifier* issued is what makes a replayed grant
    detectable, and it is the one invariant this endpoint exists to preserve.
    """

    action: str = Field(description="'open' or 'close'. `shutter` refuses anything else.")
    reason: str = Field(description="Recorded into the sealed record. Never read as authorization.")
    nonce: str = Field(min_length=1, description="Issued by `shutter`, via shutter.challenge.")
    incident_id: str | None = None


class GrantResponse(BaseModel):
    """The signed grant, as the opaque string it crosses the wire as.

    A string, never an object. `shutter` verifies the signature over exactly
    these bytes, and any layer that parses and re-serializes breaks every
    signature in a way indistinguishable from tampering.
    """

    grant_json: str


class IncidentRequest(BaseModel):
    incident_type: IncidentType
    raised_by: RaisedBy
    note: str | None = None


class ContextRequest(BaseModel):
    text: str


class StartCallRequest(BaseModel):
    incident_id: str


class SetModeRequest(BaseModel):
    incident_id: str
    mode: str
    by_human: bool


class SecurityModeRequest(BaseModel):
    """Arm/disarm. Motion has always opened the shutter unconditionally on
    detection; this is the human switch on top of it, and it defaults to
    disarmed - see `MasterAgent.security_mode`."""

    enabled: bool


class MasterHub:
    """Composes master's verified picture into what the three surfaces render.

    Holds no state of its own beyond the subscriber list and the last composed
    document. Everything it serves is read from the agent at the moment it is
    asked, for the same reason `MasterAgent.answer` re-admits on every question:
    a surface asks now because the answer may have changed.
    """

    def __init__(
        self,
        agent: MasterAgent,
        *,
        site_id: str,
        site_address: str,
        floorplan: Floorplan,
        key: "Ed25519PrivateKey",
        camera_room: str = "living_room",
    ) -> None:
        self.agent = agent
        self.site_id = site_id
        # Configuration, never a claim. See `hub_incident`.
        self.site_address = site_address
        self.floorplan = floorplan
        self.camera_room = camera_room
        self._key = key
        self._subscribers: set[WebSocket] = set()
        self._seq = 0
        self._task: asyncio.Task[None] | None = None
        #: Verification ids already pushed, so the stream carries each verdict
        #: once rather than re-announcing the same claim every half second. The
        #: gate mints a fresh id per admission, so this grows with real events
        #: rather than with time.
        self._announced: set[str] = set()
        self._zone_centroids = {
            room.zone: _centroid(room.polygon) for room in floorplan.rooms
        }

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._task = asyncio.create_task(self._publish_loop(), name="master-hub-publish")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _publish_loop(self) -> None:
        """Push state and fresh verification verdicts to every connected hub.

        Broad exception handling on purpose, same rule as the hub's own
        background tasks: this runs for the life of the process and must not die
        of one malformed claim during an emergency.
        """
        while True:
            try:
                await self.broadcast(StateEvent(state=self.state()))
                for result in self._fresh_verifications():
                    await self.broadcast(VerificationEvent(result=result))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("master hub: publish failed")
            await asyncio.sleep(PUBLISH_INTERVAL_S)

    def _fresh_verifications(self) -> list[Any]:
        """Verdicts not yet announced, acceptances and discards alike.

        Discards are carried with exactly the same weight as acceptances, which
        is the whole reason this stream exists. "It tells you what it discarded"
        is checkable only if the discards actually reach a screen.
        """
        results = [claim.result for claim in self.agent.admitted]
        results.extend(self.agent.discarded)
        fresh = [r for r in results if r.verification_id not in self._announced]
        for result in fresh:
            self._announced.add(result.verification_id)
        # The gate mints a new id per pass, so this set would otherwise grow
        # without bound on a process that runs all weekend.
        if len(self._announced) > 5000:
            self._announced = set(list(self._announced)[-1000:])
        return fresh

    # ----------------------------------------------------------------- fan-out

    async def subscribe(self, socket: WebSocket) -> None:
        self._subscribers.add(socket)

    def unsubscribe(self, socket: WebSocket) -> None:
        self._subscribers.discard(socket)

    async def broadcast(self, payload: EventPayload) -> None:
        """Send one envelope to every connected hub, dropping the ones that died.

        A send failure is a disconnected hub rather than a bad event, so the
        socket is dropped and the event still reaches everyone else. An
        exception here must never be able to stop a state tick.
        """
        if not self._subscribers:
            return
        self._seq += 1
        incident = self.agent.incident
        envelope = Envelope(
            seq=self._seq,
            payload=payload,
            incident_id=incident.incident_id if incident else None,
        )
        raw = envelope.model_dump_json()
        dead: list[WebSocket] = []
        for socket in self._subscribers:
            try:
                await socket.send_text(raw)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self._subscribers.discard(socket)

    # ------------------------------------------------------------------ queries

    def state(self) -> InteriorState:
        """Master's verified picture, in the shape the app draws.

        Composed from admitted claims only. A claim the gate discarded is not
        here and does not become a presence on someone's screen - it reaches the
        surfaces as a verification verdict instead, which is the honest place
        for it.
        """
        admitted = self.agent.admitted
        by_field: dict[str, list[AdmittedClaim]] = {}
        for claim in admitted:
            by_field.setdefault(claim.assertion.field, []).append(claim)

        motion_zones = {
            claim.assertion.zone_scope
            for claim in by_field.get("presence.motion", [])
            if claim.assertion.value == "true"
        }
        occupancy = {
            claim.assertion.zone_scope: claim
            for claim in by_field.get("vision.occupancy", [])
        }
        unexpected = any(
            claim.assertion.value == "true"
            for claim in by_field.get("intruder.unexpected_presence", [])
        )
        intruder_zones = {
            claim.assertion.value for claim in by_field.get("intruder.intruder_zone", [])
        }

        presences: list[Presence] = []
        for zone in sorted(motion_zones | set(occupancy)):
            presences.append(
                self._presence(
                    zone,
                    moving=zone in motion_zones,
                    occupancy=occupancy.get(zone),
                    unexpected=unexpected and (not intruder_zones or zone in intruder_zones),
                )
            )

        latest = self.agent.latest
        return InteriorState(
            site_id=self.site_id,
            captured_at=latest.observed_at if latest else utc_now(),
            sensor_identity=self.agent.identity.ansname,
            calibration=Calibration(
                # Master aggregates; it holds no baseline of its own. The radio's
                # baseline health is `presence`'s to report and reaches the app
                # through GET /v1/sensor, so inventing an age here would be
                # inventing the one number that decides whether the radio's
                # claims can be trusted at all.
                baseline_age_s=0.0,
                healthy=bool(latest and latest.healthy),
                note=latest.note if latest else "master has not completed a tick yet",
            ),
            presences=presences,
            # Device association is `presence`'s claim and reaches the hub
            # through the verification stream. It is deliberately not restated
            # as a hashed device list here: this router serves what the gate
            # admitted, and a list assembled from claim text would be a second,
            # drifting copy of a field that already has one owner.
            associated_devices=[],
            # The gas sensor went with the pivot. `agents/master/environment.py`
            # is deleted and there is no environment reading to report, which is
            # a strict improvement: every input master now acts on came through
            # the gate.
            environment=None,
            floorplan=self.floorplan,
            active_incident_id=(
                self.agent.incident.incident_id if self.agent.incident else None
            ),
        )

    def _presence(
        self,
        zone: str,
        *,
        moving: bool,
        occupancy: AdmittedClaim | None,
        unexpected: bool,
    ) -> Presence:
        """One zone's worth of presence, stated no more strongly than the evidence.

        The three states map onto what actually produced the evidence, and the
        mapping is the honesty rule in code:

        - The camera saw a person: CONFIRMED_MOVING. A lens resolved a body.
        - The radio saw a perturbation and the camera did not corroborate it:
          UNCONFIRMED. **A curtain looks exactly like this**, and rendering it
          as a person would be the system's worst available lie.
        - The camera is looking and reports nobody: UNKNOWN rather than absent,
          because a zone under observation with nothing in it is a different
          fact from a zone nobody asked about.

        CONFIRMED_STILL is never produced here. It meant "a person who is not
        moving, carrying a breathing signature that was resolvable and is not
        now", and respiration went with the pivot. The state survives in the
        model for the app's decoder; nothing claims it any more.
        """
        person_present = occupancy is not None and occupancy.assertion.value == "person_present"
        if person_present:
            state = PresenceState.CONFIRMED_MOVING
        elif moving:
            state = PresenceState.UNCONFIRMED
        else:
            state = PresenceState.UNKNOWN

        if person_present and occupancy is not None:
            confidence = occupancy.assertion.confidence
            basis_source = occupancy.assertion.provenance.source
        else:
            confidence = 0.4 if moving else 0.2
            basis_source = Source.AGENT_INFERENCE

        x, y = self._zone_centroids.get(zone, (0.0, 0.0))
        return Presence(
            presence_id=f"z-{zone}",
            state=state,
            position=Position(zone=zone, x=x, y=y, zone_confidence=0.9 if person_present else 0.5),
            moving=moving,
            confidence=confidence,
            vitals=Vitals(
                # Respiration went with the pivot and the radio never gets it
                # back. UNKNOWN is the honest value and `None` breathing rate is
                # the honest number: absence of a signature was never proof of
                # absence of a person, and now there is no signature at all.
                respiration=RespirationStatus.UNKNOWN,
                breathing_bpm=None,
                heart_bpm=None,
                person_confidence=confidence if person_present else 0.0,
            ),
            presence_class=PresenceClass.UNKNOWN,
            class_basis=(
                "No class is claimed. Classification came from respiration rate, which "
                "the pivot removed, and a camera that describes build and clothing is "
                "not doing the same thing."
            ),
            # `intruder`'s verdict, inverted: unexpected means no registered
            # device accounts for this person. None when nothing has decided,
            # which is a different fact from "expected" and is carried as one.
            expected=(not unexpected) if (person_present or moving) else None,
            respiration_lost_s=None,
            provenance=Provenance(
                source=basis_source,
                producer=self.agent.identity.name,
                ansname=self.agent.identity.ansname,
                detail=(
                    f"Composed from claims admitted for zone {zone!r}. "
                    + (
                        "A camera resolved a person here."
                        if person_present
                        else "The radio reports motion and no camera has corroborated it. "
                        "A curtain looks exactly like this."
                        if moving
                        else "Under observation, nothing resolved."
                    )
                ),
            ),
        )

    def sensor(self) -> SensorLiveness:
        """Whether the radio is producing anything, from `presence`'s own report.

        Reported from master's view of `presence` rather than by asking the
        radio, because master is what the hub can reach. When `presence` is
        unreachable this says so; it never fills the gap with a plausible rate.
        """
        latest = self.agent.latest
        blind = {u.field.split(".", 1)[0] for u in latest.unknowns} if latest else set()
        reachable = "presence" not in blind
        motion = any(
            claim.assertion.field == "presence.motion" for claim in self.agent.admitted
        )
        source = Source.AGENT_INFERENCE
        for claim in self.agent.admitted:
            if claim.assertion.field.startswith("presence."):
                source = claim.assertion.provenance.source
                break
        return SensorLiveness(
            source=source,
            simulated=source in (Source.RUVIEW_SIM, Source.DEMO_TRIGGER),
            live=reachable,
            frame_rate_hz=None,
            last_frame_at=latest.observed_at if latest and reachable else None,
            baseline_healthy=reachable,
            baseline_age_s=None,
            detail=(
                "agents/presence is answering master's challenges."
                + (" Motion is being reported." if motion else " No motion this pass.")
                if reachable
                else "agents/presence produced no observation. Unreachable and "
                "'nothing to report' are different facts and this is the first one."
            ),
        )

    def reachability(self) -> list[AgentReachability]:
        """Which peers answered master's last fan-out.

        Built from the roster rather than from whoever happened to answer, so an
        agent that vanished is reported as unreachable rather than omitted. An
        agent missing from a list reads as an agent nobody asked about.
        """
        latest = self.agent.latest
        blind = {u.field.split(".", 1)[0] for u in latest.unknowns} if latest else set()
        answered = {
            claim.assertion.field.split(".", 1)[0] for claim in self.agent.admitted
        }
        out: list[AgentReachability] = []
        for agent in sorted(ROSTER, key=lambda a: (a.tier, a.slug)):
            if agent.slug == self.agent.identity.slug:
                reach = Reachability.REACHABLE
                detail = "This process."
            elif agent.slug in blind:
                reach = Reachability.UNREACHABLE
                detail = "Produced no observation on master's last fan-out."
            elif agent.slug in answered:
                reach = Reachability.REACHABLE
                detail = "Answered master's last challenge with an admitted claim."
            else:
                # Not asked. `master` fans out to the sensing agents only;
                # `caller`, `replay` and `shutter` are downstream of it and their
                # health is not a thing this fan-out measures. Saying "degraded"
                # would be inventing a measurement.
                reach = Reachability.DEGRADED
                detail = (
                    "Not part of master's sensing fan-out, so this pass says nothing "
                    "about it either way."
                )
            out.append(
                AgentReachability(
                    name=agent.name,
                    ansname=agent.ansname,
                    tier=agent.tier,
                    reachability=reach,
                    last_seen_at=latest.observed_at if latest else None,
                    detail=detail,
                )
            )
        return out

    # ------------------------------------------------------------- the incident

    def hub_incident(self, incident: Any) -> HubIncident:
        """Master's small incident, in the rich shape the app renders.

        Master holds a type, a release gate and a trace; the hub model carries
        the address, the status and the classification the resident reads.
        Translating here rather than widening master's own type keeps the
        coordinator's state small, which is the reason it is a separate type in
        the first place.

        **The address comes from this process's configuration, never from the
        incident.** It is bound at registration and sealed; an agent that can
        change where a response is sent is a swatting tool no matter how well
        the claims upstream verify.
        """
        found = incident.classification
        classification = (
            IncidentClassification(
                incident_type=found.incident_type,
                reasoning=found.reasoning,
                confidence=found.confidence,
                contributing_claim_ids=list(found.contributing_fields),
                discarded_claim_ids=[r.claim.claim_id for r in self.agent.discarded],
            )
            if found
            else None
        )
        return HubIncident(
            incident_id=incident.incident_id,
            site_id=self.site_id,
            incident_type=incident.incident_type,
            status=(
                IncidentStatus.CLASSIFIED if classification else IncidentStatus.RAISED
            ),
            raised_by=incident.raised_by,
            raised_at=incident.raised_at,
            address=self.site_address,
            classification=classification,
            context_notes=[
                ContextNote(
                    note_id=f"n-{i}",
                    incident_id=incident.incident_id,
                    text=text,
                    provenance=Provenance(
                        source=Source.USER_INPUT,
                        producer=self.agent.identity.name,
                        ansname=self.agent.identity.ansname,
                        detail=(
                            "Typed by the resident. A human statement, not a measurement: "
                            "`caller` attributes it rather than asserting it as sensed fact."
                        ),
                    ),
                )
                for i, text in enumerate(incident.context_notes, start=1)
            ],
        )

    # ---------------------------------------------------------------- the grant

    def sign(self, request: GrantRequest) -> str:
        """Sign a grant over the shutter's own nonce.

        **This is the only place in this process that signs an order rather than
        a claim**, and the distinction is the whole reason `shutter` exists as a
        separate agent. A claim says what is true and a failed one leaves the
        world unchanged; a grant says *do this*, and a failed one is an attempt
        to move a physical object that did not succeed.

        The envelope is built through `agents.shutter.grant` and never by hand.
        A hand-built dict serializes datetimes differently from pydantic and
        produces a signature mismatch indistinguishable from an attack, which is
        battery probe #13.
        """
        now = utc_now()
        envelope = GrantEnvelope(
            nonce=request.nonce,
            issuer=self.agent.identity.ansname,
            action=request.action,
            # Recorded, not trusted. It goes into the sealed record so an
            # investigator can follow the chain backwards; nothing downstream
            # reads it as authorization.
            reason=request.reason,
            incident_id=request.incident_id,
            issued_at=now,
            expires_at=now + GRANT_TTL,
        )
        return sign_grant(self._key, envelope).decode()


def _centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    """The zone's middle, for the 3D view to draw at.

    A centroid, not a fix. `Position` says so in its own docstring and it is
    worth saying twice: this hardware tier cannot localize within a room, and
    the coordinates exist so the renderer has somewhere to put a marker.
    """
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def hub_router(hub: MasterHub) -> APIRouter:
    """The routes `LiveMasterClient` posts to. Paths are its contract, not a proposal.

    Every path here is spelled exactly as `app/backend/hawkeye_backend/master/
    live.py` spells it. That file carried a TODO(master) block for months saying
    these were its proposal rather than something master had agreed to; this
    router is the agreement, and the two must be changed together.
    """
    router = APIRouter(prefix="/v1", tags=["hub"])

    @router.get("/state", summary="Master's verified picture of the interior")
    async def get_state() -> InteriorState:
        return hub.state()

    @router.get("/sensor", summary="Is the radio producing anything")
    async def get_sensor() -> SensorLiveness:
        return hub.sensor()

    @router.get("/agents", summary="Which peers answered the last fan-out")
    async def get_agents() -> dict[str, list[AgentReachability]]:
        return {"agents": hub.reachability()}

    @router.get("/security-mode", summary="Is motion currently allowed to open the shutter")
    async def get_security_mode() -> dict[str, bool]:
        return {"enabled": hub.agent.security_mode}

    @router.post("/security-mode", summary="Arm or disarm. A human decision, from the app")
    async def post_security_mode(body: SecurityModeRequest) -> dict[str, bool]:
        hub.agent.set_security_mode(body.enabled)
        return {"enabled": hub.agent.security_mode}

    @router.post("/incident", summary="Raise an incident")
    async def post_incident(body: IncidentRequest) -> HubIncident:
        incident = hub.agent.raise_incident(body.incident_type, body.raised_by, body.note)
        hub_incident = hub.hub_incident(incident)
        await hub.broadcast(
            IncidentEvent(phase=IncidentPhase.RAISED, incident=hub_incident)
        )
        return hub_incident

    @router.post("/incident/{incident_id}/context", summary="The resident's free text")
    async def post_context(incident_id: str, body: ContextRequest) -> dict[str, str]:
        incident = hub.agent.incident
        if incident is None or incident.incident_id != incident_id:
            raise HTTPException(status_code=404, detail=f"no open incident {incident_id}")
        hub.agent.submit_context(body.text)
        # Echoed in the shape `ContextNote` validates against, so the hub's
        # client can parse it without a second model.
        return {
            "note_id": f"n-{len(incident.context_notes)}",
            "incident_id": incident_id,
            "text": body.text,
            "at": utc_now().isoformat(),
        }

    @router.post("/shutter/grant", summary="Sign a grant bound to the shutter's nonce")
    async def post_grant(body: GrantRequest) -> GrantResponse:
        return GrantResponse(grant_json=hub.sign(body))

    @router.websocket("/stream")
    async def stream(socket: WebSocket) -> None:
        """The hub's subscription. One envelope per frame, same union the app decodes.

        Master speaks the app's envelope directly rather than a private format,
        so the hub validates and forwards instead of translating. One shape
        across three processes is one shape that can drift, instead of two.
        """
        await socket.accept()
        await hub.subscribe(socket)
        # Send the current picture immediately, so a surface that connects
        # between ticks draws something rather than waiting out the interval.
        with contextlib.suppress(Exception):
            await socket.send_text(
                Envelope(seq=0, payload=StateEvent(state=hub.state())).model_dump_json()
            )
        try:
            while True:
                # The hub never sends on this socket; it posts. Reading keeps the
                # connection's close frame observable so a dropped hub is
                # dropped here too rather than accumulating.
                await socket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("hub stream closed unexpectedly", exc_info=True)
        finally:
            hub.unsubscribe(socket)

    return router


def a2a_hub_router(hub: MasterHub) -> APIRouter:
    """The two `/a2a/...` paths the hub posts to. Named for the contract, not the wire.

    These live under `/a2a/` because that is what `LiveMasterClient` spells, and
    the hub's paths are its contract. **They are not the A2A JSON-RPC endpoint**
    and carry no signed envelope: `/a2a` itself is a separate route on a
    separate router, registered by `build_app`, and this prefix cannot shadow it
    because FastAPI matches the exact path first.

    What they carry is one human decision each, forwarded from the surface the
    human touched.
    """
    router = APIRouter(prefix="/a2a", tags=["hub"])

    @router.post("/start-call", summary="Release caller to dial. Human-raised only")
    async def start_call(body: StartCallRequest) -> dict[str, str]:
        """The only path toward a phone call, and the only place master gates it.

        403 rather than 500 on a refusal, because a refused autonomous dial is a
        correct outcome the hub renders, not a fault. The hub holds its own copy
        of this check; two processes refusing independently is the point.
        """
        incident = hub.agent.incident
        if incident is None or incident.incident_id != body.incident_id:
            raise HTTPException(status_code=404, detail=f"no open incident {body.incident_id}")
        try:
            released = hub.agent.release_for_call()
        except AutonomousDialRefused as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"incident_id": released.incident_id, "released": "true"}

    @router.post("/set-mode", summary="Switch the resident's leg of the call")
    async def set_mode(body: SetModeRequest) -> dict[str, str]:
        """Automation may only ever move toward quieter.

        Guessing wrong toward silence costs one tap. Guessing wrong toward audio
        makes a phone audible while someone is hiding. The two failures are not
        comparable, so inference is trusted in one direction only and this is
        where that is enforced on master's side.
        """
        if body.mode not in ("watching", "whisper", "full_voice"):
            raise HTTPException(status_code=400, detail=f"unknown mode {body.mode!r}")
        if body.mode in ("whisper", "full_voice") and not body.by_human:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"refusing to move to {body.mode!r} without a human hand. Opening a "
                    "microphone to emergency services is a human decision; automation may "
                    "only ever move toward quieter."
                ),
            )
        announcements = {
            "watching": "The resident is following on screen and is not on the call.",
            "whisper": (
                "The resident is joining but cannot hear you. They are hiding and will "
                "respond by voice only."
            ),
            "full_voice": "The resident is joining. They can hear you.",
        }
        return {"announcement": announcements[body.mode]}

    return router
