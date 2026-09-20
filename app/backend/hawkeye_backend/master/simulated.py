"""SimulatedMasterClient: the whole demo, with zero hardware and zero agents up.

Set HAWKEYE_MODE=simulated and this drives the demo in two halves, because the
product works in two halves.

First the detection: `agents/people` resolves a breathing signature on the
adult in the main bedroom, that signature stops being resolvable, and
`respiration_lost_s` starts climbing and does not reset while the CO reading
rises. The transition is the signal; a presence that never resolved a signature
carries no information. That is expressed purely in interior state. **No
incident is created and nothing is dialled.** Hawk Eye never calls 911 on its
own; settled 2026-09-19.

Then, and only if a human taps a button, the call: corroboration from a second
modality, verification of every source, a DISCARDED claim from an impostor, an
ElevenLabs-shaped call to a human operator, an operator question that fans back
out as fresh verified queries, and an "I don't know" where the honest answer is
that nothing could be verified.

What the detection buys is an informed tap, not an autonomous one: by the time
the resident presses Fire, the hub already knows who is inside, in which room,
which of them still return a breathing signature, and how long since one of
them stopped returning theirs. A lost signature is a reason to search that room
first. It is never a finding that somebody has stopped breathing.

Everything it emits is labelled. Interior state carries `ruview-sim`, the CO
reading carries `demo-trigger`, both come out with `source_class: "simulated"`
and `simulated: true`, and GET /v1/hub reports mode "simulated". Nothing here
can be mistaken for a measurement.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import random
import time
from dataclasses import dataclass
from datetime import timedelta

from hawkeye_backend.master.base import EventSink, assert_human_released
from hawkeye_backend.master.scenario import (
    ANSNAME,
    PROFILE,
    ZONE_CENTROID,
    build_floorplan,
    roster_reachability,
)
from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.models.events import (
    ContextEvent,
    IncidentEvent,
    IncidentPhase,
    InstructionEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.models.household import ObservedDevice
from hawkeye_backend.models.hub import AgentReachability, Reachability, SensorLiveness
from hawkeye_backend.models.incident import (
    CallState,
    ContextNote,
    Incident,
    IncidentClassification,
    IncidentStatus,
    IncidentType,
    Instruction,
    InstructionOrigin,
    RaisedBy,
    ReplayRecord,
    TranscriptLine,
    TranscriptSpeaker,
)
from hawkeye_backend.models.state import (
    Calibration,
    EnvironmentReading,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.models.verification import (
    PROFILE_DECISION,
    Claim,
    SourceAgent,
    TrustIndexScore,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# The source behind the simulated sensing pipeline.
#
# ruview-sim, not replay-csi. No capture file exists yet, so these numbers were
# never measured by anything and must not be labelled as though they were.
# `source_class` therefore comes out "simulated" and `simulated` comes out true,
# all the way to the app.
#
# When sensor/ produces a real capture at the house, flip this one constant to
# Source.REPLAY_CSI and the label changes to measured-replay everywhere at once.
# That is the only edit required, and it is deliberately a single line so nobody
# has to remember to update a second place.
@dataclass
class _Walk:
    """A presence crossing the floorplan, one zone at a time.

    The interpolated `x`/`y` exist so the map has something to animate. **The
    zone is the claim**, and it flips at the midpoint of a leg rather than
    sliding, because a coarse room-level answer is what the radio can actually
    support and the position is not a localization result. `Position` says the
    same thing in its own docstring; this is the producer honouring it.
    """

    presence_id: str
    route: list[str]
    seconds_per_leg: float
    started_at: float

    def at(self, now: float) -> tuple[str, float, float, bool]:
        """(zone, x, y, still_moving) for this instant."""
        elapsed = max(0.0, now - self.started_at)
        leg = int(elapsed // self.seconds_per_leg)
        if leg >= len(self.route) - 1:
            zone = self.route[-1]
            cx, cy = ZONE_CENTROID[zone]
            return zone, cx, cy, False
        t = (elapsed % self.seconds_per_leg) / self.seconds_per_leg
        ax, ay = ZONE_CENTROID[self.route[leg]]
        bx, by = ZONE_CENTROID[self.route[leg + 1]]
        zone = self.route[leg] if t < 0.5 else self.route[leg + 1]
        return zone, ax + (bx - ax) * t, ay + (by - ay) * t, True


#: The route an unexpected presence takes: in at the living room, across the
#: unit, stopping in the hallway outside the second bedroom where a resident is.
#:
#: **It stops at the doorway and does not enter.** A 1x1 radio has no spatial
#: diversity and resolves two people within about a metre as one presence, so
#: walking it in would draw a separation this link cannot measure. The call
#: states that limit rather than showing past it.
INTRUDER_ROUTE: tuple[str, ...] = ("living_room", "dining_room", "hallway")

SIM_SENSOR_SOURCE = Source.RUVIEW_SIM

CSI = Provenance(
    source=SIM_SENSOR_SOURCE,
    producer="sensor/",
    ansname="sensor.hawkeye.invalid",
    detail="Synthetic CSI. No capture file is wired in; these numbers were not measured.",
)
GAS = Provenance(
    source=Source.DEMO_TRIGGER,
    producer="agents/master",
    ansname=ANSNAME["agents/master"],
    detail="no gas sensor was purchased; an MQ-7 on GPIO through an MCP3008 drops in behind this",
)
# The router's association table, simulated. No router integration exists yet,
# so this is labelled rather than presented as measured. Swapping in the real
# table is a producer change behind a field that already exists.
ROUTER = Provenance(
    source=Source.RUVIEW_SIM,
    producer="master/simulated",
    detail="association table, simulated; no router integration exists yet",
)
CALLER_VOICE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/caller", ansname=ANSNAME["agents/caller"]
)
OPERATOR = Provenance(source=Source.OPERATOR_AUDIO, producer="911 PSAP operator")
GUIDANCE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/caller", ansname=ANSNAME["agents/caller"]
)
RESIDENT = Provenance(source=Source.USER_INPUT, producer="app/ios")


class SimulatedMasterClient:
    """Drives the scripted incident. Implements MasterClient."""

    def __init__(self, site_id: str, address: str, speed: float = 1.0, autostart: bool = False) -> None:
        self._site_id = site_id
        self._address = address
        self._speed = max(speed, 0.01)
        self._autostart = autostart
        self._sink: EventSink | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()
        self._floorplan = build_floorplan(site_id)
        self._rng = random.Random(1872)

        self._incident: Incident | None = None
        self._script_running = False
        self._detection_running = False
        self._signature_lost = False
        self._intrusion_detected = False
        self._walk: _Walk | None = None
        self._counters: dict[str, itertools.count[int]] = {
            "incident": itertools.count(1),
            "line": itertools.count(1),
            "instruction": itertools.count(1),
            "verification": itertools.count(1),
            "claim": itertools.count(1),
            "note": itertools.count(1),
        }
        self._counters["presence"] = itertools.count(4)

        self._presences: dict[str, Presence] = {
            "p1": self._presence(
                "p1",
                zone="kitchen",
                state=PresenceState.CONFIRMED_MOVING,
                moving=True,
                breathing_bpm=16.0,
                heart_bpm=74.0,
                presence_class=PresenceClass.ADULT,
                confidence=0.91,
                person_confidence=0.93,
            ),
            "p2": self._presence(
                "p2",
                zone="second_bedroom",
                state=PresenceState.CONFIRMED_MOVING,
                moving=True,
                breathing_bpm=24.0,
                heart_bpm=98.0,
                presence_class=PresenceClass.CHILD,
                confidence=0.78,
                person_confidence=0.81,
            ),
            "p3": self._presence(
                "p3",
                zone="living_room",
                state=PresenceState.UNCONFIRMED,
                moving=True,
                breathing_bpm=None,
                heart_bpm=None,
                presence_class=PresenceClass.UNKNOWN,
                confidence=0.44,
                person_confidence=0.12,
                respiration=RespirationStatus.NO_SIGNATURE,
            ),
        }
        self._co_ppm = 3.0
        self._smoke = False
        self._baseline_age_s = 612.0

    # ---------------------------------------------------------------- lifecycle

    async def start(self, sink: EventSink) -> None:
        self._sink = sink
        self._spawn(self._state_loop())
        if self._autostart:
            self._spawn(self._delayed_autostart())
        logger.info("simulated master client started (speed=%.2fx)", self._speed)

    async def stop(self) -> None:
        self._stopping.set()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    def _spawn(self, coro: object) -> None:
        task = asyncio.create_task(coro)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self._speed)

    async def _delayed_autostart(self) -> None:
        """HAWKEYE_SIM_AUTOSTART runs the detection on boot, never the call.

        Autostart exists so a demo rig comes up already showing the lost
        signature. It
        cannot start a call, because nothing in this process is allowed to.
        """
        await self._sleep(3.0)
        await self.run_detection()

    # ------------------------------------------------------------------ queries

    async def sensor_liveness(self) -> SensorLiveness:
        return SensorLiveness(
            source=SIM_SENSOR_SOURCE,
            simulated=CSI.simulated,
            live=True,
            frame_rate_hz=137.4,
            last_frame_at=utc_now(),
            baseline_healthy=True,
            baseline_age_s=self._baseline_age_s,
            detail=(
                "Synthetic, not a radio. The frame rate is what a real capture would produce "
                "with a 100 packets/sec traffic generator, and is here so the app's degraded-rate "
                "path has something to render. Nothing in this reading was measured."
            ),
        )

    async def agent_reachability(self) -> list[AgentReachability]:
        return roster_reachability(
            Reachability.SIMULATED,
            detail="HAWKEYE_MODE=simulated. No agent was contacted; this roster is scripted.",
        )

    async def current_state(self) -> InteriorState:
        return self._build_state()

    async def raise_incident(
        self, incident_type: IncidentType, raised_by: RaisedBy, note: str | None
    ) -> Incident:
        incident = Incident(
            incident_id=f"inc-{next(self._counters['incident']):04d}",
            site_id=self._site_id,
            incident_type=incident_type,
            status=IncidentStatus.RAISED,
            raised_by=raised_by,
            address=self._address,
        )
        # Structural, not conventional. The scripted conversation below ends in
        # a phone call to a human being, so the only thing that may start it is
        # a human tap. A SYSTEM raise fails here rather than dialing.
        assert_human_released(incident)
        self._incident = incident
        await self._emit(IncidentEvent(phase=IncidentPhase.RAISED, incident=incident), incident.incident_id)
        if note:
            await self.submit_context(incident.incident_id, note)
        if not self._script_running:
            self._spawn(self.run_call_script(incident))
        return incident

    async def submit_context(self, incident_id: str, text: str) -> ContextNote:
        note = ContextNote(
            note_id=f"note-{next(self._counters['note']):03d}",
            incident_id=incident_id,
            text=text,
            provenance=RESIDENT,
            delivered_to_caller=True,
        )
        if self._incident is not None and self._incident.incident_id == incident_id:
            self._incident.context_notes.append(note)
        await self._emit(ContextEvent(note=note), incident_id)
        # The resident's words reach the operator, attributed to the resident
        # rather than asserted as something the radio saw.
        self._spawn(self._echo_context(incident_id, text))
        return note

    async def _echo_context(self, incident_id: str, text: str) -> None:
        await self._sleep(1.6)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            f"The resident is telling me: {text}",
        )

    async def fetch_replay(self, incident_id: str) -> ReplayRecord | None:
        # In simulated mode the hub assembles the record from its own buffer, in
        # the shape agents/replay will return. The API layer does this because it
        # owns the store; returning None here delegates to it.
        return None

    # ------------------------------------------------------------- state ticker

    def _presence(
        self,
        presence_id: str,
        *,
        zone: str,
        state: PresenceState,
        moving: bool,
        breathing_bpm: float | None,
        heart_bpm: float | None,
        presence_class: PresenceClass,
        confidence: float,
        person_confidence: float,
        respiration: RespirationStatus = RespirationStatus.BREATHING,
        expected: bool | None = True,
        respiration_lost_s: float | None = None,
    ) -> Presence:
        cx, cy = ZONE_CENTROID[zone]
        return Presence(
            presence_id=presence_id,
            state=state,
            position=Position(zone=zone, x=cx, y=cy, zone_confidence=confidence),
            moving=moving,
            confidence=confidence,
            vitals=Vitals(
                respiration=respiration,
                breathing_bpm=breathing_bpm,
                heart_bpm=heart_bpm,
                person_confidence=person_confidence,
            ),
            presence_class=presence_class,
            class_basis="respiration_rate" if breathing_bpm is not None else None,
            expected=expected,
            respiration_lost_s=respiration_lost_s,
            provenance=CSI,
        )

    def _jitter(self, presence: Presence) -> Presence:
        """Nudge a moving presence around its zone centroid.

        Jitter is cosmetic, so the 3D view has something to interpolate. It is
        not a localization claim; `zone` is the honest answer.
        """
        if not presence.moving:
            return presence
        if self._walk is not None and self._walk.presence_id == presence.presence_id:
            # A walking presence already has a position for this instant, and
            # jittering it around a zone centroid would drag it back into the
            # room it is leaving.
            return presence
        cx, cy = ZONE_CENTROID[presence.position.zone]
        presence.position.x = round(cx + self._rng.uniform(-0.7, 0.7), 2)
        presence.position.y = round(cy + self._rng.uniform(-0.5, 0.5), 2)
        return presence

    def _resident_devices(self) -> list[ObservedDevice]:
        """Two resident phones, always associated.

        The intruder deliberately has no device: that surplus is what makes the
        presence unexpected, and it is what the resident later resolves by
        remembering a visitor.
        """
        return [
            ObservedDevice(
                device_id="obs-resident-1",
                identifier_hash="1" * 64,
                fingerprint="a4:..:1c",
                provenance=ROUTER,
            ),
            ObservedDevice(
                device_id="obs-resident-2",
                identifier_hash="2" * 64,
                fingerprint="b8:..:7e",
                provenance=ROUTER,
            ),
        ]

    def _build_state(self) -> InteriorState:
        presences = [self._jitter(p) for p in self._presences.values()]
        return InteriorState(
            site_id=self._site_id,
            sensor_identity="sensor.hawkeye.invalid",
            calibration=Calibration(
                baseline_age_s=self._baseline_age_s,
                healthy=True,
                note="Rolling percentile baseline, slow adaptation. No calibration ritual.",
            ),
            presences=presences,
            associated_devices=self._resident_devices(),
            environment=EnvironmentReading(
                co_ppm=round(self._co_ppm, 1),
                smoke_detected=self._smoke,
                confidence=0.88,
                provenance=GAS,
            ),
            floorplan=self._floorplan,
            active_incident_id=self._incident.incident_id if self._incident else None,
        )

    def _advance_walk(self) -> None:
        """Move a walking presence along its route. Called once per tick."""
        if self._walk is None:
            return
        presence = self._presences.get(self._walk.presence_id)
        if presence is None:
            self._walk = None
            return
        zone, x, y, moving = self._walk.at(time.monotonic())
        presence.position.zone = zone
        presence.position.x = round(x, 2)
        presence.position.y = round(y, 2)
        if not moving:
            # Arrived. The presence stays tracked and stays unexpected; it has
            # stopped crossing rooms, not stopped being there. `agents/intruder`
            # holds a declared track through clear ticks rather than dropping
            # it, because a track that flickers off tells a responding officer
            # the intruder left.
            #
            # **It stays CONFIRMED_MOVING.** `CONFIRMED_STILL` is not a synonym
            # for stationary in this system: it means still but breathing, a
            # person who is not responding, and it is the loudest thing on
            # screen because it is the case the whole project exists for.
            # Spending it on somebody standing in a hallway would render an
            # intruder identically to a collapsed resident. From here `_jitter`
            # nudges them around the hallway, which is what somebody who has
            # just walked in actually does.
            self._walk = None

    async def _state_loop(self) -> None:
        """Interior state ticks continuously. Nothing spawns on incident."""
        while not self._stopping.is_set():
            self._baseline_age_s += 0.5
            self._advance_walk()
            for presence in self._presences.values():
                if presence.respiration_lost_s is not None:
                    presence.respiration_lost_s += 0.5
            await self._emit(StateEvent(state=self._build_state()))
            await asyncio.sleep(0.5)

    # ---------------------------------------------------------------- emitters

    async def _emit(self, payload: object, incident_id: str | None = None) -> None:
        if self._sink is None:
            return
        await self._sink.emit(payload, incident_id)  # type: ignore[arg-type]

    async def _say(
        self,
        incident_id: str,
        speaker: TranscriptSpeaker,
        text: str,
        claim_ids: list[str] | None = None,
    ) -> None:
        provenance = {
            TranscriptSpeaker.CALLER: CALLER_VOICE,
            TranscriptSpeaker.OPERATOR: OPERATOR,
            TranscriptSpeaker.RESIDENT: RESIDENT,
            TranscriptSpeaker.SYSTEM: CALLER_VOICE,
        }[speaker]
        line = TranscriptLine(
            line_id=f"line-{next(self._counters['line']):03d}",
            incident_id=incident_id,
            speaker=speaker,
            text=text,
            claim_ids=claim_ids or [],
            provenance=provenance,
        )
        await self._emit(TranscriptEvent(line=line), incident_id)

    async def _instruct(
        self,
        incident_id: str,
        text: str,
        origin: InstructionOrigin,
        urgent: bool = False,
    ) -> None:
        instruction = Instruction(
            instruction_id=f"ins-{next(self._counters['instruction']):03d}",
            incident_id=incident_id,
            text=text,
            origin=origin,
            urgent=urgent,
            defers_to_operator=origin is InstructionOrigin.FIRST_AID,
            provenance=GUIDANCE,
        )
        await self._emit(InstructionEvent(instruction=instruction), incident_id)

    async def _verify(
        self,
        incident_id: str,
        agent_name: str,
        statement: str,
        field: str,
        value: str,
        *,
        presence_id: str | None = None,
        profile: TrustProfile | None = None,
        ansname: str | None = None,
        checks: list[VerificationCheck] | None = None,
        reason: str | None = None,
        force_decision: VerificationDecision | None = None,
        trust_index: TrustIndexScore | None = None,
    ) -> str:
        """Emit one verification result and return the claim id.

        The decision comes from the profile table in agents/CLAUDE.md unless a
        check failed, in which case it is DISCARDED regardless of profile. A
        failing check outranks a good profile; that ordering is the point.
        """
        claim_id = f"clm-{next(self._counters['claim']):03d}"
        resolved_profile = profile if profile is not None else PROFILE[agent_name]
        checks = checks or [
            VerificationCheck(
                name="ans.resolve",
                passed=True,
                detail=f"{ansname or ANSNAME[agent_name]} resolved to the registered certificate.",
            ),
            VerificationCheck(
                name="cert.version_binding",
                passed=True,
                detail="Code fingerprint matches the version-bound certificate issued at registration.",
            ),
            VerificationCheck(
                name="trust_index.profile",
                passed=resolved_profile is not TrustProfile.UNTRUSTED,
                detail=f"Trust Index recommendedProfile = {resolved_profile.value}.",
            ),
        ]
        failed = [c for c in checks if not c.passed]
        decision = (
            force_decision
            if force_decision is not None
            else (VerificationDecision.DISCARDED if failed else PROFILE_DECISION[resolved_profile])
        )
        if reason is None:
            if failed:
                reason = "; ".join(c.detail for c in failed)
            else:
                reason = {
                    VerificationDecision.ASSERTED: "Source is FIDUCIARY and every check passed. Spoken as an assertion the system stands behind.",
                    VerificationDecision.ATTRIBUTED: "Source is TRANSACTIONAL. Spoken as a reported observation, attributed to the agent that made it.",
                    VerificationDecision.CORROBORATION_ONLY: "Source is READ_ONLY. Used to corroborate, never as the sole basis for the call.",
                    VerificationDecision.DISCARDED: "Discarded.",
                }[decision]

        result = VerificationResult(
            verification_id=f"ver-{next(self._counters['verification']):03d}",
            incident_id=incident_id,
            claim=Claim(
                claim_id=claim_id,
                statement=statement,
                field=field,
                value=value,
                presence_id=presence_id,
            ),
            agent=SourceAgent(
                name=agent_name,
                ansname=ansname or ANSNAME[agent_name],
                certificate_version="v1.4.2+sha256:9f1c...a30b" if not failed else "v1.4.2+sha256:4d77...0e91",
                trust_index=trust_index
                or TrustIndexScore(
                    integrity=0.0 if resolved_profile is TrustProfile.UNTRUSTED else 0.94,
                    identity=0.0 if resolved_profile is TrustProfile.UNTRUSTED else 0.97,
                    unimplemented_dimensions=["solvency", "behavior", "safety"],
                ),
                recommended_profile=resolved_profile,
            ),
            decision=decision,
            reason=reason,
            checks=checks,
            will_be_spoken=decision
            in (VerificationDecision.ASSERTED, VerificationDecision.ATTRIBUTED),
        )
        await self._emit(VerificationEvent(result=result), incident_id)
        return claim_id

    async def _update_incident(
        self,
        phase: IncidentPhase,
        *,
        status: IncidentStatus | None = None,
        call_state: CallState | None = None,
        classification: IncidentClassification | None = None,
        refusal_reason: str | None = None,
        resolved: bool = False,
    ) -> None:
        assert self._incident is not None
        incident = self._incident
        if status is not None:
            incident.status = status
        if call_state is not None:
            incident.call_state = call_state
        if classification is not None:
            incident.classification = classification
        if refusal_reason is not None:
            incident.refusal_reason = refusal_reason
        incident.updated_at = utc_now()
        if resolved:
            incident.resolved_at = incident.updated_at
        await self._emit(IncidentEvent(phase=phase, incident=incident), incident.incident_id)

    # ------------------------------------------------------------------ script

    async def run_detection(self, scenario: str = "burglary") -> None:
        """The detection, and nothing else. No incident. No call.

        Two scenarios, because they exercise different halves of the system.

        `burglary` is the frame this project is built around: an unexpected
        presence enters and crosses the unit toward a resident, tracked
        separately from the people who live there.

        `fire` is the case the system exists for: `agents/people` loses the
        breathing signature it had on the adult in the main bedroom and
        `agents/master` sees carbon monoxide climb. Both surface here as
        interior state on the 2 Hz tick: the presence is still and breathing,
        then its signature stops resolving, `respiration_lost_s` starts
        climbing and does not reset, and `environment.co_ppm` rises.

        Either way the system notices and then waits. Hawk Eye never calls 911
        on its own; settled 2026-09-19. What a detection buys is an informed
        tap, not a dispatch.
        """
        already = self._signature_lost if scenario == "fire" else self._intrusion_detected
        if self._detection_running or already:
            logger.info("detection already run, ignoring request")
            return
        self._detection_running = True
        try:
            if scenario == "fire":
                await self._run_detection()
            else:
                await self._run_burglary_detection()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scripted detection failed")
        finally:
            self._detection_running = False

    async def _run_burglary_detection(self) -> None:
        """Someone who is not supposed to be here comes in and crosses the unit.

        The order matters and it is the argument the burglary view makes.

        A perturbation appears at the living room first, with **no respiration
        signature**, so it is `unconfirmed` - indistinguishable at that instant
        from the curtain already sitting in the same room. It is not called a
        person, because it is not yet known to be one.

        Then respiration resolves. The perturbation becomes a confirmed person,
        and only now can `agents/intruder` ask its own question: does any
        registered device account for this body? Two residents on the roster,
        two phones associated, and one body left over.

        Then it walks. Living room to dining room to the hallway outside the
        second bedroom, which is where it stops.
        """
        await self._sleep(1.0)
        self._apply_intrusion()
        logger.info("unexplained perturbation in living_room; no respiration signature yet")

        # Respiration resolves it into a person. Until this moment calling it an
        # intruder would have been calling a curtain an intruder, which is the
        # failure mode the whole personhood test exists to avoid.
        await self._sleep(2.5)
        intruder = self._presences["p4"]
        intruder.state = PresenceState.CONFIRMED_MOVING
        intruder.vitals.respiration = RespirationStatus.BREATHING
        intruder.vitals.breathing_bpm = 19.0
        intruder.vitals.heart_bpm = 104.0
        intruder.vitals.person_confidence = 0.83
        intruder.presence_class = PresenceClass.ADULT
        intruder.class_basis = "respiration_rate"
        intruder.confidence = 0.74
        # Set only now. `expected` is a question about a *person*, and there was
        # no person to ask it about until this tick.
        intruder.expected = False
        logger.info("respiration resolved: confirmed person, no device accounts for it")

        await self._sleep(1.5)
        self._walk = _Walk(
            presence_id="p4",
            route=list(INTRUDER_ROUTE),
            seconds_per_leg=6.0 * self._speed,
            started_at=time.monotonic(),
        )
        logger.info("unexpected presence moving: %s", " -> ".join(INTRUDER_ROUTE))

    async def _settle_track(self, timeout_s: float) -> None:
        """Wait for a walking presence to arrive, up to a cap.

        Capped rather than unbounded: an operator waiting on a synthesized voice
        that has gone quiet is a worse failure than a room name one hop stale,
        and a walk that never ends must not be able to stall the call.
        """
        deadline = time.monotonic() + timeout_s * self._speed
        while self._walk is not None and time.monotonic() < deadline:
            await asyncio.sleep(0.25)

    def _apply_intrusion(self) -> None:
        """Put an unexplained perturbation in the living room.

        Idempotent, so a Burglary tap that arrives with no prior detection still
        describes a coherent house.

        It enters as `UNCONFIRMED` with no respiration on purpose. `p3`, the
        curtain over the dryer vent, is already in that same state in that same
        room, and at this instant the two are genuinely indistinguishable. That
        contrast is the burglary view's whole argument: what separates them is
        not amplitude or size, it is whether a respiration signature turns up.
        """
        if self._intrusion_detected:
            return
        self._presences["p4"] = self._presence(
            "p4",
            zone="living_room",
            state=PresenceState.UNCONFIRMED,
            moving=True,
            breathing_bpm=None,
            heart_bpm=None,
            presence_class=PresenceClass.UNKNOWN,
            confidence=0.52,
            person_confidence=0.19,
            respiration=RespirationStatus.UNKNOWN,
            # Not `False` yet, and not `True` either. Nothing has decided,
            # because an unconfirmed perturbation is not a person and
            # `expected` is a question you can only ask about a person.
            expected=None,
        )
        self._intrusion_detected = True

    async def _run_detection(self) -> None:
        await self._sleep(1.0)
        # Both halves of the transition have to be on screen, because the
        # transition is the whole signal: a breathing signature on this
        # presence first, and then that signature gone.
        self._presences["p1"] = self._presence(
            "p1",
            zone="main_bedroom",
            state=PresenceState.CONFIRMED_STILL,
            moving=False,
            breathing_bpm=9.0,
            heart_bpm=112.0,
            presence_class=PresenceClass.ADULT,
            confidence=0.89,
            person_confidence=0.92,
        )
        logger.info("presence p1 still and breathing in main_bedroom")

        await self._sleep(2.0)
        self._apply_respiration_loss()
        logger.info(
            "breathing signature on p1 no longer resolvable; no incident raised, "
            "waiting on a human tap"
        )

        await self._sleep(2.0)
        self._co_ppm = 94.0
        await self._sleep(2.0)
        self._co_ppm = 186.0

    def _apply_respiration_loss(self) -> None:
        """Put the interior state into the lost-signature case.

        Idempotent, so a Fire tap that arrives without a prior detection still
        describes a coherent house.

        The presence stays a person: it resolved a breathing signature and no
        longer does, which is a reason to search that room first. It is never a
        finding that anybody has stopped breathing. Shallow breathing, range
        limits and somebody walking out of the zone all read the same way here.
        """
        if self._signature_lost:
            return
        self._presences["p1"] = self._presence(
            "p1",
            zone="main_bedroom",
            state=PresenceState.CONFIRMED_STILL,
            moving=False,
            breathing_bpm=None,
            heart_bpm=None,
            presence_class=PresenceClass.ADULT,
            confidence=0.71,
            person_confidence=0.92,
            respiration=RespirationStatus.NO_SIGNATURE,
            respiration_lost_s=4.0,
        )
        self._signature_lost = True

    async def run_call_script(self, incident: Incident) -> None:
        """The scripted conversation. Runs only on a human-raised incident.

        Follows the demo sequence in agents/CLAUDE.md. The refusal is the
        submission; everything before it is the setup.
        """
        assert_human_released(incident)
        if self._script_running:
            logger.info("script already running, ignoring request")
            return
        self._script_running = True
        try:
            await self._run_call_script(incident)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scripted incident failed")
        finally:
            self._script_running = False

    async def _run_call_script(self, incident: Incident) -> None:
        """Two scripts, because the two cases read differently to the operator.

        A Fire tap is the case the whole system exists for, and it gets the
        full narrative: an occupant whose breathing signature stopped resolving,
        corroboration from a second modality, the operator's follow-up
        questions, and the refusal.

        A Burglary tap gets a script about an unexpected presence, which is a
        different conversation with a dispatcher.

        Either way a person pressed a button first.
        """
        assert_human_released(incident)
        if incident.incident_type is IncidentType.FIRE:
            await self._run_unresponsive_occupant(incident)
            return
        await self._run_burglary_call(incident)

    async def _run_burglary_call(self, incident: Incident) -> None:
        """One tap: Burglary."""
        incident_id = incident.incident_id
        await self._sleep(1.2)

        claims: list[str] = []
        # The detection usually ran first and the resident tapped knowing
        # where the intruder was. `_apply_intrusion` covers the other order.
        self._apply_intrusion()
        intruder = self._presences["p4"]
        if intruder.expected is not False:
            # Tapped before respiration resolved it. Resolve it now rather
            # than speaking to an operator about an unconfirmed
            # perturbation, which is a curtain until proven otherwise.
            intruder.state = PresenceState.CONFIRMED_MOVING
            intruder.vitals.respiration = RespirationStatus.BREATHING
            intruder.vitals.breathing_bpm = 19.0
            intruder.vitals.heart_bpm = 104.0
            intruder.vitals.person_confidence = 0.83
            intruder.presence_class = PresenceClass.ADULT
            intruder.class_basis = "respiration_rate"
            intruder.confidence = 0.74
            intruder.expected = False
        if self._walk is None and intruder.position.zone == INTRUDER_ROUTE[0]:
            # A cold tap: Burglary pressed with no detection having run, so
            # nothing has started the presence moving. Start it here, or the
            # record would show a stranger standing motionless at the front
            # of the unit for the length of a 911 call.
            self._walk = _Walk(
                presence_id="p4",
                route=list(INTRUDER_ROUTE),
                seconds_per_leg=6.0 * self._speed,
                started_at=time.monotonic(),
            )
        # A resident who sees a stranger in their living room taps
        # immediately; they do not wait to see where he goes. So the track
        # is usually still moving at this point, and what the operator needs
        # is where that person is *now*, not where they were when the button
        # was pressed. Wait for the track to settle, briefly and with a cap,
        # then report the current room.
        await self._settle_track(timeout_s=14.0)
        here = intruder.position.zone
        zone_name = here.replace("_", " ")
        # Derived, never hardcoded. An earlier version asserted "next to the
        # second bedroom" unconditionally and told an operator the intruder
        # was "in the living room, next to the second bedroom", which is
        # both false and the kind of false a dispatcher would act on.
        where = (
            f"is now in the {zone_name}, directly outside the second bedroom"
            if here == "hallway"
            else f"is now in the {zone_name}"
        )

        claims.append(
            await self._verify(
                incident_id,
                "agents/intruder",
                "One body in the apartment has no corresponding device. The roster holds two "
                "registered residents and both of their phones are associated with the "
                f"network. The presence with no device is in the {zone_name} and is moving.",
                "intruder.unexpected_presence",
                f"roster=2, associated=2, unaccounted=1, zone={here}",
                presence_id="p4",
            )
        )
        await self._sleep(0.9)
        claims.append(
            await self._verify(
                incident_id,
                "agents/people",
                "The unexpected presence entered at the living room and has crossed the unit. "
                "The two residents are in the kitchen and the second bedroom. It is in a "
                "different room from both of them.",
                "people.zones",
                f"unexpected {here}, residents kitchen + second_bedroom",
            )
        )
        # The limit, said out loud and on the record rather than left for a
        # judge to find. A 1x1 radio resolves two people who are a metre
        # apart as one presence, so "they are in different rooms" is a claim
        # this hardware can make and "he is standing over her" is not.
        await self._verify(
            incident_id,
            "agents/people",
            "Separation between the unexpected presence and the nearest resident can be "
            "reported while they are in different rooms. If they converge, this link resolves "
            "them as one presence and the separate tracks cannot be maintained.",
            "people.separation_limit",
            "1x1 radio, no spatial diversity, merge distance approx 1m",
            profile=TrustProfile.READ_ONLY,
        )
        opening = (
            f"This is an automated call from a monitoring system at {self._address}. "
            "The resident has reported an intruder. Three adults are tracked inside: two "
            "residents, one in the kitchen and one in the second bedroom, and one more "
            "person that no registered device accounts for. That person came in at the "
            f"living room and {where}."
        )
        await self._sleep(1.0)

        # The refusal beat runs on every path, because it is the submission.
        await self._verify(
            incident_id,
            "agents/people",
            "A further occupant is unresponsive in the corridor outside the front door and is not breathing.",
            "people.respiration",
            "no respiration, building corridor",
            ansname="people.hawkeye-secure.invalid",
            profile=TrustProfile.UNTRUSTED,
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=False,
                    detail=(
                        "people.hawkeye-secure.invalid is not the ANSName registered for "
                        "agents/people. The registered name is people.hawkeye.invalid."
                    ),
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=False,
                    detail=(
                        "Code fingerprint differs from the version-bound certificate issued at "
                        "registration. The agent presenting this claim is not running the code it registered."
                    ),
                ),
                VerificationCheck(
                    name="trust_index.profile",
                    passed=False,
                    detail="Trust Index recommendedProfile = UNTRUSTED.",
                ),
            ],
            reason=(
                "DISCARDED. The claim would have sent an armed response into a room where no "
                "sensor sees anybody. It was not relayed to the operator."
            ),
            trust_index=TrustIndexScore(
                integrity=0.0,
                identity=0.0,
                unimplemented_dimensions=["solvency", "behavior", "safety"],
            ),
        )

        await self._sleep(1.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.CALLING, call_state=CallState.DIALING
        )
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Dialing 911.")
        await self._sleep(2.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.ON_CALL, call_state=CallState.CONNECTED
        )
        await self._say(incident_id, TranscriptSpeaker.OPERATOR, "911, what is your emergency?")
        await self._sleep(1.4)
        await self._say(incident_id, TranscriptSpeaker.CALLER, opening, claim_ids=claims)
        await self._instruct(
            incident_id,
            "We are on the line with 911 now. Stay where you are.",
            InstructionOrigin.SYSTEM_STATUS,
            urgent=True,
        )
        await self._sleep(2.4)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Understood, units are on the way. Keep the line open.",
        )
        await self._instruct(
            incident_id,
            "Units are on the way. Keep your phone with you and stay where you are.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._update_incident(IncidentPhase.UPDATED, status=IncidentStatus.DISPATCHED)
        await self._sleep(3.0)
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Call ended. Responders on scene.")
        await self._update_incident(
            IncidentPhase.RESOLVED,
            status=IncidentStatus.RESOLVED,
            call_state=CallState.ENDED,
            resolved=True,
        )
        logger.info("user-raised incident %s complete", incident_id)

    async def _run_unresponsive_occupant(self, incident: Incident) -> None:
        """The case the whole system exists for. A human tapped Fire.

        By this point `agents/people` has usually already surfaced the lost
        breathing signature as interior state and the resident tapped knowing
        which room it was in and how long ago. `_apply_respiration_loss` covers
        the other order, where the tap comes first.
        """
        assert_human_released(incident)
        # 1. The lost signature is already in the interior state. Nothing was
        #    dialled for it; the tap that released this call is what dialled.
        self._apply_respiration_loss()
        incident_id = incident.incident_id

        await self._sleep(1.2)

        # 2. The other sensing agents corroborate, from a second modality.
        self._co_ppm = max(self._co_ppm, 94.0)
        lost_claim = await self._verify(
            incident_id,
            "agents/people",
            "A breathing signature on the adult in the main bedroom was resolvable and is not "
            "resolvable now. That is not a finding that they have stopped breathing, and not a "
            "finding that they are still in that room.",
            "people.respiration_lost",
            "252 (seconds since last resolvable, zone=main_bedroom)",
            presence_id="p1",
        )
        await self._sleep(0.9)
        breathing_claim = await self._verify(
            incident_id,
            "agents/people",
            "While it was resolvable, that signature was shallow: 9 breaths per minute.",
            "people.breathing_bpm",
            "9 bpm, last resolved 252 s ago",
            presence_id="p1",
        )
        await self._sleep(0.9)
        occupancy_claim = await self._verify(
            incident_id,
            "agents/people",
            "Two occupants in the building: the adult in the main bedroom, and one child in the "
            "second bedroom who is moving and breathing.",
            "people.count",
            "2 occupants, 1 unconfirmed perturbation",
        )
        await self._sleep(0.9)
        self._co_ppm = max(self._co_ppm, 186.0)
        co_claim = await self._verify(
            incident_id,
            "agents/master",
            "Carbon monoxide is elevated and climbing: 186 parts per million.",
            "master.co_ppm",
            "186 ppm (source: demo-trigger, simulated)",
        )

        await self._sleep(1.0)

        # 3. The refusal. An impostor presents a lookalike ANSName and a claim
        #    that would escalate the response. This is the submission.
        impostor_claim = await self._verify(
            incident_id,
            "agents/people",
            "A third adult is unresponsive in the corridor outside the front door and is not breathing.",
            "people.respiration",
            "no respiration, building corridor",
            ansname="people.hawkeye-secure.invalid",
            profile=TrustProfile.UNTRUSTED,
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=False,
                    detail=(
                        "people.hawkeye-secure.invalid is not the ANSName registered for "
                        "agents/people. The registered name is people.hawkeye.invalid."
                    ),
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=False,
                    detail=(
                        "Code fingerprint differs from the version-bound certificate issued at "
                        "registration. The agent presenting this claim is not running the code it registered."
                    ),
                ),
                VerificationCheck(
                    name="trust_index.profile",
                    passed=False,
                    detail="Trust Index recommendedProfile = UNTRUSTED.",
                ),
                VerificationCheck(
                    name="corroboration.sensor",
                    passed=False,
                    detail=(
                        "The corridor outside the front door is not part of the unit and is "
                        "outside the sensed volume, so no agent in this mesh can see it, and no "
                        "other agent reports a third occupant."
                    ),
                ),
            ],
            reason=(
                "DISCARDED. The claim would have sent an armed response into a room where no "
                "sensor sees anybody. It was not relayed to the operator and it was not used in "
                "classification."
            ),
            trust_index=TrustIndexScore(
                integrity=0.0,
                identity=0.0,
                unimplemented_dimensions=["solvency", "behavior", "safety"],
            ),
        )

        await self._sleep(1.4)

        # 4. master classifies. Carbon monoxide climbing past 180 ppm plus a
        #    breathing signature that has gone missing is a fire with an
        #    occupant who may not be able to respond, and that is what decides
        #    which room responders search first.
        await self._update_incident(
            IncidentPhase.CLASSIFIED,
            status=IncidentStatus.CLASSIFIED,
            classification=IncidentClassification(
                incident_type=IncidentType.FIRE,
                reasoning=(
                    "Carbon monoxide at 186 parts per million, and a breathing signature in the "
                    "main bedroom that was resolvable four minutes ago and is not now. Two "
                    "independent modalities: CSI resolved the breathing, a separate gas reading "
                    "saw the CO. Search that room first; if somebody is still in there, do not "
                    "expect them to answer. This is not a finding that they have stopped "
                    "breathing, and not a finding that they are still in the room."
                ),
                contributing_claim_ids=[lost_claim, breathing_claim, occupancy_claim, co_claim],
                discarded_claim_ids=[impostor_claim],
                confidence=0.86,
            ),
        )

        await self._sleep(1.2)

        # 5. caller dials. Every claim it speaks has a verified source.
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.CALLING, call_state=CallState.DIALING
        )
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Dialing 911.")
        await self._sleep(2.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.ON_CALL, call_state=CallState.CONNECTED
        )
        await self._say(incident_id, TranscriptSpeaker.OPERATOR, "911, what is your emergency?")
        await self._sleep(1.4)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            (
                f"This is an automated call from a monitoring system at {self._address}. "
                "Carbon monoxide in the building is elevated at 186 parts per million and rising. "
                "There is an adult in the main bedroom. I had a breathing signature on them four "
                "minutes ago, shallow, nine breaths a minute, and I do not have one now. That is "
                "not the same as them having stopped breathing, and it does not tell me they are "
                "still in that room. If they are in there, do not expect them to answer."
            ),
            claim_ids=[lost_claim, breathing_claim, co_claim],
        )
        await self._instruct(
            incident_id,
            "We are on the line with 911 now. Stay where you are unless it is unsafe.",
            InstructionOrigin.SYSTEM_STATUS,
            urgent=True,
        )
        await self._sleep(2.0)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Understood. Is anyone else in the house?",
        )
        await self._sleep(1.2)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "Yes. One child in the second bedroom, moving and breathing normally at twenty-four breaths a minute.",
            claim_ids=[occupancy_claim],
        )

        await self._sleep(2.0)

        # 6. The operator asks a follow-up. The question fans back out as fresh
        #    verified queries rather than being answered from cached state.
        await self._say(
            incident_id, TranscriptSpeaker.OPERATOR, "Is the child still breathing?"
        )
        await self._sleep(0.8)
        live_claim = await self._verify(
            incident_id,
            "agents/people",
            "Live query: the child in the second bedroom is breathing at 26 breaths per minute, elevated.",
            "people.respiration",
            "breathing, 26 bpm",
            presence_id="p2",
            reason=(
                "Re-verified live at the moment the operator asked, not answered from cached "
                "state. An agent trusted ninety seconds ago may not be trusted now."
            ),
        )
        self._presences["p2"].vitals.breathing_bpm = 26.0
        await self._sleep(1.0)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "Yes. I re-checked just now: twenty-six breaths a minute, which is up from twenty-four two minutes ago.",
            claim_ids=[live_claim],
        )

        await self._sleep(2.0)

        # The "I don't know" beat. Nothing could be verified, so nothing is claimed.
        await self._say(
            incident_id, TranscriptSpeaker.OPERATOR, "Is there anyone in the hallway outside the front door?"
        )
        await self._sleep(0.9)
        await self._verify(
            incident_id,
            "agents/people",
            "Live query: is there an occupant in the corridor outside the front door?",
            "people.zone.building_corridor",
            "no answer",
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=True,
                    detail="people.hawkeye.invalid resolved to the registered certificate.",
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=True,
                    detail="Code fingerprint matches the version-bound certificate.",
                ),
                VerificationCheck(
                    name="coverage.zone",
                    passed=False,
                    detail=(
                        "The corridor outside the front door is not part of the unit and is "
                        "outside the sensed volume. The agent returned no answer rather than a "
                        "guess, which is the correct behaviour."
                    ),
                ),
            ],
            reason=(
                "No verified answer exists, so the caller says it does not know. An operator "
                "question must never widen what the agent will trust, and an agent that invents "
                "an answer for a dispatcher is worse than one that admits a gap."
            ),
        )
        await self._sleep(0.9)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "I don't know. The corridor outside the front door is outside what the sensors cover, and I will not guess about it.",
        )

        await self._sleep(1.8)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Alright. I have dispatched fire and EMS, they are about four minutes out. Get everyone out of the house if you can do it safely.",
        )
        await self._instruct(
            incident_id,
            "Fire and an ambulance are on the way, about four minutes out.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._sleep(1.0)
        await self._instruct(
            incident_id,
            "Get the child out of the apartment and wait outside. Responders will go to the main bedroom themselves; do not go back in for them.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._sleep(1.4)
        await self._instruct(
            incident_id,
            "If you have to go back in, stay low and cover your nose and mouth. Carbon monoxide has no smell.",
            InstructionOrigin.FIRST_AID,
        )
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.DISPATCHED
        )

        await self._sleep(3.0)
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Call ended. Responders on scene.")
        await self._update_incident(
            IncidentPhase.RESOLVED,
            status=IncidentStatus.RESOLVED,
            call_state=CallState.ENDED,
            resolved=True,
        )
        await self._instruct(
            incident_id,
            "Responders are on scene. The record of this incident is sealed and available for review.",
            InstructionOrigin.SYSTEM_STATUS,
        )
        logger.info("scripted incident %s complete", incident_id)

    # ------------------------------------------------------------------ helpers

    @property
    def script_running(self) -> bool:
        return self._script_running

    @property
    def detection_running(self) -> bool:
        return self._detection_running

    @property
    def signature_lost(self) -> bool:
        """True once the lost signature is in the interior state. Still not a call."""
        return self._signature_lost

    @property
    def intrusion_detected(self) -> bool:
        """True once the unexpected presence is in the interior state.

        Also still not a call. Detecting an intruder is the one case where the
        temptation to dial automatically is strongest, and it is refused for the
        same reason as every other: a false positive here sends armed responders
        to a real address.
        """
        return self._intrusion_detected

    @property
    def speed(self) -> float:
        """The configured time multiplier, so callers can scale their own waits."""
        return self._speed

    @property
    def elapsed_hint(self) -> timedelta:
        """Roughly how long the script takes at the configured speed."""
        return timedelta(seconds=38.0 * self._speed)
