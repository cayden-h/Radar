"""What agents/caller posts as each transcript line is spoken, and what every
app then sees. Mirrors test_vision_api.py's narration coverage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


@pytest.fixture
def client():
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_a_transcript_line_reaches_every_stream_subscriber(client: TestClient):
    """The property the whole integration exists for: one producer, one funnel,
    every surface."""
    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()  # hello

        response = client.post(
            "/v1/incident/inc-1/transcript",
            json={"speaker": "operator", "text": "What is your emergency?"},
        )
        assert response.status_code == 202

        while (envelope := ws.receive_json())["payload"]["kind"] != "transcript":
            pass

    payload = envelope["payload"]
    assert payload["line"]["text"] == "What is your emergency?"
    assert payload["line"]["speaker"] == "operator"
    assert payload["line"]["incident_id"] == "inc-1"


def test_caller_line_carries_agent_provenance(client: TestClient):
    response = client.post(
        "/v1/incident/inc-1/transcript",
        json={"speaker": "caller", "text": "There is an incident in progress."},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["line"]["provenance"]["producer"] == "agents/caller"
    assert body["line"]["provenance"]["ansname"] is not None


def test_operator_line_carries_human_provenance(client: TestClient):
    response = client.post(
        "/v1/incident/inc-1/transcript",
        json={"speaker": "operator", "text": "Units are on the way."},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["line"]["provenance"]["source"] == "operator-audio"


def test_resident_line_is_not_mislabelled_as_operator_audio(client: TestClient):
    """A resident speaking on the call (whisper or full voice) must never be
    recorded as PSAP operator audio in the forensic record."""
    response = client.post(
        "/v1/incident/inc-1/transcript",
        json={"speaker": "resident", "text": "He's in the kitchen, I'm upstairs."},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["line"]["provenance"]["source"] == "user-input"
    assert body["line"]["provenance"]["source"] != "operator-audio"
    assert body["line"]["provenance"]["producer"] == "resident"


def test_system_line_is_not_mislabelled_as_operator_audio(client: TestClient):
    """A non-speech system annotation, e.g. 'call connected', must never be
    recorded as PSAP operator audio."""
    response = client.post(
        "/v1/incident/inc-1/transcript",
        json={"speaker": "system", "text": "Call connected."},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["line"]["provenance"]["source"] != "operator-audio"
    assert body["line"]["provenance"]["producer"] == "hawkeye_backend"
