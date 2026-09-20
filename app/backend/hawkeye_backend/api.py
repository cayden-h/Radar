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
import json
import logging
import secrets
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from hawkeye_backend import __version__
from hawkeye_backend.edge.link import run_edge_link
from hawkeye_backend.household import DeviceAlreadyClaimed, UnknownDevice
from hawkeye_backend.master.base import (
    AutonomousDialRefused,
    MasterUnavailable,
    ParticipationModeRefused,
)
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.models.events import (
    Envelope,
    HelloEvent,
    NarrationEvent,
    OccupancyEvent,
    ShieldEvent,
    TranscriptEvent,
)
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
    TranscriptLine,
    TranscriptSpeaker,
)
from hawkeye_backend.models.events import NoticeEvent
from hawkeye_backend.models.notice import Notice
from hawkeye_backend.models.state import InteriorState
from hawkeye_backend.replay import RecordSealed, build_export, verify_entries
from hawkeye_backend.replay.archive import ArchiveStatus
from hawkeye_backend.replay.courier import CourierReceipt
from hawkeye_backend.runtime import EdgeUnavailable, HubRuntime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["hawkeye"])

#: MJPEG part separator. Any token works as long as it does not occur in the
#: payload; spelled out rather than generated so the web console and the tests
#: can both name it.
MJPEG_BOUNDARY = "hawkeyeframe"


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
    source: Literal["live", "archive"] = Field(
        default="live",
        description=(
            "Where this row came from. `live` means this process recorded it and "
            "still holds it. `archive` means it was read back out of storage, "
            "written by a process that is gone. The console labels the two "
            "differently rather than presenting them as the same claim."
        ),
    )


class ReplayIndex(BaseModel):
    """GET /v1/replay response."""

    hub_name: str
    mode: str
    site_address: str
    caller_ansname: str
    records: list[ReplaySummary]
    archive: ArchiveStatus = Field(
        description=(
            "Whether sealed records are being persisted. A configured archive "
            "that is unreachable looks exactly like 'nothing has happened yet' "
            "unless the page is told the difference, so the page is told."
        )
    )


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


class SecurityModeRequest(BaseModel):
    """POST /v1/security-mode body. A human decision from the app; automation
    never arms or disarms itself."""

    enabled: bool


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
        camera=runtime.camera.status(),
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
        note = await runtime.client.submit_context(incident_id, body.text)
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc

    if body.speak_on_call:
        # Best-effort, deliberately: the note is already stored and
        # acknowledged above. A failure to reach caller must not fail this
        # request or unwind the store - it is a side channel for speaking
        # the note aloud, not the record of it.
        try:
            await runtime.client.inject_context(incident_id, body.text)
        except Exception:
            logger.exception(
                "failed to route resident context to caller for incident %s "
                "(note is still stored)",
                incident_id,
            )

    return note


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


@router.get(
    "/security-mode",
    summary="Is motion currently allowed to open the shutter",
)
async def get_security_mode(request: Request) -> dict:
    runtime = _runtime(request)
    try:
        enabled = await runtime.client.security_mode()
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc
    return {"enabled": enabled}


@router.post(
    "/security-mode",
    summary="Arm or disarm. Motion opens the shutter only while armed",
)
async def set_security_mode(request: Request, body: SecurityModeRequest) -> dict:
    runtime = _runtime(request)
    try:
        enabled = await runtime.client.set_security_mode(body.enabled)
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc
    return {"enabled": enabled}


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
                source="live",
            )
        )

    # Records this process no longer holds - a previous run's, after a restart.
    # The in-memory row wins whenever both sources have the same incident: it
    # was written by the process being asked, and listing an incident twice puts
    # two rows with one id on the console, which reads as a forked record.
    #
    # The two archive reads run together rather than one after the other. Each
    # blocks for the driver's server-selection timeout when the cluster is
    # unreachable, and sequentially that is twice the wait before the page draws
    # anything at all - which is the case a reader is most likely to meet.
    live_ids = {r.incident_id for r in records}
    archived_result, status = await asyncio.gather(
        runtime.archive.summaries(), runtime.archive.status(), return_exceptions=True
    )
    if isinstance(archived_result, BaseException):
        logger.error("replay index: archive read failed (%s)", archived_result)
        archived = []
    else:
        archived = archived_result
    if isinstance(status, BaseException):
        logger.error("replay index: archive status failed (%s)", status)
        status = ArchiveStatus(
            configured=True,
            connected=False,
            backend="unknown",
            detail="Replay archive status could not be read.",
        )
    for row in archived:
        if row.incident_id in live_ids:
            continue
        records.append(ReplaySummary(**row.model_dump(), source="archive"))

    records.sort(key=lambda r: r.opened_at, reverse=True)

    return ReplayIndex(
        hub_name=settings.hub_name,
        mode=settings.mode,
        site_address=settings.site_address,
        caller_ansname=settings.caller_ansname,
        records=records,
        archive=status,
    )


