"""What vision posts back, and what every app then sees."""

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


def test_a_narration_line_reaches_every_stream_subscriber(client: TestClient):
    """The property the whole integration exists for: one producer, one funnel,
    every surface."""
    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()  # hello

        response = client.post(
            "/v1/vision/narration",
            json={"text": "A person in a dark jacket is by the door.", "room": "Living room"},
        )
        assert response.status_code == 202

        while (envelope := ws.receive_json())["payload"]["kind"] != "narration":
            pass

    payload = envelope["payload"]
    assert payload["text"] == "A person in a dark jacket is by the door."
    assert payload["room"] == "Living room"


def test_narration_carries_its_sampling_window(client: TestClient):
    """Gemini samples about one frame per second, so narration is a sequence of
    observations and not continuous tracking. The root CLAUDE.md requires that
    limit to live in the data, not only in a comment."""
    response = client.post(
        "/v1/vision/narration",
        json={"text": "Someone is standing still.", "room": "Living room", "window_s": 2.5},
    )
    assert response.status_code == 202
    assert response.json()["window_s"] == 2.5


def test_narration_is_never_a_transcript_line(client: TestClient):
    """TranscriptLine means the caller-to-911 conversation. A camera observation
    must not be able to render as something an operator was told."""
    response = client.post(
        "/v1/vision/narration", json={"text": "Someone is there.", "room": "Living room"}
    )
    assert response.json()["kind"] == "narration"


def test_narration_without_a_room_is_refused(client: TestClient):
    """One fixed camera sees one room. A scoped claim must not become an
    unscoped one because a producer left a field out, so scope is required
    rather than defaulted."""
    response = client.post("/v1/vision/narration", json={"text": "Something moved."})
    assert response.status_code == 422


def test_blank_narration_is_refused(client: TestClient):
    response = client.post(
        "/v1/vision/narration", json={"text": "   ", "room": "Living room"}
    )
    assert response.status_code == 422


def test_occupancy_reaches_the_stream(client: TestClient):
    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()
        response = client.post(
            "/v1/vision/occupancy",
            json={"person_present": True, "people": 1, "room": "Living room"},
        )
        assert response.status_code == 202
        while (envelope := ws.receive_json())["payload"]["kind"] != "occupancy":
            pass

    assert envelope["payload"]["person_present"] is True
    assert envelope["payload"]["people"] == 1
