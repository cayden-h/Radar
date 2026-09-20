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
from starlette.websockets import WebSocketDisconnect

from agents.caller import CallerAgent
from agents.caller.transport.orchestrator import CallOrchestrator
from agents.caller.transport.server import build_transport_app
from agents.caller.transport.simulated import SimulatedCallTransport

AUTH_TOKEN = "test_auth_token"
PUBLIC_BASE_URL = "https://example.ngrok-free.app"
INTERNAL_TOKEN = "test_internal_trigger_token"


def _app_and_client(mesh, *, auth_token: str | None = AUTH_TOKEN, internal_trigger_token: str | None = INTERNAL_TOKEN):
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
        auth_token=auth_token,
        elevenlabs_voice_id="voice123",
        public_base_url=PUBLIC_BASE_URL,
        internal_trigger_token=internal_trigger_token,
    )
    return orch, TestClient(app)


def _mint_relay_token(orch, client) -> str:
    """Drive the real /twilio/agent-leg webhook so the orchestrator mints the
    per-call ConversationRelay token exactly the way a real call would.
    """
    url = f"{PUBLIC_BASE_URL}/twilio/agent-leg"
    params = {"CallSid": "CA2"}
    sig = _sign(url, params)
    resp = client.post("/twilio/agent-leg", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert orch.relay_ws_token
    return orch.relay_ws_token


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


def test_unconfigured_transport_app_rejects_the_voice_webhook_even_when_signed(mesh):
    """When Twilio voice isn't configured, `auth_token` is `None` rather than
    falling back to a known constant like "test_auth_token" - a string that is
    printed in this very test suite and would let anyone who read the repo
    forge valid-looking signed requests against a publicly reachable but
    unconfigured instance. An unconfigured app must refuse every request, even
    one signed against that old fallback constant, rather than accept it.
    """
    _, client = _app_and_client(mesh, auth_token=None)
    url = f"{PUBLIC_BASE_URL}/twilio/voice"
    params = {"CallSid": "CA1"}
    sig = _sign(url, params)  # signed with the old fallback constant
    resp = client.post("/twilio/voice", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 503
    assert "<Conference>" not in resp.text


def test_unconfigured_transport_app_rejects_the_agent_leg_webhook(mesh):
    """Same fail-closed behaviour on /twilio/agent-leg as on /twilio/voice -
    guarding one route and not the others would leave the unconfigured case
    only partially closed.
    """
    _, client = _app_and_client(mesh, auth_token=None)
    resp = client.post("/twilio/agent-leg", data={"CallSid": "CA2"})
    assert resp.status_code == 503


def test_conversation_relay_websocket_round_trips_a_prompt_through_the_orchestrator(mesh):
    """The WS route must actually call orchestrator.handle_relay_message rather
    than being a bare echo - a ConversationRelay `prompt` message must produce
    the same spoken-reply shape the orchestrator's own unit tests expect.

    Connecting with the correct per-call token (minted by /twilio/agent-leg,
    exactly as a real call would) must still work end to end.
    """
    orch, client = _app_and_client(mesh)
    token = _mint_relay_token(orch, client)
    with client.websocket_connect(f"/twilio/conversation-relay?token={token}") as ws:
        ws.send_json({"type": "setup", "callSid": "CA1", "from": "+15551234567"})
        ws.send_json({"type": "prompt", "voicePrompt": "what colour is the front door?"})
        reply = ws.receive_json()
        assert reply["type"] == "text"
        assert reply["token"].startswith("I don't know")


def test_conversation_relay_websocket_rejects_a_connection_with_no_token(mesh):
    """Twilio never sends X-Twilio-Signature on a WS handshake, so this route's
    only defence against an arbitrary internet connection is the per-call
    token minted by /twilio/agent-leg. A connection presenting none of it must
    be refused before a single frame reaches `orchestrator.handle_relay_message`,
    which mutates the shared transcript and can trigger agent speech.
    """
    orch, client = _app_and_client(mesh)
    _mint_relay_token(orch, client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/twilio/conversation-relay"):
            pass
    # Nothing this connection could have sent was ever handed to the
    # orchestrator - the transcript, which only handle_relay_message mutates,
    # is untouched.
    assert orch.transcript_so_far() == []


def test_conversation_relay_websocket_rejects_a_connection_with_the_wrong_token(mesh):
    """A present-but-incorrect token must be refused identically to a missing
    one - the same principle the signed-webhook tests above establish for
    X-Twilio-Signature applies here too.
    """
    orch, client = _app_and_client(mesh)
    _mint_relay_token(orch, client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/twilio/conversation-relay?token=not-the-real-token"):
            pass
    assert orch.transcript_so_far() == []


def test_unconfigured_transport_app_rejects_a_conversation_relay_connection(mesh):
    """When Twilio voice isn't configured (`auth_token=None`), the WS route
    must fail closed exactly like every HTTP webhook below - there is no
    per-call token minted (agent-leg itself is unreachable, see the HTTP test
    below), and even a connection that somehow presents one must still be
    refused rather than reaching the orchestrator.
    """
    _, client = _app_and_client(mesh, auth_token=None)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/twilio/conversation-relay?token=anything"):
            pass


# ---------------------------------------------------- /internal/start-call and /internal/set-mode
#
# These are the trigger routes `agents/master/transport.py`'s `/a2a/start-call`
# and `/a2a/set-mode` handlers POST into, over plain HTTP, once master's own
# guards (AutonomousDialRefused, ParticipationModeRefused) have already
# passed. They carry no X-Twilio-Signature - Twilio never calls them - so
# they are gated by a separate bearer token instead, and must fail exactly as
# closed as every Twilio-facing route above when that token is absent, wrong,
# or missing.


def test_internal_start_call_rejects_a_request_with_no_token(mesh):
    """No Authorization header at all must be refused, not treated as an
    internal, trusted caller - this server is reachable on the public
    internet like every agent in this project, not just from agents/master.
    """
    _, client = _app_and_client(mesh)
    resp = client.post(
        "/internal/start-call",
        json={"incident_id": "inc-1", "incident_type": "burglary", "address": "1872 Ridgeview Lane"},
    )
    assert resp.status_code == 403


def test_internal_start_call_rejects_the_wrong_token(mesh):
    """A present-but-incorrect bearer token is refused identically to a missing
    one, the same principle already established for X-Twilio-Signature above.
    """
    _, client = _app_and_client(mesh)
    resp = client.post(
        "/internal/start-call",
        json={"incident_id": "inc-1", "incident_type": "burglary", "address": "1872 Ridgeview Lane"},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert resp.status_code == 403


def test_internal_start_call_with_the_correct_token_places_the_call(mesh):
    """A correctly-authorized trigger actually invokes
    `CallOrchestrator.start_call`, which is what this route exists for -
    the conference name it produces must show up on the orchestrator.
    """
    orch, client = _app_and_client(mesh)
    resp = client.post(
        "/internal/start-call",
        json={"incident_id": "inc-2", "incident_type": "burglary", "address": "1872 Ridgeview Lane"},
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["conference_name"] == "incident-inc-2"
    assert orch.conference_name == "incident-inc-2"


def test_unconfigured_internal_trigger_token_rejects_start_call_even_when_bearing_a_token(mesh):
    """When `HAWKEYE_INTERNAL_TRIGGER_TOKEN` isn't set, `internal_trigger_token`
    is `None` rather than falling back to a known constant - same rule
    `auth_token=None` follows for the Twilio-facing routes, same reason: a
    fallback string printed in this test suite must not be a usable secret
    against a publicly reachable but unconfigured instance.
    """
    _, client = _app_and_client(mesh, internal_trigger_token=None)
    resp = client.post(
        "/internal/start-call",
        json={"incident_id": "inc-3", "incident_type": "burglary", "address": "x"},
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )
    assert resp.status_code == 503


def test_internal_set_mode_rejects_an_unauthorized_request(mesh):
    """Same token gate applies to /internal/set-mode independently of
    /internal/start-call - guarding one route must not be assumed to guard
    the other.
    """
    _, client = _app_and_client(mesh)
    resp = client.post("/internal/set-mode", json={"mode": "full_voice", "by_human": True})
    assert resp.status_code == 403


def test_internal_set_mode_with_the_correct_token_changes_the_bridge(mesh):
    """A correctly-authorized, human-confirmed mode change reaches
    `CallOrchestrator.set_mode` and returns its announcement text.
    """
    _, client = _app_and_client(mesh)
    resp = client.post(
        "/internal/set-mode",
        json={"mode": "full_voice", "by_human": True},
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )
    assert resp.status_code == 200
    assert "announcement" in resp.json()


def test_internal_set_mode_refuses_automation_moving_louder(mesh):
    """`agents/caller`'s own `Bridge.set_mode` guard
    (`ModeChangeRefused`) must still stand behind this route even though
    `agents/master` is expected to have already refused this upstream - a
    second, independent check, not a redundant one, since this route has no
    way to know whether its caller actually checked.
    """
    _, client = _app_and_client(mesh)
    resp = client.post(
        "/internal/set-mode",
        json={"mode": "full_voice", "by_human": False},
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"},
    )
    assert resp.status_code == 403
