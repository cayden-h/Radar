"""The HTTP and websocket surface the iOS app talks to.

Six capabilities, per app/CLAUDE.md:

  GET  /v1/hub                      hub identity and health, for the Connect screen
  GET  /v1/state                    interior state, for the 3D view
  WS   /v1/stream                   the live push channel
  POST /v1/incident                 the resident raises an incident
  POST /v1/incident/{id}/context    the "what is happening" box
  GET  /v1/incident/{id}/replay     the sealed post-incident record

Plus POST /v1/demo/run, which drives the scripted detection in simulated mode and
404s in live mode. It exists so scripts/demo.sh has something to hit. It stops at
the detection: Hawk Eye never calls 911 on its own (settled 2026-09-19), so the
call runs only once a person taps, and `?simulate_human_tap=true` is the explicit
opt-in that stands in for that person.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from hawkeye_backend import __version__
from hawkeye_backend.household import DeviceAlreadyClaimed, UnknownDevice
from hawkeye_backend.master.base import MasterUnavailable
from hawkeye_backend.master.simulated import SimulatedMasterClient
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


class HouseholdResponse(BaseModel):
    """The roster. A list rather than a bare array so the shape can grow."""

    members: list[HouseholdMember]


class UnclaimedDevicesResponse(BaseModel):
    devices: list[ObservedDevice]


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


@router.delete("/household/members/{member_id}", status_code=204, summary="Forget a member")
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
