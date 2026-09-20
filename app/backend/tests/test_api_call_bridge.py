"""POST /v1/incident starts a call; POST /v1/incident/{id}/mode switches it.

The safety-relevant claim under test: `POST /v1/incident` only ever produces
a USER-raised incident (see `post_incident` in `hawkeye_backend/api.py`,
which hardcodes `RaisedBy.USER`), so the `AutonomousDialRefused` guard in
`assert_human_released` is never actually tripped by this route in practice.
These tests exercise the happy path (call starts, mode can be lowered by a
human) and the mode-refusal path (automation may only ever move quieter).
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


def test_raising_an_incident_starts_a_call(client):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    assert resp.status_code == 202
    incident_id = resp.json()["incident_id"]
    mode_resp = client.post(
        f"/v1/incident/{incident_id}/mode", json={"mode": "whisper", "by_human": True}
    )
    assert mode_resp.status_code == 200
    assert "announcement" in mode_resp.json()


def test_an_automated_mode_escalation_is_refused_with_409(client):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    incident_id = resp.json()["incident_id"]
    mode_resp = client.post(
        f"/v1/incident/{incident_id}/mode", json={"mode": "full_voice", "by_human": False}
    )
    assert mode_resp.status_code == 409
