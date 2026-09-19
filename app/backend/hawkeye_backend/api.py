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

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from hawkeye_backend import __version__
from hawkeye_backend.master.base import MasterUnavailable
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.events import Envelope, HelloEvent
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
    """One tap from the app. Burglary, Fire, or Faint.

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


@router.get(
    "/incident/{incident_id}/replay",
    response_model=ReplayRecord,
    summary="The sealed post-incident record",
)
async def get_replay(request: Request, incident_id: str) -> ReplayRecord:
    """From agents/replay in live mode; assembled locally in simulated mode.

    Every verification is in here, accepted and discarded alike. The discarded
    ones are the point: the operator could not check us live, but an investigator
    can check this afterward, and swatting investigations are entirely post-hoc.
    """
    runtime = _runtime(request)
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
        caller_ansname=runtime.settings.master_ansname.replace("master.", "caller."),
        site_address=runtime.settings.site_address,
    )
    if built is None:
        raise HTTPException(status_code=404, detail=f"unknown incident: {incident_id}")
    return built


@router.post("/demo/run", response_model=DemoRunAck, summary="Run the scripted detection")
async def post_demo_run(
    request: Request,
    simulate_human_tap: bool = Query(
        default=False,
        description=(
            "Stand in for a person pressing Faint in the app. Off by default. "
            "The hub itself never raises an incident; this parameter exists so "
            "one curl can exercise detection plus call end to end, and it is "
            "the human, not the system, that it is imitating."
        ),
    ),
) -> DemoRunAck:
    """Drive the scripted detection, then stop. Simulated mode only.

    The detection is expressed purely in interior state: the presence goes to
    `confirmed_still`, `still_down_s` climbs, the CO reading rises. No incident
    is created and no call is placed, because Hawk Eye never calls 911 on its
    own (settled 2026-09-19). The system notices and waits for a human tap.

    `?simulate_human_tap=true` additionally raises a Faint incident exactly as
    `POST /v1/incident` would, with `raised_by: user`, because the thing being
    simulated is the person. Without it this endpoint cannot start a call.

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

    started = not (client.detection_running or client.fall_detected)
    if started:
        asyncio.create_task(client.run_detection())
        detail = "scripted detection started; no incident raised, waiting on a human tap"
    else:
        detail = "detection already run; no incident raised, waiting on a human tap"

    raised_incident_id: str | None = None
    if simulate_human_tap:
        # Exactly the path POST /v1/incident takes. RaisedBy.USER is not a
        # label of convenience here: assert_human_released refuses anything
        # else on the way to the call.
        incident = await client.raise_incident(IncidentType.FAINT, RaisedBy.USER, None)
        raised_incident_id = incident.incident_id
        detail += "; simulated human tap raised a faint incident"

    return DemoRunAck(started=started, detail=detail, raised_incident_id=raised_incident_id)


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
