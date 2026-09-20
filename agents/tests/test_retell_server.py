"""The Retell transport server: bearer-gated trigger + gated Custom LLM WS."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent
from agents.caller.transport.retell.client import SimulatedRetellVoiceClient
from agents.caller.transport.retell.orchestrator import RetellCallOrchestrator
from agents.caller.transport.retell.server import build_retell_transport_app
from agents.master import MasterAgent


def _build(mesh, *, secret="s3cr3t", token="tok"):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    orch = RetellCallOrchestrator(
        caller, SimulatedRetellVoiceClient(), from_number="+1", operator_number="+2"
    )
    app = build_retell_transport_app(orch, websocket_secret=secret, internal_trigger_token=token)
    return app, orch


def test_start_call_requires_bearer_token(mesh):
    app, _ = _build(mesh)
    client = TestClient(app)
    resp = client.post(
        "/internal/start-call",
        json={"incident_id": "i1", "incident_type": "burglary", "address": "12 Elm"},
    )
    assert resp.status_code == 403


def test_start_call_with_token_returns_call_id(mesh):
    app, orch = _build(mesh)
    client = TestClient(app)
    resp = client.post(
        "/internal/start-call",
        headers={"Authorization": "Bearer tok"},
        json={"incident_id": "i1", "incident_type": "burglary", "address": "12 Elm"},
    )
    assert resp.status_code == 200
    assert resp.json()["call_id"].startswith("SIM-RETELL-")
    assert orch.call_id is not None


def test_inject_context_requires_bearer_token(mesh):
    app, _ = _build(mesh)
    client = TestClient(app)
    resp = client.post(
        "/internal/inject-context",
        json={"incident_id": "i1", "text": "he has a knife"},
    )
    assert resp.status_code == 403


def test_inject_context_with_token_queues_note(mesh):
    app, orch = _build(mesh)
    client = TestClient(app)
    resp = client.post(
        "/internal/inject-context",
        headers={"Authorization": "Bearer tok"},
        json={"incident_id": "i1", "text": "he has a knife"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"queued": True}
    assert orch._pending_resident_notes == ["he has a knife"]


def test_ws_rejects_wrong_secret(mesh):
    app, orch = _build(mesh)
    client = TestClient(app)
    # start a call so the call_id is known
    client.post(
        "/internal/start-call",
        headers={"Authorization": "Bearer tok"},
        json={"incident_id": "i1", "incident_type": "burglary", "address": "12 Elm"},
    )
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/retell/llm-websocket/wrong/{orch.call_id}") as ws:
            ws.receive_text()


def test_ws_rejects_unknown_call_id(mesh):
    app, orch = _build(mesh)
    client = TestClient(app)
    client.post(
        "/internal/start-call",
        headers={"Authorization": "Bearer tok"},
        json={"incident_id": "i1", "incident_type": "burglary", "address": "12 Elm"},
    )
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/retell/llm-websocket/s3cr3t/not-a-real-call") as ws:
            ws.receive_text()


def test_ws_accepts_started_call_and_sends_config_then_responds(mesh):
    app, orch = _build(mesh)
    client = TestClient(app)
    client.post(
        "/internal/start-call",
        headers={"Authorization": "Bearer tok"},
        json={"incident_id": "i1", "incident_type": "burglary", "address": "12 Elm"},
    )
    with client.websocket_connect(f"/retell/llm-websocket/s3cr3t/{orch.call_id}") as ws:
        config = ws.receive_json()
        assert config["response_type"] == "config"
        ws.send_json({"interaction_type": "response_required", "response_id": 0, "transcript": []})
        reply = ws.receive_json()
        assert reply["response_type"] == "response"
        assert "not a person" in reply["content"]


def test_ws_fails_closed_when_unconfigured(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    orch = RetellCallOrchestrator(
        caller, SimulatedRetellVoiceClient(), from_number="+1", operator_number="+2"
    )
    app = build_retell_transport_app(orch, websocket_secret=None, internal_trigger_token=None)
    client = TestClient(app)
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/retell/llm-websocket/anything/whatever") as ws:
            ws.receive_text()
