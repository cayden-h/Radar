"""POST /v1/incident/{id}/context with speak_on_call routes the note to caller.

Task 4: hub -> master -> caller forwarding of resident notes. `ContextRequest`
gained `speak_on_call: bool = False`; when set, `post_context` also calls the
master client's `inject_context(incident_id, text)` after the note is stored,
fail-soft - a failed speak must never fail the note store. `SimulatedMasterClient`
has no real caller to POST to, so it records onto `injected_context` for this
test to inspect, mirroring what `LiveMasterClient.inject_context` actually sends.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings, reset_settings
from hawkeye_backend.main import create_app


@pytest.fixture
def client():
    reset_settings()
    app = create_app(Settings(mode="simulated"))
    with TestClient(app) as c:
        yield c
    reset_settings()


def _simulated_client(client: TestClient):
    return client.app.state.runtime.client


def test_context_without_speak_on_call_does_not_reach_caller(client):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    incident_id = resp.json()["incident_id"]

    ctx_resp = client.post(
        f"/v1/incident/{incident_id}/context", json={"text": "he has a knife"}
    )

    assert ctx_resp.status_code == 202
    assert _simulated_client(client).injected_context == []


def test_context_with_speak_on_call_forwards_to_caller(client):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    incident_id = resp.json()["incident_id"]

    ctx_resp = client.post(
        f"/v1/incident/{incident_id}/context",
        json={"text": "he has a knife", "speak_on_call": True},
    )

    assert ctx_resp.status_code == 202
    assert _simulated_client(client).injected_context == [(incident_id, "he has a knife")]


def test_speak_on_call_failure_does_not_fail_the_note_store(client, monkeypatch):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    incident_id = resp.json()["incident_id"]

    sim = _simulated_client(client)

    async def _boom(incident_id: str, text: str) -> None:
        raise RuntimeError("caller transport unreachable")

    monkeypatch.setattr(sim, "inject_context", _boom)

    ctx_resp = client.post(
        f"/v1/incident/{incident_id}/context",
        json={"text": "he has a knife", "speak_on_call": True},
    )

    # The note is still stored and acknowledged, despite the speak failing.
    assert ctx_resp.status_code == 202
    assert ctx_resp.json()["text"] == "he has a knife"
