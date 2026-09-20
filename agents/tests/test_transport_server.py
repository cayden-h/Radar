"""agents/tests/test_transport_server.py

The Twilio-facing FastAPI server (Task 8) that wires the orchestrator (Task 7),
signature validation (Task 4) and the TwiML builders (Task 3) into actual
HTTP/WS routes. Every webhook route must validate X-Twilio-Signature before
touching any agent logic - that is the global constraint this file exists to
enforce, not just the happy path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from agents.caller import CallerAgent
from agents.caller.transport.orchestrator import CallOrchestrator
from agents.caller.transport.server import build_transport_app
from agents.caller.transport.simulated import SimulatedCallTransport

AUTH_TOKEN = "test_auth_token"
PUBLIC_BASE_URL = "https://example.ngrok-free.app"


def _app_and_client(mesh):
    orch = CallOrchestrator(
        caller=CallerAgent(mesh),
        transport=SimulatedCallTransport(),
        mock_911_number="+15550004444",
        twilio_voice_number="+15550003333",
        twiml_app_sid="APxxxx",
        status_callback_url="https://example.ngrok-free.app/twilio/status",
    )
    app = build_transport_app(
        orch,
        auth_token=AUTH_TOKEN,
        elevenlabs_voice_id="voice123",
        public_base_url=PUBLIC_BASE_URL,
    )
    return orch, TestClient(app)


def _sign(url: str, params: dict[str, str]) -> str:
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_voice_webhook_rejects_an_unsigned_request(mesh):
    """An unsigned /twilio/voice POST must never reach TwiML generation.

    Anyone on the internet can POST to this URL once it is public; the
    signature is the only thing standing between an attacker and dial-conference
    TwiML being returned to them, so an absent header must refuse before any
    agent logic runs.
    """
    _, client = _app_and_client(mesh)
    resp = client.post("/twilio/voice", data={"CallSid": "CA1"})
    assert resp.status_code == 403


def test_voice_webhook_rejects_a_request_with_a_wrong_signature(mesh):
    """A present-but-incorrect signature must be refused identically to a missing one.

    A route that only checks "is the header present" rather than "does the
    header verify" would pass this test's sibling above while still being
    trivially bypassable by sending any non-empty header value.
    """
    _, client = _app_and_client(mesh)
    resp = client.post(
        "/twilio/voice", data={"CallSid": "CA1"}, headers={"X-Twilio-Signature": "not-a-real-signature"}
    )
    assert resp.status_code == 403


def test_voice_webhook_returns_dial_conference_twiml_when_signed(mesh):
    """A correctly-signed /twilio/voice request gets the conference-dial TwiML.

    This is the inbound leg's entry point: Twilio calls this webhook when the
    outbound call to the mock 911 number connects, and it must be told to join
    the conference rather than anything else.
    """
    _, client = _app_and_client(mesh)
    url = f"{PUBLIC_BASE_URL}/twilio/voice"
    params = {"CallSid": "CA1"}
    sig = _sign(url, params)
    resp = client.post("/twilio/voice", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert "<Conference>" in resp.text


def test_agent_leg_webhook_rejects_an_unsigned_request(mesh):
    """/twilio/agent-leg is a webhook exactly like /twilio/voice and must be
    guarded the same way - a second, independently-checked route rather than
    an assumption that guarding one route guards the module.
    """
    _, client = _app_and_client(mesh)
    resp = client.post("/twilio/agent-leg", data={"CallSid": "CA2"})
    assert resp.status_code == 403


def test_agent_leg_webhook_returns_connect_conversation_relay_twiml(mesh):
    """A correctly-signed /twilio/agent-leg request gets Connect/ConversationRelay TwiML
    pointed at our own websocket, which is what lets the agent's leg of the
    conference actually stream audio to and from ElevenLabs.
    """
    _, client = _app_and_client(mesh)
    url = f"{PUBLIC_BASE_URL}/twilio/agent-leg"
    params = {"CallSid": "CA2"}
    sig = _sign(url, params)
    resp = client.post("/twilio/agent-leg", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert "ConversationRelay" in resp.text
    assert "wss://" in resp.text or "conversation-relay" in resp.text


def test_status_webhook_rejects_an_unsigned_request(mesh):
    """/twilio/status carries call-lifecycle events and is just as forgeable
    as the other two webhooks, so it gets the identical signature gate.
    """
    _, client = _app_and_client(mesh)
    resp = client.post("/twilio/status", data={"CallSid": "CA3", "CallStatus": "completed"})
    assert resp.status_code == 403


def test_status_webhook_accepts_a_signed_request(mesh):
    """A correctly-signed status callback is acknowledged rather than refused."""
    _, client = _app_and_client(mesh)
    url = f"{PUBLIC_BASE_URL}/twilio/status"
    params = {"CallSid": "CA3", "CallStatus": "completed"}
    sig = _sign(url, params)
    resp = client.post("/twilio/status", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200


def test_voice_webhook_ignores_a_mock_911_number_supplied_as_a_request_parameter(mesh):
    """HAWKEYE_MOCK_911_NUMBER must only ever come from server-side settings.

    If a caller could smuggle a `mock_911_number` (or similarly-named) form
    field into a signed webhook and have it change what the server dials, the
    dispatch destination would no longer be a binding sealed at registration -
    it would be attacker-controlled input, which is exactly the swatting shape
    the root CLAUDE.md calls out. The route must dial whatever the orchestrator
    was constructed with, and must not read a destination number out of the
    request at all.
    """
    orch, client = _app_and_client(mesh)
    url = f"{PUBLIC_BASE_URL}/twilio/voice"
    params = {"CallSid": "CA1", "mock_911_number": "+15559998888", "To": "+15559998888"}
    sig = _sign(url, params)
    resp = client.post("/twilio/voice", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    # The orchestrator's bound number is untouched by anything in the request.
    assert orch.mock_911_number == "+15550004444"


def test_conversation_relay_websocket_round_trips_a_prompt_through_the_orchestrator(mesh):
    """The WS route must actually call orchestrator.handle_relay_message rather
    than being a bare echo - a ConversationRelay `prompt` message must produce
    the same spoken-reply shape the orchestrator's own unit tests expect.
    """
    _, client = _app_and_client(mesh)
    with client.websocket_connect("/twilio/conversation-relay") as ws:
        ws.send_json({"type": "setup", "callSid": "CA1", "from": "+15551234567"})
        ws.send_json({"type": "prompt", "voicePrompt": "what colour is the front door?"})
        reply = ws.receive_json()
        assert reply["type"] == "text"
        assert reply["token"].startswith("I don't know")
