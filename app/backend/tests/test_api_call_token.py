"""GET /v1/incident/{incident_id}/call-token — a real Twilio Voice Access Token.

Twilio Access Tokens are self-contained signed JWTs minted locally with an API
Key/Secret pair and a TwiML Application SID; minting one makes no network call,
so these tests exercise the real `twilio` SDK's `AccessToken`/`VoiceGrant`
classes end to end rather than faking them, following Task 11's pattern of
exercising the real request/response shape through `TestClient`.
"""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings, reset_settings
from hawkeye_backend.main import create_app


@pytest.fixture
def configured_settings() -> Settings:
    return Settings(
        mode="simulated",
        twilio_account_sid="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        twilio_api_key_sid="SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        twilio_api_key_secret="test-secret",
        twilio_application_sid="APxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    )


@pytest.fixture
def client(configured_settings):
    reset_settings()
    app = create_app(configured_settings)
    with TestClient(app) as c:
        yield c
    reset_settings()


@pytest.fixture
def unconfigured_client():
    reset_settings()
    app = create_app(Settings(mode="simulated"))
    with TestClient(app) as c:
        yield c
    reset_settings()


def _raise_incident(client) -> str:
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    assert resp.status_code == 202
    return resp.json()["incident_id"]


def test_call_token_for_a_known_incident_is_a_valid_voice_grant_jwt(client):
    incident_id = _raise_incident(client)

    resp = client.get(f"/v1/incident/{incident_id}/call-token")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"access_token"}
    token = body["access_token"]
    assert isinstance(token, str) and token

    # Twilio Access Tokens are JWTs signed with the API Key Secret as an HMAC
    # key, with the API Key SID as `iss`/`sub`... decoding with the same
    # secret confirms the SDK actually signed it, not just returned a string.
    claims = jwt.decode(
        token,
        "test-secret",
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    assert claims["iss"] == "SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    grants = claims["grants"]
    assert grants["identity"] == f"resident-{incident_id}"
    assert grants["voice"]["outgoing"]["application_sid"] == "APxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def test_call_token_for_an_unknown_incident_is_404(client):
    resp = client.get("/v1/incident/does-not-exist/call-token")
    assert resp.status_code == 404


def test_call_token_without_twilio_voice_credentials_is_503(unconfigured_client):
    incident_id = _raise_incident(unconfigured_client)
    resp = unconfigured_client.get(f"/v1/incident/{incident_id}/call-token")
    assert resp.status_code == 503
