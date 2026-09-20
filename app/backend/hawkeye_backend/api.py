"""The HTTP and websocket surface the iOS app talks to.

Six capabilities, per app/CLAUDE.md:

  GET  /v1/hub                      hub identity and health, for the Connect screen
  GET  /v1/state                    interior state, for the 3D view
  WS   /v1/stream                   the live push channel
  POST /v1/incident                 the resident raises an incident
  POST /v1/incident/{id}/context    the "what is happening" box
  GET  /v1/incident/{id}/replay     the sealed post-incident record

Plus the replay console's three reads, which the iOS app does not use:

  GET  /v1/replay                        index of recorded incidents
  GET  /v1/incident/{id}/replay/verify   recompute the hash chain
  GET  /v1/incident/{id}/replay/export   the bundle a detective is handed

Plus POST /v1/demo/run, which drives the scripted detection in simulated mode and
404s in live mode. It exists so scripts/demo.sh has something to hit. It stops at
the detection: Hawk Eye never calls 911 on its own (settled 2026-09-19), so the
call runs only once a person taps, and `?simulate_human_tap=true` is the explicit
opt-in that stands in for that person.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from hawkeye_backend import __version__
from hawkeye_backend.household import DeviceAlreadyClaimed, UnknownDevice
from hawkeye_backend.master.base import (
    AutonomousDialRefused,
    MasterUnavailable,
    ParticipationModeRefused,
)
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.events import Envelope, HelloEvent
from hawkeye_backend.models.household import HouseholdMember, ObservedDevice, RememberRequest
from hawkeye_backend.models.hub import HubStatus
from hawkeye_backend.models.incident import (
    ContextNote,
    ContextRequest,
    Incident,
    IncidentAck,
    IncidentType,
    RaiseIncidentRequest,
    RaisedBy,
    ReplayRecord,
)
from hawkeye_backend.models.state import InteriorState
from hawkeye_backend.replay import build_export
from hawkeye_backend.runtime import HubRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["hawkeye"])


def _runtime(request: Request) -> HubRuntime:
    runtime: HubRuntime = request.app.state.runtime
    return runtime


class DemoRunAck(BaseModel):
    started: bool
    detail: str
    raised_incident_id: str | None = None


class ReplaySummary(BaseModel):
    """One row on the replay console's index. Deliberately cheap to build.

    A record can hold a few hundred frames, and the index must not serialize all
    of them just to draw a list.
    """

    incident_id: str
    incident_type: str
    address: str
    opened_at: datetime
    sealed: bool
    sealed_at: datetime | None
    seal_reason: str | None
    duration_s: float
    entries: int
    frames_dropped: int
    verifications: int
    discarded: int
    root_hash: str | None


class ReplayIndex(BaseModel):
    """GET /v1/replay response."""

    hub_name: str
    mode: str
    site_address: str
    caller_ansname: str
    records: list[ReplaySummary]


class ChainVerdict(BaseModel):
    """GET /v1/incident/{id}/replay/verify response.

    The website recomputes the same thing in the browser rather than trusting
    this. Both answers are offered because they prove different things: this one
    is convenient, the browser's does not require the server to be honest about
    itself.
    """

    incident_id: str
    intact: bool
    detail: str
    failed_seq: int | None
    entries: int
    root_hash: str | None
    sealed: bool
    scitt_receipt: str | None = None
    receipt_note: str = (
        "Null, and it must stay null until a real transparency-log submission exists. "
        "Without one this record is tamper-evident to whoever holds it and to nobody else."
    )


class HouseholdResponse(BaseModel):
    """The roster. A list rather than a bare array so the shape can grow."""

    members: list[HouseholdMember]


class UnclaimedDevicesResponse(BaseModel):
    devices: list[ObservedDevice]


class SetParticipationModeRequest(BaseModel):
    """POST /v1/incident/{id}/mode body.

    `by_human` defaults true because the only caller that should ever send
    false is the automation itself asking to move quieter; a human tapping a
    mode control in the app always sets it explicitly true. See
    `app/CLAUDE.md`: automation may only ever move toward quieter.
    """

    mode: Literal["watching", "whisper", "full_voice"]
    by_human: bool = True


@router.get("/hub", response_model=HubStatus, summary="Hub identity and health")
async def get_hub(request: Request) -> HubStatus:
    """What the Connect screen hits after Bonjour discovery.

    Health here means "the app may proceed", not "every agent is up". A hub with
    one tier 3 agent unreachable is still usable; a hub whose sensing pipeline is
    dead is not, and the app should say so rather than draw an empty house.
    """
    runtime = _runtime(request)
    settings = runtime.settings
    try:
        sensor = await runtime.client.sensor_liveness()
        agents = await runtime.client.agent_reachability()
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc

    active = await runtime.store.get_active_incident()
    tier1_ok = all(a.reachability.value != "unreachable" for a in agents if a.tier == 1)
    healthy = sensor.live and sensor.baseline_healthy and tier1_ok

    return HubStatus(
        hub_name=settings.hub_name,
        hub_ansname=settings.hub_ansname,
        master_ansname=settings.master_ansname,
        site_id=settings.site_id,
        site_address=settings.site_address,
        mode=settings.mode,
        version=__version__,
        healthy=healthy,
        uptime_s=round(runtime.uptime_s, 1),
        sensor=sensor,
        agents=agents,
        active_incident_id=active.incident_id if active else None,
    )


@router.get("/state", response_model=InteriorState, summary="Current interior state")
async def get_state(request: Request) -> InteriorState:
    """Who is in the building, where, and whether they are breathing.

    Served from the last state the mesh produced when one exists, so a client
    reconnecting mid-incident sees the same thing the stream is pushing.
    """
    runtime = _runtime(request)
    cached = await runtime.store.get_state()
    if cached is not None:
        return cached
    try:
        return await runtime.client.current_state()
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc


@router.post("/incident", response_model=IncidentAck, status_code=202, summary="Raise an incident")
async def post_incident(request: Request, body: RaiseIncidentRequest) -> IncidentAck:
    """One tap from the app. Burglary or Fire.

    202 rather than 201: the hub has accepted it and forwarded it to master, and
    what happens next arrives on the stream. The resident should not be staring
    at a spinner while an agent decides things.
    """
    runtime = _runtime(request)
    try:
        incident: Incident = await runtime.client.raise_incident(
            body.incident_type, RaisedBy.USER, body.note
        )
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc

    # The incident is already raised and acknowledged to the app by this point.
    # A start_call failure must not roll that back: the resident tapped, the
    # incident stands, and the call either starts or it doesn't. Either way the
    # app learns about it from the event stream (call_state stays NOT_PLACED
    # on failure) rather than from this response.
    try:
        await runtime.client.start_call(incident)
    except AutonomousDialRefused:
        # RaisedBy.USER is hardcoded three lines above, so this route can
        # never actually produce the incident that trips this guard. It stays
        # here anyway as the second, structural copy of the rule: if a future
        # change lets a non-user-raised incident reach this point, dialing
        # still refuses rather than silently proceeding.
        logger.warning("start_call refused for %s: not user-raised", incident.incident_id)
    except Exception:
        logger.exception("start_call failed for %s", incident.incident_id)
    return IncidentAck(incident_id=incident.incident_id, status=incident.status)


@router.post(
    "/incident/{incident_id}/context",
    response_model=ContextNote,
    status_code=202,
    summary="The 'what is happening' box",
)
async def post_context(request: Request, incident_id: str, body: ContextRequest) -> ContextNote:
    """Free text from the resident, forwarded to master and on to caller.

    The note carries `user-input` provenance. The agents know what the radio can
    see; they do not know the intruder had a knife or the child is asthmatic.
    What the resident says is a human statement and caller attributes it as one
    rather than asserting it as something a sensor observed.
    """
    runtime = _runtime(request)
    existing = await runtime.store.get_incident(incident_id)
    if existing is None:
        active = await runtime.store.get_active_incident()
        if active is None or active.incident_id != incident_id:
            raise HTTPException(status_code=404, detail=f"unknown incident: {incident_id}")
    try:
        return await runtime.client.submit_context(incident_id, body.text)
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc


@router.post(
    "/incident/{incident_id}/mode",
    summary="Switch the resident's leg of an in-progress call",
)
async def set_mode(
    incident_id: str, request: Request, body: SetParticipationModeRequest
) -> dict:
    """Watching, whisper, or full voice. See the mode table in `app/CLAUDE.md`.

    409 rather than a silent no-op when the change is refused: an automated
    caller asking to go louder without `by_human=True` is exactly the case
    that must fail loudly, because the asymmetry only holds if going quieter
    is free and going louder always needs a human hand.
    """
    runtime = _runtime(request)
    try:
        announcement = await runtime.client.set_participation_mode(
            incident_id, body.mode, by_human=body.by_human
        )
    except ParticipationModeRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"announcement": announcement}


class CallTokenResponse(BaseModel):
    access_token: str


@router.get(
    "/incident/{incident_id}/call-token",
    response_model=CallTokenResponse,
    summary="A Twilio Voice Access Token for the resident's leg of the call",
)
async def get_call_token(request: Request, incident_id: str) -> CallTokenResponse:
    """Mints a short-lived Access Token so the app can join the conference as a
    live WebRTC audio leg (`CallAudioSession` on the client, `app/CLAUDE.md`'s
    mode table for what each participation mode does with it).

    Access Tokens are self-contained signed JWTs; minting one is a local
    operation and never calls Twilio, which is why this needs no
    `MasterUnavailable` handling the way the mesh-backed routes above do.

    404 for an incident this hub never raised, matching `post_context`'s
    validation above. 503 when the API Key/Secret/Application SID trio is
    missing, matching the all-or-none `twilio_*_configured` pattern in
    `hawkeye_backend.config`: a half-configured credential set is treated as
    unconfigured rather than as a token that fails at the moment it matters.
    """
    runtime = _runtime(request)
    existing = await runtime.store.get_incident(incident_id)
    if existing is None:
        active = await runtime.store.get_active_incident()
        if active is None or active.incident_id != incident_id:
            raise HTTPException(status_code=404, detail=f"unknown incident: {incident_id}")

    settings = runtime.settings
    if not settings.twilio_call_token_configured:
        raise HTTPException(
            status_code=503, detail="twilio voice access token minting is not configured"
        )

    token = AccessToken(
        settings.twilio_account_sid,
        settings.twilio_api_key_sid,
        settings.twilio_api_key_secret.get_secret_value(),
        identity=f"resident-{incident_id}",
        ttl=3600,
    )
    token.add_grant(
        VoiceGrant(outgoing_application_sid=settings.twilio_application_sid)
    )
    return CallTokenResponse(access_token=token.to_jwt())


@router.get("/replay", response_model=ReplayIndex, summary="Index of recorded incidents")
async def get_replay_index(request: Request) -> ReplayIndex:
    """What the replay console lists. Newest first.

    Only incidents this hub actually recorded appear here. An incident it saw
    mid-flight but never saw raised is deliberately absent rather than listed
    with a partial chain, because a record that silently omits its own beginning
    has the shape of a doctored one.
    """
    runtime = _runtime(request)
    settings = runtime.settings
    records: list[ReplaySummary] = []
    for session in runtime.recorder.sessions():
        incident = await runtime.store.get_incident(session.incident_id)
        end = session.sealed_at or utc_now()
        record = session.to_record()
        records.append(
            ReplaySummary(
                incident_id=session.incident_id,
                incident_type=incident.incident_type.value if incident else "unknown",
                address=session.site_address,
                opened_at=session.opened_at,
                sealed=session.sealed,
                sealed_at=session.sealed_at,
                seal_reason=session.seal_reason,
                duration_s=round((end - session.opened_at).total_seconds(), 2),
                entries=len(session),
                frames_dropped=session.frames_dropped,
                verifications=len(record.verifications),
                discarded=sum(
                    1 for v in record.verifications if v.decision.value == "DISCARDED"
                ),
                root_hash=session.root_hash,
            )
        )
    return ReplayIndex(
        hub_name=settings.hub_name,
        mode=settings.mode,
        site_address=settings.site_address,
        caller_ansname=settings.caller_ansname,
        records=records,
    )


def _session_or_404(request: Request, incident_id: str):
    """The recorded session, or a 404 naming what is missing."""
    session = _runtime(request).recorder.get(incident_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"no recorded session for {incident_id}"
        )
    return session


@router.get(
    "/incident/{incident_id}/replay",
    response_model=ReplayRecord,
    summary="The sealed post-incident record",
)
async def get_replay(
    request: Request,
    incident_id: str,
    since_seq: int = Query(
        default=0,
        ge=0,
        description=(
            "Return only entries after this sequence. The replay console polls with "
            "it once a second while a record is still open, so an unsealed record is "
            "tailed rather than refetched."
        ),
    ),
) -> ReplayRecord:
    """The record written as the incident happened.

    Three sources, in order of authority. The hub's own recorder holds the
    record it wrote entry by entry, and that is preferred whenever it exists.
    `agents/replay` owns it in live mode and is asked next. Failing both, the
    store assembles one after the fact, which is a reconstruction and proves
    less; it stays only so incidents raised before the recorder existed still
    resolve.

    Every verification is in here, accepted and discarded alike. The discarded
    ones are the point: the operator could not check us live, but an investigator
    can check this afterward, and swatting investigations are entirely post-hoc.
    """
    runtime = _runtime(request)
    session = runtime.recorder.get(incident_id)
    if session is not None:
        return session.to_record(since_seq=since_seq)

    try:
        record = await runtime.client.fetch_replay(incident_id)
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc
    if record is not None:
        return record

    store = runtime.in_memory_store()
    if store is None:
        raise HTTPException(status_code=404, detail=f"no replay record for {incident_id}")
    built = await store.build_replay(
        incident_id,
        caller_ansname=runtime.settings.caller_ansname,
        site_address=runtime.settings.site_address,
    )
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown incident: {incident_id}")
    return built


@router.get(
    "/incident/{incident_id}/replay/verify",
    response_model=ChainVerdict,
    summary="Recompute the record's hash chain",
)
async def verify_replay(request: Request, incident_id: str) -> ChainVerdict:
    """What an investigator runs, and what the console runs again client-side.

    A pass means nobody has edited, reordered, inserted or removed an entry since
    it was written. It does not mean the system that wrote the record wrote it
    honestly; that is the transparency log's job and the log is not wired.
    """
    session = _session_or_404(request, incident_id)
    intact, detail, failed_seq = session.verify()
    return ChainVerdict(
        incident_id=incident_id,
        intact=intact,
        detail=detail,
        failed_seq=failed_seq,
        entries=len(session),
        root_hash=session.root_hash,
        sealed=session.sealed,
    )


@router.get(
    "/incident/{incident_id}/replay/export",
    summary="The bundle a detective is handed",
    response_class=Response,
)
async def export_replay(request: Request, incident_id: str) -> Response:
    """A zip: the record, a readable chain, a standalone verifier, and a README.

    Exports an unsealed record too, clearly marked as unsealed. An investigator
    asking for the record mid-incident is a real scenario and refusing would be
    worse than handing over something honestly labelled.
    """
    session = _session_or_404(request, incident_id)
    exported_at = utc_now()
    payload = build_export(session.to_record(), exported_at)
    stamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="hawkeye-{incident_id}-{stamp}.zip"'
            )
        },
    )


@router.post("/demo/run", response_model=DemoRunAck, summary="Run the scripted detection")
async def post_demo_run(
    request: Request,
    scenario: Literal["burglary", "fire"] = Query(
        default="burglary",
        description=(
            "Which detection to drive. `burglary` puts an unexpected presence in the "
            "living room and walks it across the unit to the hallway outside the second "
            "bedroom. `fire` takes the breathing signature off the adult in the main "
            "bedroom, so `respiration_lost_s` climbs, with the CO reading climbing "
            "alongside it. Neither raises an incident on its own."
        ),
    ),
    simulate_human_tap: bool = Query(
        default=False,
        description=(
            "Stand in for a person pressing the matching button in the app. Off by "
            "default. "
            "The hub itself never raises an incident; this parameter exists so "
            "one curl can exercise detection plus call end to end, and it is "
            "the human, not the system, that it is imitating."
        ),
    ),
) -> DemoRunAck:
    """Drive the scripted detection, then stop. Simulated mode only.

    The detection is expressed purely in interior state: the presence goes to
    `confirmed_still` with no resolvable breathing signature, `respiration_lost_s`
    climbs, the CO reading rises. No incident
    is created and no call is placed, because Hawk Eye never calls 911 on its
    own (settled 2026-09-19). The system notices and waits for a human tap.

    `?simulate_human_tap=true` additionally raises the incident type that matches
    the scenario, exactly as `POST /v1/incident` would, with `raised_by: user`,
    because the thing being simulated is the person. Without it this endpoint
    cannot start a call.

    404s in live mode, deliberately. There must be no way to trigger a scripted
    incident against a live mesh. A demo button that fabricates an emergency on
    a system wired to a phone line is not a thing this project gets to have.
    """
    runtime = _runtime(request)
    client = runtime.client
    if not isinstance(client, SimulatedMasterClient):
        raise HTTPException(status_code=404, detail="not available in live mode")
    if client.script_running:
        return DemoRunAck(started=False, detail="scripted incident already running")

    already_run = client.signature_lost if scenario == "fire" else client.intrusion_detected
    started = not (client.detection_running or already_run)
    if started:
        asyncio.create_task(client.run_detection(scenario))
        detail = f"scripted {scenario} detection started; no incident raised, waiting on a human tap"
    else:
        detail = f"{scenario} detection already run; no incident raised, waiting on a human tap"

    raised_incident_id: str | None = None
    if simulate_human_tap:
        # Exactly the path POST /v1/incident takes. RaisedBy.USER is not a
        # label of convenience here: assert_human_released refuses anything
        # else on the way to the call.
        #
        # The tap matches the detection. A person who has just watched an
        # unexplained body cross their living room does not press Fire, and a
        # demo where the scripted tap disagrees with the scripted detection is
        # showing a house that contradicts itself.
        incident_type = IncidentType.FIRE if scenario == "fire" else IncidentType.BURGLARY
        if scenario == "burglary" and started:
            # Let the detection resolve the perturbation into a person before
            # the stand-in taps. A real resident taps because they were told
            # there is someone in the house, and the system cannot tell them
            # that until respiration has answered whether it is a person at
            # all. Tapping into the middle of that makes the call script force
            # the resolution, and the house then describes a stranger the
            # sensing never actually confirmed.
            #
            # Short, and scaled with sim speed, so the endpoint stays responsive.
            await asyncio.sleep(4.0 * client.speed)
        incident = await client.raise_incident(incident_type, RaisedBy.USER, None)
        raised_incident_id = incident.incident_id
        detail += f"; simulated human tap raised a {incident_type.value} incident"

    return DemoRunAck(started=started, detail=detail, raised_incident_id=raised_incident_id)


@router.get("/household", response_model=HouseholdResponse, summary="Who belongs here")
async def get_household(request: Request) -> HouseholdResponse:
    """The roster. Read-only: members are added by approving a real detection."""
    return HouseholdResponse(members=await _runtime(request).roster.members())


@router.get(
    "/household/unclaimed-devices",
    response_model=UnclaimedDevicesResponse,
    summary="Devices no member claims",
)
async def get_unclaimed_devices(request: Request) -> UnclaimedDevicesResponse:
    """Candidates for a binding. The app shows these when the resident chooses
    to remember a visitor."""
    return UnclaimedDevicesResponse(devices=await _runtime(request).roster.unclaimed_devices())


@router.post(
    "/household/remember",
    response_model=HouseholdMember,
    status_code=201,
    summary="Remember a visitor",
)
async def post_remember(request: Request, body: RememberRequest) -> HouseholdMember:
    """Name a person and optionally bind the device that just appeared.

    201 because this creates something that outlives the request, which is the
    whole difference between this and approving a presence.
    """
    try:
        return await _runtime(request).roster.remember(body)
    except UnknownDevice as exc:
        raise HTTPException(
            status_code=404, detail=f"no observed device with id {exc.args[0]!r}"
        ) from exc
    except DeviceAlreadyClaimed as exc:
        # 409 rather than 404: the device exists, it is just not free. A 404
        # would send the app looking for a device sitting right there, and the
        # resident needs to be told it already belongs to someone.
        raise HTTPException(
            status_code=409,
            detail=f"device {exc.args[0]!r} already belongs to someone on the roster",
        ) from exc


@router.delete(
    "/household/members/{member_id}",
    status_code=204,
    response_model=None,
    summary="Forget a member",
)
async def delete_member(request: Request, member_id: str) -> None:
    """Remove a member. Their devices become unclaimed rather than orphaned."""
    if not await _runtime(request).roster.forget(member_id):
        raise HTTPException(status_code=404, detail=f"no member with id {member_id!r}")


@router.post(
    "/presences/{presence_id}/approve",
    status_code=202,
    summary="Vouch for a presence, this session only",
)
async def post_approve_presence(request: Request, presence_id: str) -> dict[str, str]:
    """A human override of a machine inference. It only ever lowers an alarm.

    Not persisted: presence ids are reused across sessions, so a stored approval
    would silently vouch for a stranger. Idempotent, because a resident tapping
    twice under stress is not a condition worth surfacing.
    """
    _runtime(request).approved_presences.add(presence_id)
    return {"presence_id": presence_id, "status": "approved"}


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    """The live push channel. Every frame is an Envelope.

    On connect the client gets a `hello`, then the last state tick so the 3D view
    has something to draw immediately, then everything as it happens.
    """
    runtime: HubRuntime = websocket.app.state.runtime
    await websocket.accept()
    sub = await runtime.bus.subscribe()
    try:
        active = await runtime.store.get_active_incident()
        recent = await runtime.store.recent_events(1)
        hello = Envelope(
            seq=0,
            payload=HelloEvent(
                hub_name=runtime.settings.hub_name,
                hub_ansname=runtime.settings.hub_ansname,
                mode=runtime.settings.mode,
                active_incident_id=active.incident_id if active else None,
                replay_from_seq=recent[0].seq if recent else None,
            ),
        )
        await websocket.send_text(hello.model_dump_json())

        cached = await runtime.store.get_state()
        if cached is not None:
            from hawkeye_backend.models.events import StateEvent

            await websocket.send_text(
                Envelope(seq=0, payload=StateEvent(state=cached)).model_dump_json()
            )

        while True:
            envelope = await sub.queue.get()
            await websocket.send_text(envelope.model_dump_json())
    except WebSocketDisconnect:
        logger.info("stream client disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("stream client failed")
    finally:
        await runtime.bus.unsubscribe(sub)