async def _record_or_404(request: Request, incident_id: str) -> ReplayRecord:
    """The record, from memory or from the archive, or a 404 naming what is missing.

    Verify and export both need a whole record and neither needs a live session,
    so both go through here. Before the archive existed they took the session
    directly, which meant a record survived a restart but could not be exported
    afterward - and the export is the deliverable, not the record.
    """
    session = _runtime(request).recorder.get(incident_id)
    if session is not None:
        return session.to_record()

    archived = await _runtime(request).archive.get(incident_id)
    if archived is not None:
        return archived

    raise HTTPException(status_code=404, detail=f"no recorded session for {incident_id}")


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

    # The restart case. A sealed record outlives the process that wrote it, and
    # what comes back is the record as written rather than a reassembly of it -
    # the hashes are stored, not recomputed. Asked before the store below
    # because this is the real record and that is a reconstruction.
    archived = await runtime.archive.get(incident_id)
    if archived is not None:
        return archived

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
    record = await _record_or_404(request, incident_id)
    intact, detail, failed_seq = verify_entries(record.entries)
    return ChainVerdict(
        incident_id=incident_id,
        intact=intact,
        detail=detail,
        failed_seq=failed_seq,
        entries=len(record.entries),
        root_hash=record.root_hash,
        sealed=record.sealed,
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
    record = await _record_or_404(request, incident_id)
    exported_at = utc_now()
    payload = build_export(record, exported_at)
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


class CourierRequest(BaseModel):
    """Send a sealed record to a responding department."""

    to: str = Field(
        default="",
        description=(
            "The destination, as the 911 operator gave it on the call and as it "
            "was read back to them. Recorded with `operator_supplied` provenance: "
            "a human statement on a phone call, never a verified binding and "
            "never authorization for anything. Empty falls back to the address "
            "configured on the hub, recorded as `configured`."
        ),
    )


@router.post(
    "/incident/{incident_id}/courier",
    status_code=202,
    summary="Send the sealed record to the responding department",
)
async def post_courier(
    request: Request, incident_id: str, body: CourierRequest
) -> CourierReceipt:
    """Hand the bundle to a police department, and chain what happened.

    This exists alongside the automatic send on seal for two reasons. The
    operator-supplied address is only known once somebody has answered the
    phone, and a send that failed needs a way to be tried again without
    replaying the incident.

    **202 on a failed send, not 502.** The send is the subject of the request
    rather than a step within it: a failure is a real answer, it is recorded on
    the chain and published to every surface, and the receipt in the body says
    which of the three outcomes happened. A 5xx here would imply the request
    could not be processed, when in fact it was processed completely and the
    answer was no.
    """
    runtime = _runtime(request)
    to = body.to or runtime.settings.courier_to
    provenance = "operator_supplied" if body.to else "configured"
    try:
        return await runtime.deliver(incident_id, to=to, provenance=provenance)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"no record for incident {incident_id}"
        ) from exc
    except RecordSealed as exc:
        # 409: the record exists and the request is well formed, but the record
        # is not in a state where it can be sent. Retrying later will work.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/camera/still", summary="The newest camera frame", response_class=Response)
async def get_camera_still(request: Request) -> Response:
    """One JPEG, or a 503 naming why there isn't one.

    503 rather than a placeholder image, deliberately. A caller that gets bytes
    back must be able to treat them as a real frame; handing back a grey
    rectangle on failure would make every consumer responsible for telling the
    two apart, and one of them would get it wrong.

    A stale frame is still served, because it is a true statement about the last
    thing the camera saw. `X-HawkEye-Frame-Age` and `X-HawkEye-Live` say what it
    is, and every consumer reads them before drawing it as the room now.
    """
    runtime = _runtime(request)
    frame = runtime.camera.latest
    status = runtime.camera.status()
    if frame is None:
        raise HTTPException(status_code=503, detail=status.detail)
    return Response(
        content=frame.jpeg,
        media_type="image/jpeg",
        headers={
            "X-HawkEye-Frame-Age": f"{status.last_frame_age_s or 0.0:.3f}",
            "X-HawkEye-Live": "true" if status.live else "false",
            "Cache-Control": "no-store",
        },
    )


