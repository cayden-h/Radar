"""Arm/disarm, proxied through the hub to master.

Motion has always opened the shutter unconditionally on detection; security
mode is the human switch on top of it, and it defaults to disarmed. See
`agents/master/agent.py`'s `security_mode` for the agent-side half of this.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


def _client() -> TestClient:
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    return TestClient(create_app(settings))


def test_security_mode_starts_disarmed():
    with _client() as client:
        response = client.get("/v1/security-mode")
        assert response.status_code == 200
        assert response.json() == {"enabled": False}


def test_arming_and_disarming_round_trips():
    with _client() as client:
        armed = client.post("/v1/security-mode", json={"enabled": True})
        assert armed.status_code == 200
        assert armed.json() == {"enabled": True}

        after = client.get("/v1/security-mode")
        assert after.json() == {"enabled": True}

        disarmed = client.post("/v1/security-mode", json={"enabled": False})
        assert disarmed.json() == {"enabled": False}
