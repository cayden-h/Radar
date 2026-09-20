"""agents/tests/test_master_transport.py

`agents/agents/master/transport.py` adds the two call-bridge hops
`app/backend`'s `LiveMasterClient` has been POSTing to since before
`agents/master` had any HTTP surface for them: `POST /a2a/start-call` and
`POST /a2a/set-mode`. This is the closing task on that gap, scoped to exactly
those two routes - not `/v1/state`, `/v1/incident`, or any other pre-existing
gap in master's surface.

The safety-critical property under test in the first two cases below is not
"the response code is 403" on its own - it is that a non-user-raised
incident makes **zero** requests to agents/caller's transport server. A
route that returns 403 after having already dialed would still be a bug this
project cannot ship.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.master.agent import MasterAgent
from agents.master.transport import attach_call_bridge_routes
from hawkeye_backend.models.incident import IncidentType, RaisedBy


class _RecordingTransport(httpx.AsyncBaseTransport):
    """A fake agents/caller transport server: records every request it saw.

    A test double for the boundary this module crosses, not a mock of the
    module under test. Standing up the real caller transport app plus a real
    Twilio-shaped signature would test a different file; what matters here is
    how many times, and with what body, `agents/master/transport.py` calls
    across that boundary.
    """

    def __init__(self, response_body: dict[str, object] | None = None, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._response_body = response_body or {}
        self._status_code = status_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._response_body)


def _app_and_client(agent: MasterAgent, transport: _RecordingTransport | None):
    app = FastAPI()
    caller_client = (
        httpx.AsyncClient(base_url="http://caller.invalid", transport=transport)
        if transport is not None
        else None
    )
    attach_call_bridge_routes(app, agent, caller_client=caller_client)
    return TestClient(app)


@pytest.fixture
def agent(mesh) -> MasterAgent:
    return MasterAgent(mesh)


def test_start_call_refuses_a_system_raised_incident_and_never_calls_caller(agent, mesh):
    """The AutonomousDialRefused guard must still stand between an incident
    and a placed call at this HTTP hop. A SYSTEM-raised incident must come
    back 403, and agents/caller's transport server must never be contacted -
    the request must not merely fail after dialing, it must not dial.
    """
    transport = _RecordingTransport()
    client = _app_and_client(agent, transport)

    resp = client.post(
        "/a2a/start-call",
        json={
            "incident_id": "inc-0001",
            "incident_type": "burglary",
            "raised_by": "system",
            "address": "1872 Ridgeview Lane, Blacksburg VA",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error"] == "autonomous_dial_refused"
    assert transport.requests == []


def test_start_call_releases_a_user_raised_incident_and_triggers_caller(agent, mesh):
    """The happy path: a USER-raised incident clears `release_for_call` and
    the handler then POSTs exactly once to agents/caller's
    `/internal/start-call`, carrying the incident id, type and address.
    """
    transport = _RecordingTransport(response_body={"conference_name": "incident-inc-0002"})
    client = _app_and_client(agent, transport)

    resp = client.post(
        "/a2a/start-call",
        json={
            "incident_id": "inc-0002",
            "incident_type": "burglary",
            "raised_by": "user",
            "address": "1872 Ridgeview Lane, Blacksburg VA",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"incident_id": "inc-0002"}
    assert len(transport.requests) == 1
    triggered = transport.requests[0]
    assert triggered.url.path == "/internal/start-call"
    import json

    body = json.loads(triggered.content)
    assert body == {
        "incident_id": "inc-0002",
        "incident_type": "burglary",
        "address": "1872 Ridgeview Lane, Blacksburg VA",
    }
    # And master's own state reflects the release.
    assert agent.incident is not None
    assert agent.incident.released_for_call is True


def test_start_call_preserves_the_incident_id_the_hub_minted(agent, mesh):
    """`raise_incident`'s new `incident_id` keyword must actually be used here,
    or the hub's record and master's own would carry two different ids for
    one incident.
    """
    transport = _RecordingTransport()
    client = _app_and_client(agent, transport)

    client.post(
        "/a2a/start-call",
        json={
            "incident_id": "inc-hub-minted",
            "incident_type": "burglary",
            "raised_by": "user",
            "address": "some address",
        },
    )

    assert agent.incident.incident_id == "inc-hub-minted"


def test_start_call_fails_closed_with_500_when_caller_transport_is_not_configured(agent):
    """No `HAWKEYE_CALLER_TRANSPORT_URL` means `caller_client` is `None`.
    That must fail loudly with a 500 rather than silently doing nothing -
    the same fail-loud style every other guard in this project uses.
    """
    client = _app_and_client(agent, transport=None)

    resp = client.post(
        "/a2a/start-call",
        json={
            "incident_id": "inc-0003",
            "incident_type": "burglary",
            "raised_by": "user",
            "address": "some address",
        },
    )

    assert resp.status_code == 500
    assert resp.json()["error"] == "caller_transport_not_configured"


def test_set_mode_refuses_automation_moving_louder_and_never_calls_caller(agent, mesh):
    """Mirrors `_MODE_LEVEL` in `app/backend`'s SimulatedMasterClient:
    automation may only ever move a call toward quieter. `by_human=False`
    requesting something louder than the tracked current mode must be
    refused, and the refusal must happen before agents/caller is contacted.
    """
    transport = _RecordingTransport()
    client = _app_and_client(agent, transport)
    # Open an incident so there is a call to change the mode of.
    client.post(
        "/a2a/start-call",
        json={"incident_id": "inc-0004", "incident_type": "burglary", "raised_by": "user", "address": "x"},
    )
    transport.requests.clear()

    resp = client.post(
        "/a2a/set-mode",
        json={"incident_id": "inc-0004", "mode": "full_voice", "by_human": False},
    )

    assert resp.status_code == 403
    assert resp.json()["error"] == "participation_mode_refused"
    assert transport.requests == []


def test_set_mode_allows_a_human_hand_to_move_louder_and_forwards_to_caller(agent, mesh):
    """A human-confirmed mode change clears master's guard and is forwarded
    to agents/caller's `/internal/set-mode`, and the announcement caller
    returns is relayed back to the hub untouched.
    """
    transport = _RecordingTransport(response_body={"announcement": "Sound on - your phone will be audible."})
    client = _app_and_client(agent, transport)
    client.post(
        "/a2a/start-call",
        json={"incident_id": "inc-0005", "incident_type": "burglary", "raised_by": "user", "address": "x"},
    )
    transport.requests.clear()

    resp = client.post(
        "/a2a/set-mode",
        json={"incident_id": "inc-0005", "mode": "full_voice", "by_human": True},
    )

    assert resp.status_code == 200
    assert resp.json() == {"announcement": "Sound on - your phone will be audible."}
    assert len(transport.requests) == 1
    assert transport.requests[0].url.path == "/internal/set-mode"


def test_set_mode_toward_quieter_needs_no_human_hand(agent, mesh):
    """The asymmetry: moving toward quieter is always allowed, automated or not."""
    transport = _RecordingTransport(response_body={"announcement": "Listening only."})
    client = _app_and_client(agent, transport)
    client.post(
        "/a2a/start-call",
        json={"incident_id": "inc-0006", "incident_type": "burglary", "raised_by": "user", "address": "x"},
    )
    transport.requests.clear()

    resp = client.post(
        "/a2a/set-mode",
        json={"incident_id": "inc-0006", "mode": "watching", "by_human": False},
    )

    assert resp.status_code == 200
    assert len(transport.requests) == 1


def test_inject_context_forwards_to_caller(agent, mesh):
    """A pass-through side channel: the resident's typed note reaches caller.

    Unlike start-call and set-mode, this route carries no dial guard - it
    forwards context for an already-running call rather than authorizing
    anything new. One POST in, one POST out, same body.
    """
    transport = _RecordingTransport()
    client = _app_and_client(agent, transport)

    resp = client.post(
        "/a2a/inject-context",
        json={"incident_id": "inc-1", "text": "he has a knife"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"queued": True}
    assert len(transport.requests) == 1
    triggered = transport.requests[0]
    assert triggered.url.path == "/internal/inject-context"
    import json

    body = json.loads(triggered.content)
    assert body == {"incident_id": "inc-1", "text": "he has a knife"}


def test_inject_context_fails_closed_with_500_when_caller_transport_is_not_configured(agent):
    client = _app_and_client(agent, transport=None)

    resp = client.post(
        "/a2a/inject-context",
        json={"incident_id": "inc-1", "text": "he has a knife"},
    )

    assert resp.status_code == 500
    assert resp.json()["error"] == "caller_transport_not_configured"


def test_inject_context_translates_caller_failure_to_502(agent):
    transport = _RecordingTransport(status_code=500)
    client = _app_and_client(agent, transport)

    resp = client.post(
        "/a2a/inject-context",
        json={"incident_id": "inc-1", "text": "he has a knife"},
    )

    assert resp.status_code == 502
    assert resp.json()["error"] == "caller_unreachable"