def _mjpeg_part(jpeg: bytes) -> bytes:
    """One part of the multipart stream.

    `Content-Length` is included because without it some clients buffer until
    the connection closes, and for a stream that never closes that means they
    draw nothing at all.
    """
    return (
        f"--{MJPEG_BOUNDARY}\r\n"
        f"Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode() + jpeg + b"\r\n"


@router.get("/camera/live", summary="The live camera, as MJPEG")
async def get_camera_live(request: Request) -> StreamingResponse:
    """`multipart/x-mixed-replace`, which every browser already reads.

    MJPEG rather than WebRTC because it needs no signalling, no TURN fallback
    and no peer plumbing, and it is one `<img src>` in a browser. The cost is
    bandwidth, and this runs on a LAN.

    A consumer that falls behind loses frames rather than stalling the camera.
    See `LiveCamera.accept`: the per-subscriber queue is small on purpose,
    because a viewer three frames behind wants the newest frame, not the backlog.
    """
    runtime = _runtime(request)
    if runtime.camera.latest is None:
        # 503 before the stream opens, so a caller gets a status code rather
        # than an empty 200 that never produces a part.
        raise HTTPException(status_code=503, detail=runtime.camera.status().detail)

    idle_timeout_s = max(1.0, runtime.settings.camera_stale_after_s * 2)

    async def parts():
        sub = await runtime.camera.subscribe()
        try:
            # The newest frame first, so a viewer joining mid-stream sees
            # something immediately instead of waiting for the next capture.
            first = runtime.camera.latest
            if first is not None:
                yield _mjpeg_part(first.jpeg)
            while True:
                try:
                    frame = await asyncio.wait_for(sub.queue.get(), timeout=idle_timeout_s)
                except asyncio.TimeoutError:
                    # **The stream ends rather than holding a frozen frame open.**
                    #
                    # A browser whose <img> stops receiving parts keeps painting
                    # the last one it got, forever, with no way for the page to
                    # know. Ending the response is what lets the page fall back
                    # to the unreachable state, which is the whole rule: a
                    # frozen picture of an empty room is the most dangerous
                    # thing this system can display.
                    logger.info(
                        "camera stream: no frame for %.1fs, ending the response so "
                        "the client stops painting a stale one",
                        idle_timeout_s,
                    )
                    return
                yield _mjpeg_part(frame.jpeg)
        finally:
            await runtime.camera.unsubscribe(sub)

    return StreamingResponse(
        parts(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.websocket("/edge/link")
async def edge_link(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    """The websocket the Pi dials. Frames up, shutter grants down.

    The Pi dials out rather than serving so that nothing in this system ever has
    to discover the Pi's address. It is headless and its DHCP lease moves every
    time the network changes; the only address anything needs is this hub's own.
    """
    runtime: HubRuntime = websocket.app.state.runtime
    await run_edge_link(websocket, runtime, token)


class NarrationRequest(BaseModel):
    """What `vision/` posts for each Gemini line."""

    text: str = Field(min_length=1)
    room: str = Field(
        min_length=1,
        description=(
            "Required, never defaulted. One fixed camera sees one room, and a "
            "scoped claim must not quietly become an unscoped one because a "
            "producer left a field out."
        ),
    )
    window_s: float = Field(default=1.0, gt=0)


class TranscriptRequest(BaseModel):
    """What `agents/caller` posts for each line spoken on the call, operator or
    caller side."""

    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)


class OccupancyRequest(BaseModel):
    person_present: bool
    people: int = Field(ge=0)
    room: str = Field(min_length=1)


class ShutterRequest(BaseModel):
    """Ask the shield to move.

    Two actions exist and there is no third. An unknown one is a refusal rather
    than a default, which is the rule `agents/shutter/grant.py` already states.
    """

    action: Literal["open", "close"]
    reason: str = Field(
        default="",
        description=(
            "Why. Recorded into the sealed record so an investigator can follow "
            "the chain backwards. Nothing downstream reads it as authorization."
        ),
    )


@router.post("/vision/narration", status_code=202, summary="One line from the camera")
async def post_narration(request: Request, body: NarrationRequest) -> NarrationEvent:
    """`vision/` posts here; every app sees it.

    202 rather than 201: this creates nothing addressable, it publishes. The
    line is on the stream by the time this returns.
    """
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="narration text cannot be blank")
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    event = NarrationEvent(text=body.text.strip(), room=body.room, window_s=body.window_s)
    await runtime.emit(event, active.incident_id if active else None)
    return event


@router.post(
    "/incident/{incident_id}/transcript",
    status_code=202,
    summary="One line from the live operator <-> agent 911 call",
)
async def post_transcript(
    incident_id: str, request: Request, body: TranscriptRequest
) -> TranscriptEvent:
    """`agents/caller`'s Retell orchestrator posts here for every line it
    appends to its own transcript, operator or caller side; every app sees it.

    202 rather than 201: this creates nothing addressable, it publishes. The
    line is on the stream by the time this returns. Best-effort by contract on
    the caller's side: a failed POST here must never break a live 911 call.
    """
    runtime = _runtime(request)
    try:
        speaker = TranscriptSpeaker(body.speaker)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"unknown speaker {body.speaker!r}")
    if speaker is TranscriptSpeaker.CALLER:
        provenance = Provenance(
            source=Source.AGENT_INFERENCE,
            producer="agents/caller",
            ansname=runtime.settings.caller_ansname,
        )
    elif speaker is TranscriptSpeaker.OPERATOR:
        provenance = Provenance(source=Source.OPERATOR_AUDIO, producer="911 PSAP operator")
    elif speaker is TranscriptSpeaker.RESIDENT:
        # The resident speaking on the call directly (whisper or full voice).
        # USER_INPUT is HUMAN-class and is the closest existing source for
        # something a resident said themselves; it must never be attributed
        # to the operator.
        provenance = Provenance(source=Source.USER_INPUT, producer="resident")
    else:
        # SYSTEM: a non-speech annotation we generated ourselves, e.g. "call
        # connected". Not sensed, not spoken by a human on the line.
        provenance = Provenance(source=Source.AGENT_INFERENCE, producer="hawkeye_backend")
    line = TranscriptLine(
        line_id=str(uuid.uuid4()),
        incident_id=incident_id,
        speaker=speaker,
        text=body.text,
        provenance=provenance,
    )
    event = TranscriptEvent(line=line)
    await runtime.emit(event, incident_id)
    return event


@router.post("/vision/occupancy", status_code=202, summary="Whether the camera sees anybody")
async def post_occupancy(request: Request, body: OccupancyRequest) -> OccupancyEvent:
    """Personhood, and nothing more.

    It says somebody is there. It never says who: we have no database and no
    lawful basis for one. Identity is `intruder`'s question and it answers it
    from the router's device roster, not from a face.
    """
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    event = OccupancyEvent(
        person_present=body.person_present, people=body.people, room=body.room
    )
    await runtime.emit(event, active.incident_id if active else None)
    return event


@router.post("/shutter", status_code=202, summary="Move the physical shield")
async def post_shutter(request: Request, body: ShutterRequest) -> ShieldEvent:
    """Challenge, sign, open, publish. Every outcome reaches every surface.

    Three messages cross the edge link, in this order, and the order is the
    security property rather than an implementation detail:

    1. **This process asks the shutter for a nonce.** The grant is bound to a
       challenge the *verifier* issued, which is what makes a replayed grant
       detectable. A nonce generated here would prove nothing.
    2. **`master` signs a grant over that nonce**, and it crosses as an opaque
       string. Nothing between here and the servo may reformat it.
    3. **The shutter verifies and answers**, with an attestation or a refusal.

    The refusal matters more than the success. A dispatch demo that works is
    unremarkable; a shutter that declines a grant it cannot verify, visibly, on
    every screen at once, is the submission.

    Four outcomes, four different answers, none of them a guess:

    - **No edge connected** is a 503. There is no servo, and answering `opened`
      would be the worst possible response.
    - **The shutter refused** is a 202 carrying `refused: true` and the reason.
      The system worked; it said no.
    - **The shutter never answered** is a 504 and a position of `unknown`. An
      unknown shield position is a true statement and `open` would be a false
      one, and the difference is whether a camera is covered.
    - **It moved** is a 202 with the attested position, always `commanded` and
      never `measured`, because the servo has no position feedback.
    """
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    incident_id = active.incident_id if active else None
    timeout = runtime.settings.shutter_timeout_s

    def refused(reason: str) -> ShieldEvent:
        return ShieldEvent(
            position="unknown",
            requested_action=body.action,
            reason=body.reason,
            refused=True,
            refusal_reason=reason,
        )

    # -- phase one: a nonce from the shutter itself --------------------------
    challenge_id = secrets.token_urlsafe(9)
    challenge_waiter = runtime.await_attestation(challenge_id)
    try:
        await runtime.request_challenge(challenge_id)
    except EdgeUnavailable as exc:
        runtime.cancel_attestation(challenge_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        challenge = await asyncio.wait_for(challenge_waiter, timeout=timeout)
    except asyncio.TimeoutError:
        runtime.cancel_attestation(challenge_id)
        event = refused(f"the shutter did not answer a challenge within {timeout}s")
        await runtime.emit(event, incident_id)
        raise HTTPException(status_code=504, detail=event.refusal_reason)

    if getattr(challenge, "failed", False) or not getattr(challenge, "nonce", ""):
        event = refused(f"the shutter would not issue a nonce: {challenge.detail}")
        await runtime.emit(event, incident_id)
        return event

    # -- phase two: a signed grant bound to that nonce ----------------------
    request_id = secrets.token_urlsafe(9)
    waiter = runtime.await_attestation(request_id)

    try:
        grant_json = await runtime.client.issue_shutter_grant(
            action=body.action,
            reason=body.reason,
            nonce=challenge.nonce,
            incident_id=incident_id,
        )
    except MasterUnavailable as exc:
        runtime.cancel_attestation(request_id)
        raise HTTPException(status_code=503, detail=f"cannot issue a grant: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        # Broad on purpose. Anything escaping here leaves a future registered in
        # `_pending_attestations` that nothing will ever resolve, and a process
        # that runs for days leaks one per failure. The shield also stays where
        # it is, which is the correct outcome when no grant could be signed, so
        # this answers 503 rather than 500.
        runtime.cancel_attestation(request_id)
        logger.exception("shutter: could not issue a grant")
        raise HTTPException(
            status_code=503, detail=f"cannot issue a grant: {exc}"
        ) from exc

    try:
        await runtime.send_grant(grant_json, request_id)
    except EdgeUnavailable as exc:
        runtime.cancel_attestation(request_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        attestation = await asyncio.wait_for(waiter, timeout=timeout)
    except asyncio.TimeoutError:
        runtime.cancel_attestation(request_id)
        # `refused` stays false: nothing refused anything, the shutter went
        # quiet. They are different facts and the record keeps them apart.
        # `position` unknown is what every surface must render loudly, because
        # it is the one case where whether the camera is covered is genuinely
        # not known.
        event = ShieldEvent(
            position="unknown",
            requested_action=body.action,
            reason=body.reason,
            refusal_reason="the shutter did not answer",
        )
        await runtime.emit(event, incident_id)
        raise HTTPException(
            status_code=504,
            detail=(
                f"the shutter did not answer within {timeout}s. "
                "The shield position is unknown."
            ),
        )

    if attestation.refused:
        event = ShieldEvent(
            # A refused grant means the shield did not move, and the shutter
            # still knows where it is. Carry that rather than `unknown`, which
            # would throw away a true fact. `unknown` stays for the case where
            # the shutter could not be reached at all.
            position=attestation.position or "unknown",
            commanded_angle=attestation.commanded_angle,
            requested_action=body.action,
            reason=body.reason,
            refused=True,
            refusal_reason=attestation.refusal_reason,
        )
    else:
        # Parsed only to read display fields out of it. The signature was
        # verified by `shutter` over the grant, not by this process over this.
        try:
            attested = json.loads(attestation.attestation_json or "{}")
        except json.JSONDecodeError:
            attested = {}
        event = ShieldEvent(
            position=attested.get("position", "unknown"),
            commanded_angle=attested.get("commanded_angle"),
            position_basis=attested.get("position_basis", "commanded"),
            requested_action=body.action,
            reason=body.reason,
        )

    await runtime.emit(event, incident_id)
    return event


@router.post(
    "/notice/{notice_id}/dismiss",
    status_code=202,
    summary="Clear a notice everywhere at once",
)
async def post_dismiss_notice(request: Request, notice_id: str) -> Notice:
    """One human clears it; every surface clears it.

    Server-side rather than per-client on purpose. Before this existed the
    phone kept its own opinion about what had been dismissed, so a resident who
    cleared a banner on their phone still had it sitting on their wrist.

    **Dismissing is not vouching.** It clears a banner and nothing else. It does
    not suppress the next notice about this presence and it does not add anybody
    to the roster; those are `/presences/{id}/approve` and `/household/remember`,
    which are separate controls with separate words because a single control for
    both would persist strangers because somebody wanted a banner to go away.

    Idempotent, and it never 404s. A resident tapping twice under stress is not
    a condition worth surfacing, and refusing an id this process no longer holds
    would leave them with a banner they cannot get rid of.
    """
    runtime = _runtime(request)
    notice = runtime.dismiss_notice(notice_id)
    await runtime.emit(NoticeEvent(notice=notice))
    return notice
