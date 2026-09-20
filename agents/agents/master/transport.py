"""agents/agents/master/transport.py

The two call-bridge hops `app/backend/hawkeye_backend/master/live.py`'s
`LiveMasterClient` has been POSTing to since before `agents/master` existed as
running code: `POST /a2a/start-call` and `POST /a2a/set-mode`, named
`PATH_START_CALL` / `PATH_SET_MODE` there. That file's own docstring marks
every path it calls as `# TODO(master): ... not a contract agents/master has
agreed to`; this module is that contract, for exactly these two paths and no
others.

Scope, stated explicitly because it is easy to over-grow: this does **not**
add `/v1/state`, `/v1/sensor`, `/v1/agents`, or a general-purpose
`/v1/incident` route. Those remain the separate, larger, pre-existing gap
`live.py` documents. The only reason `/a2a/start-call` can do anything useful
here is that its request body carries enough of an incident inline to call
`MasterAgent.raise_incident(...)` itself - see `StartCallRequest` below - not
because this module grew a general incident API.

**`/a2a/start-call` is two calls in sequence on purpose**: `raise_incident`
first, then `release_for_call`. That ordering is what lets
`AutonomousDialRefused` fire exactly as it already does for any
non-user-raised incident (see `agents/master/agent.py` and
`tests/test_trust.py::test_a_system_raised_incident_cannot_reach_release`) -
a `raised_by` that is not `RaisedBy.USER` reaches `release_for_call` and is
refused there, and the request never proceeds to call `agents/caller`'s
transport server. The safety-critical property this module exists to
preserve is that ordering: the guard runs, and only a 200 past it triggers a
call to a human being.

`/a2a/set-mode` mirrors `_MODE_LEVEL` from
`app/backend/hawkeye_backend/master/simulated.py`'s
`SimulatedMasterClient.set_participation_mode`: automation may only ever move
a call toward quieter. `MasterAgent.set_participation_mode` holds that guard;
this module is just its HTTP face, translating `ParticipationModeRefused`
into the 403 `LiveMasterClient` already knows how to turn into
`ParticipationModeRefused` on its own side of the wire.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from hawkeye_backend.models.incident import IncidentType, RaisedBy

from .agent import AutonomousDialRefused, MasterAgent, ParticipationModeRefused

logger = logging.getLogger(__name__)

#: The trigger routes on agents/caller's Twilio-facing transport server (see
#: agents/caller/transport/server.py) that this module calls into after its
#: own guards pass. Plain HTTP, not ANS - this hop is process-to-process
#: within our own deployment, the same way caller's transport server already
#: talks plain HTTP to Twilio rather than A2A.
CALLER_TRIGGER_START_CALL = "/internal/start-call"
CALLER_TRIGGER_SET_MODE = "/internal/set-mode"


class StartCallRequest(BaseModel):
    """The body `LiveMasterClient.start_call` sends to `POST /a2a/start-call`.

    Carries enough of the incident for this handler to call
    `MasterAgent.raise_incident(...)` inline, because nothing has yet called
    that method over HTTP for this incident - there is no `/v1/incident`
    route (out of scope; see module docstring) and `app/backend` is the only
    side holding the full `Incident` at this point in the flow.
    """

    incident_id: str
    incident_type: IncidentType
    raised_by: RaisedBy
    address: str
    note: str | None = None


class SetModeRequest(BaseModel):
    """The body `LiveMasterClient.set_participation_mode` sends to `POST /a2a/set-mode`."""

    incident_id: str
    mode: str
    by_human: bool = False


def attach_call_bridge_routes(
    app: FastAPI,
    agent: MasterAgent,
    *,
    caller_client: httpx.AsyncClient | None,
) -> None:
    """Add `POST /a2a/start-call` and `POST /a2a/set-mode` to `app`.

    `app` is the same FastAPI app `agents.core.runtime.build_app()` returned
    for this process - this function is called on it afterward, exactly the
    pattern `agents/__main__.py` already uses to add a second server's worth
    of routes for `caller`.

    `caller_client` is an `httpx.AsyncClient` already pointed at
    `agents/caller`'s transport server (base_url set by the caller of this
    function, typically from `HAWKEYE_CALLER_TRANSPORT_URL`). Passed in
    rather than constructed here so a test can hand this a client wired to
    `httpx.MockTransport` and assert on exactly how many requests it made -
    in particular, that a refused `/a2a/start-call` makes zero. `None` means
    this deployment has not been told where caller's transport server is;
    both routes below fail closed with a 500 rather than silently doing
    nothing, per the fail-loud style already used in
    `agents/caller/transport/server.py`.
    """

    async def _trigger_caller(path: str, body: dict[str, object]) -> httpx.Response:
        if caller_client is None:
            raise RuntimeError(
                "HAWKEYE_CALLER_TRANSPORT_URL is not configured on this master "
                "process; agents/master has no way to reach agents/caller's "
                "transport server to trigger a call."
            )
        return await caller_client.post(path, json=body)

    @app.post("/a2a/start-call")
    async def start_call(payload: StartCallRequest) -> JSONResponse:
        try:
            agent.raise_incident(
                payload.incident_type,
                payload.raised_by,
                payload.note,
                incident_id=payload.incident_id,
            )
            incident = agent.release_for_call()
        except AutonomousDialRefused as exc:
            # The safety-critical path: refused here, and nothing below this
            # point runs. agents/caller's transport server is never called.
            logger.warning(
                "refused to release incident %s for a call: %s", payload.incident_id, exc
            )
            return JSONResponse(
                status_code=403,
                content={"error": "autonomous_dial_refused", "detail": str(exc)},
            )

        try:
            response = await _trigger_caller(
                CALLER_TRIGGER_START_CALL,
                {
                    "incident_id": incident.incident_id,
                    "incident_type": incident.incident_type.value,
                    "address": payload.address,
                },
            )
            response.raise_for_status()
        except RuntimeError as exc:
            logger.error("cannot trigger agents/caller: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": "caller_transport_not_configured", "detail": str(exc)},
            )
        except httpx.HTTPError as exc:
            logger.exception(
                "failed to trigger agents/caller's transport server for incident %s",
                incident.incident_id,
            )
            return JSONResponse(
                status_code=502,
                content={"error": "caller_unreachable", "detail": str(exc)},
            )

        return JSONResponse(status_code=200, content={"incident_id": incident.incident_id})

    @app.post("/a2a/set-mode")
    async def set_mode(payload: SetModeRequest) -> JSONResponse:
        try:
            agent.set_participation_mode(payload.mode, by_human=payload.by_human)
        except ParticipationModeRefused as exc:
            return JSONResponse(
                status_code=403,
                content={"error": "participation_mode_refused", "detail": str(exc)},
            )

        try:
            response = await _trigger_caller(
                CALLER_TRIGGER_SET_MODE,
                {"mode": payload.mode, "by_human": payload.by_human},
            )
            response.raise_for_status()
        except RuntimeError as exc:
            logger.error("cannot trigger agents/caller: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": "caller_transport_not_configured", "detail": str(exc)},
            )
        except httpx.HTTPError as exc:
            logger.exception(
                "failed to forward the mode change for incident %s to agents/caller",
                payload.incident_id,
            )
            return JSONResponse(
                status_code=502,
                content={"error": "caller_unreachable", "detail": str(exc)},
            )

        body = response.json()
        announcement = body.get("announcement", "") if isinstance(body, dict) else ""
        return JSONResponse(status_code=200, content={"announcement": announcement})
