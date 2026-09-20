# Twilio Call Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Per explicit user instruction for this plan: do NOT run code review or debugging after each task. Implement every task straight through, then run one code-review pass and one debugging/test pass at the very end, covering the whole feature.**

**Goal:** Wire `agents/agents/caller`'s existing pure decision logic (`CallerAgent`, `Bridge`, `ResidentChannel`) to an actual Twilio Conference call — a mock "911" PSTN leg (a teammate's phone), a Twilio ConversationRelay leg voiced by ElevenLabs and driven by `CallerAgent`, and the iOS app joining as a third, mutable leg — with a network-free simulated mode that replaces the iOS app's existing hardcoded mock call script.

**Architecture:** `agents/agents/caller` grows a new plain-HTTP/WS transport layer (`transport/`) that Twilio calls into directly (no ANS — this is the same human-facing boundary as the 911 operator's phone line). `app/backend` gains two new `MasterClient` protocol methods (`start_call`, `set_participation_mode`) that tunnel through `master` to `caller`, plus a token-vending endpoint for the iOS Voice SDK. iOS adds the Twilio Voice SDK, new `HawkEyeClienting` methods, and Take Over/whisper/full-voice UI in `IncidentView.swift`. Everything is built test-first against fakes before anything touches a real Twilio/ElevenLabs account.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, `httpx` (no `twilio` SDK — matches the existing `TwilioSink` style), pytest. Swift 6 / SwiftUI, `twilio/twilio-voice-ios` via SPM (the one third-party-dependency exception).

## Global Constraints

- No `twilio` Python SDK — raw `httpx` calls behind a client interface, matching `notices/sinks.py`'s `TwilioSink`.
- Every Twilio webhook route validates `X-Twilio-Signature` before touching any agent logic.
- `HAWKEYE_MOCK_911_NUMBER` is a fixed env value, never accepted as a request parameter anywhere.
- A real Twilio call is placed only when `assert_human_released(incident)` passes (`raised_by is RaisedBy.USER`) — this guard already exists in `master/base.py` and must be called, not re-implemented.
- Secrets load from env only, never logged.
- `agents/` tests: plain `pytest`, no mocking framework, one behavior per test, docstring states *why* the test exists, fixtures for shared state, `pytest.raises(..., match=...)` for refusal paths — match `agents/tests/test_caller.py`'s existing style exactly.
- `app/backend` tests: `pytest` + `pytest-asyncio`, `httpx` fakes — match `app/backend/tests/test_notice_sinks.py`'s existing style.
- iOS: no third-party dependencies except `twilio-voice-ios`. `@MainActor @Observable final class` for any new client-side state, `@ObservationIgnored` for internal driver state — match `MockHawkEyeClient`'s existing pattern.
- `Config.useMocks = true` must still run with **zero network** — the simulated call experience on iOS is a Swift-native scripted implementation of the new feature (CallState transitions, participation-mode changes, a real transcript sequence), not a network call to a Python `SimulatedCallTransport`. It replaces today's ad hoc hardcoded transcript; it does not add a second copy of it.
- Commit after every task.

---

## Part A — `agents/agents/caller`: pure logic and transport (no network in tests)

### Task 1: Twilio Voice + ElevenLabs settings

**Files:**
- Modify: `app/backend/hawkeye_backend/config.py`
- Test: `app/backend/tests/test_config.py` (create if it doesn't already exist; if it does, add to it)

**Interfaces:**
- Produces: `Settings.twilio_voice_number: str`, `Settings.twilio_conference_app_sid: str`, `Settings.mock_911_number: str`, `Settings.elevenlabs_api_key: SecretStr`, `Settings.elevenlabs_voice_id: str`, `Settings.public_base_url: str`, `Settings.twilio_voice_configured: bool` (property).

- [ ] **Step 1: Write the failing test**

```python
import pytest
from hawkeye_backend.config import Settings, reset_settings


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    yield
    reset_settings()


def test_twilio_voice_is_unconfigured_by_default():
    s = Settings()
    assert s.twilio_voice_configured is False


def test_twilio_voice_configured_needs_every_field(monkeypatch):
    monkeypatch.setenv("HAWKEYE_TWILIO_VOICE_NUMBER", "+15550001111")
    monkeypatch.setenv("HAWKEYE_TWILIO_CONFERENCE_APP_SID", "APxxxx")
    monkeypatch.setenv("HAWKEYE_MOCK_911_NUMBER", "+15550002222")
    monkeypatch.setenv("HAWKEYE_ELEVENLABS_API_KEY", "sk_test")
    monkeypatch.setenv("HAWKEYE_ELEVENLABS_VOICE_ID", "voice123")
    s = Settings()
    assert s.twilio_voice_configured is True


def test_missing_one_field_reads_as_unconfigured(monkeypatch):
    monkeypatch.setenv("HAWKEYE_TWILIO_VOICE_NUMBER", "+15550001111")
    # everything else left unset
    s = Settings()
    assert s.twilio_voice_configured is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'twilio_voice_configured'`

- [ ] **Step 3: Add the fields to `Settings`**

In `app/backend/hawkeye_backend/config.py`, alongside the existing `twilio_account_sid`/`twilio_auth_token`/etc. fields, add:

```python
    twilio_voice_number: str = ""
    twilio_conference_app_sid: str = ""
    mock_911_number: str = ""
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    public_base_url: str = ""
```

And alongside the existing `twilio_configured` property:

```python
    @property
    def twilio_voice_configured(self) -> bool:
        return all((
            self.twilio_account_sid,
            self.twilio_auth_token.get_secret_value(),
            self.twilio_voice_number,
            self.twilio_conference_app_sid,
            self.mock_911_number,
            self.elevenlabs_api_key.get_secret_value(),
            self.elevenlabs_voice_id,
            self.public_base_url,
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Add the same env vars to `app/backend/.env.example`**

Append after the existing Twilio SMS block:

```
# ---- Twilio Voice + ElevenLabs, for the call bridge ----
# ALL of these plus the SMS four above are required for a real call. Missing
# any one reads as unconfigured and the call bridge refuses to place a real
# call rather than half-placing one.
HAWKEYE_TWILIO_VOICE_NUMBER=+15550003333
HAWKEYE_TWILIO_CONFERENCE_APP_SID=APxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
HAWKEYE_MOCK_911_NUMBER=+15550004444
HAWKEYE_ELEVENLABS_API_KEY=
HAWKEYE_ELEVENLABS_VOICE_ID=
# ngrok URL in dev; the real deployed host later. Used to build the TwiML App
# and status-callback webhook URLs Twilio calls back into.
HAWKEYE_PUBLIC_BASE_URL=https://your-ngrok-subdomain.ngrok-free.app
```

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/config.py app/backend/tests/test_config.py app/backend/.env.example
git commit -m "Add Twilio Voice and ElevenLabs settings for the call bridge"
```

---

### Task 2: ConversationRelay + TwiML message models

**Files:**
- Create: `agents/agents/caller/transport/__init__.py`
- Create: `agents/agents/caller/transport/models.py`
- Test: `agents/tests/test_transport_models.py`

**Interfaces:**
- Produces: `RelaySetupMessage`, `RelayPromptMessage`, `RelayInterruptMessage`, `RelayTextMessage` (outbound), `parse_relay_message(raw: dict) -> RelaySetupMessage | RelayPromptMessage | RelayInterruptMessage`, `build_text_message(text: str) -> dict`.

Twilio's ConversationRelay WebSocket protocol field names must be confirmed against Twilio's current WebSocket-messages reference (`https://www.twilio.com/docs/voice/conversationrelay/websocket-messages` or wherever it currently resolves) before writing Step 3 below — the design spec flagged this as an open item. Fetch that page first; the field names below (`type`, `callSid`, `voicePrompt`, etc.) are Twilio's documented shape as of the ConversationRelay GA release and should be verified, not assumed, against the live docs at implementation time.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from agents.caller.transport.models import (
    RelayInterruptMessage,
    RelayPromptMessage,
    RelaySetupMessage,
    build_text_message,
    parse_relay_message,
)


def test_setup_message_carries_the_call_sid():
    """The first frame on the socket identifies which call this is, so a
    reconnect or a second incident's socket is never confused with this one."""
    msg = parse_relay_message({"type": "setup", "callSid": "CAxxxx", "from": "+15550002222"})
    assert isinstance(msg, RelaySetupMessage)
    assert msg.call_sid == "CAxxxx"


def test_prompt_message_carries_the_transcribed_speech():
    msg = parse_relay_message({"type": "prompt", "voicePrompt": "what is your emergency"})
    assert isinstance(msg, RelayPromptMessage)
    assert msg.text == "what is your emergency"


def test_interrupt_message_is_recognised():
    """Barge-in: the operator or resident started talking while the agent
    was speaking. The agent must yield, never talk over a human."""
    msg = parse_relay_message({"type": "interrupt"})
    assert isinstance(msg, RelayInterruptMessage)


def test_unknown_message_type_raises_rather_than_silently_dropping():
    with pytest.raises(ValueError, match="unknown ConversationRelay message type"):
        parse_relay_message({"type": "something-new-twilio-added"})


def test_build_text_message_shape():
    assert build_text_message("units are on the way") == {
        "type": "text",
        "token": "units are on the way",
        "last": True,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_transport_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.caller.transport'`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/models.py

Wire-shape for Twilio's ConversationRelay WebSocket protocol. Field names
verified against Twilio's WebSocket-messages reference at implementation
time (docs/superpowers/plans/2026-09-20-twilio-call-bridge.md Task 2 has the
verification note) rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelaySetupMessage:
    call_sid: str
    from_number: str


@dataclass(frozen=True)
class RelayPromptMessage:
    text: str


@dataclass(frozen=True)
class RelayInterruptMessage:
    pass


def parse_relay_message(raw: dict) -> RelaySetupMessage | RelayPromptMessage | RelayInterruptMessage:
    kind = raw.get("type")
    if kind == "setup":
        return RelaySetupMessage(call_sid=raw["callSid"], from_number=raw.get("from", ""))
    if kind == "prompt":
        return RelayPromptMessage(text=raw["voicePrompt"])
    if kind == "interrupt":
        return RelayInterruptMessage()
    raise ValueError(f"unknown ConversationRelay message type: {kind!r}")


def build_text_message(text: str) -> dict:
    return {"type": "text", "token": text, "last": True}
```

Create `agents/agents/caller/transport/__init__.py` empty (or re-export the above — leave empty for now, callers import from `agents.caller.transport.models` directly).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_transport_models.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/__init__.py agents/agents/caller/transport/models.py agents/tests/test_transport_models.py
git commit -m "Add ConversationRelay message models"
```

---

### Task 3: TwiML builders

**Files:**
- Create: `agents/agents/caller/transport/twiml.py`
- Test: `agents/tests/test_twiml.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `dial_conference_twiml(conference_name: str) -> str`, `connect_relay_twiml(websocket_url: str, voice_id: str, welcome_greeting: str | None = None) -> str`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from agents.caller.transport.twiml import connect_relay_twiml, dial_conference_twiml


def test_dial_conference_twiml_names_the_conference():
    xml = dial_conference_twiml("incident-inc-001")
    assert "<Conference>incident-inc-001</Conference>" in xml
    assert xml.startswith("<?xml")


def test_connect_relay_twiml_carries_the_websocket_url_and_voice():
    xml = connect_relay_twiml("wss://example.ngrok-free.app/twilio/conversation-relay", "voice123")
    assert 'url="wss://example.ngrok-free.app/twilio/conversation-relay"' in xml
    assert 'ttsProvider="ElevenLabs"' in xml
    assert 'voice="voice123"' in xml


def test_connect_relay_twiml_never_embeds_the_mock_911_number():
    """The destination is bound in config, never in a TwiML string this
    endpoint could be tricked into building differently."""
    xml = connect_relay_twiml("wss://example.ngrok-free.app/twilio/conversation-relay", "voice123")
    assert "+1555" not in xml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_twiml.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/twiml.py

Builds the TwiML this feature returns from its Twilio webhooks. Deliberately
takes no phone number as an argument anywhere in this module: the mock 911
destination is bound once in Settings and dialed by the orchestrator via the
REST Add Participant call, never interpolated into a TwiML string a webhook
builds per-request.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def dial_conference_twiml(conference_name: str) -> str:
    safe_name = escape(conference_name)
    return f"{_XML_HEADER}<Response><Dial><Conference>{safe_name}</Conference></Dial></Response>"


def connect_relay_twiml(websocket_url: str, voice_id: str, welcome_greeting: str | None = None) -> str:
    safe_url = escape(websocket_url)
    safe_voice = escape(voice_id)
    greeting_attr = f' welcomeGreeting="{escape(welcome_greeting)}"' if welcome_greeting else ""
    return (
        f"{_XML_HEADER}<Response><Connect>"
        f'<ConversationRelay url="{safe_url}" ttsProvider="ElevenLabs" voice="{safe_voice}"{greeting_attr}/>'
        "</Connect></Response>"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_twiml.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/twiml.py agents/tests/test_twiml.py
git commit -m "Add TwiML builders for the conference and ConversationRelay legs"
```

---

### Task 4: Twilio signature validation

**Files:**
- Create: `agents/agents/caller/transport/signature.py`
- Test: `agents/tests/test_signature.py`

**Interfaces:**
- Produces: `validate_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature_header: str) -> bool`.

This is Twilio's standard `X-Twilio-Signature` HMAC-SHA1 scheme: sign the full URL concatenated with each POST param's key+value (params sorted by key), base64-encode the HMAC-SHA1 digest, compare to the header. This is documented and stable; no external lookup needed.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import base64
import hashlib
import hmac

from agents.caller.transport.signature import validate_twilio_signature

AUTH_TOKEN = "test_auth_token"
URL = "https://example.ngrok-free.app/twilio/voice"


def _sign(url: str, params: dict[str, str]) -> str:
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def test_a_correctly_signed_request_validates():
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    sig = _sign(URL, params)
    assert validate_twilio_signature(AUTH_TOKEN, URL, params, sig) is True


def test_a_forged_signature_is_rejected():
    """This is the entire front door. A webhook that skips this check lets
    anyone who finds the ngrok URL inject fake operator speech into a live
    incident."""
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    assert validate_twilio_signature(AUTH_TOKEN, URL, params, "not-a-real-signature") is False


def test_tampering_with_one_param_after_signing_is_rejected():
    params = {"CallSid": "CAxxxx", "From": "+15550002222"}
    sig = _sign(URL, params)
    tampered = {"CallSid": "CAxxxx", "From": "+15559998888"}
    assert validate_twilio_signature(AUTH_TOKEN, URL, tampered, sig) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_signature.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/signature.py

Twilio's request-signing scheme: HMAC-SHA1 over the full request URL plus
every POST param's key and value concatenated in sorted-key order, then
base64-encoded. https://www.twilio.com/docs/usage/security#validating-requests
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def validate_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature_header: str
) -> bool:
    data = url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_signature.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/signature.py agents/tests/test_signature.py
git commit -m "Add Twilio request signature validation"
```

---

### Task 5: `TwilioVoiceClient` interface + real `httpx` implementation

**Files:**
- Create: `agents/agents/caller/transport/twilio_client.py`
- Test: `agents/tests/test_twilio_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `TwilioVoiceClient` protocol with `async def create_conference_call(self, *, to: str, from_: str, conference_name: str, status_callback_url: str) -> str` (returns Call SID), `async def add_conference_participant(self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str) -> str` (returns Call SID), `async def set_participant_mode(self, *, conference_name: str, call_sid: str, muted: bool, coaching: bool = False, call_sid_to_coach: str | None = None) -> None`, `async def end_conference(self, *, conference_name: str) -> None`. `RealTwilioVoiceClient` implementing it, same shape as `TwilioSink` (`_owns_client`, Basic Auth tuple, raw `httpx`, `aclose()`).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import httpx
import pytest

from agents.caller.transport.twilio_client import RealTwilioVoiceClient

ACCOUNT_SID = "ACxxxx"


def _client(handler) -> RealTwilioVoiceClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return RealTwilioVoiceClient(account_sid=ACCOUNT_SID, auth_token="tok", client=http_client)


@pytest.mark.asyncio
async def test_create_conference_call_posts_the_expected_form():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json={"sid": "CA0001"})

    client = _client(handler)
    sid = await client.create_conference_call(
        to="+15550004444",
        from_="+15550003333",
        conference_name="incident-inc-001",
        status_callback_url="https://example.ngrok-free.app/twilio/status",
    )
    assert sid == "CA0001"
    assert len(captured) == 1
    body = captured[0].read().decode()
    assert "To=%2B15550004444" in body
    assert "incident-inc-001" in body  # inside the TwiML in the request
    await client.aclose()


@pytest.mark.asyncio
async def test_add_conference_participant_targets_the_twiml_app():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "app%3AAPxxxx" in body or "app:APxxxx" in body
        return httpx.Response(201, json={"sid": "CA0002"})

    client = _client(handler)
    sid = await client.add_conference_participant(
        conference_name="incident-inc-001",
        twiml_app_sid="APxxxx",
        from_="+15550003333",
        status_callback_url="https://example.ngrok-free.app/twilio/status",
    )
    assert sid == "CA0002"
    await client.aclose()


@pytest.mark.asyncio
async def test_a_twilio_error_response_raises_rather_than_returning_a_fake_sid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "invalid number"})

    client = _client(handler)
    with pytest.raises(RuntimeError, match="Twilio refused"):
        await client.create_conference_call(
            to="+1bad",
            from_="+15550003333",
            conference_name="incident-inc-001",
            status_callback_url="https://example.ngrok-free.app/twilio/status",
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_set_participant_mode_sends_muted_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "Muted=true" in body
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.set_participant_mode(conference_name="incident-inc-001", call_sid="CA0003", muted=True)
    await client.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_twilio_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/twilio_client.py

Raw httpx calls to Twilio's REST API, matching the style of
app/backend/hawkeye_backend/notices/sinks.py's TwilioSink: no `twilio`
package, Basic Auth tuple, own-vs-injected client tracked so aclose() only
closes what this object created.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import httpx

from .twiml import dial_conference_twiml

TWILIO_API = "https://api.twilio.com"


class TwilioVoiceClient(Protocol):
    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str: ...

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str: ...

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None: ...

    async def end_conference(self, *, conference_name: str) -> None: ...


class RealTwilioVoiceClient:
    def __init__(
        self, *, account_sid: str, auth_token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._sid = account_sid
        self._auth = (account_sid, auth_token)
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def _post(self, path: str, data: dict[str, str]) -> dict:
        resp = await self._client.post(
            f"{TWILIO_API}{path}", auth=self._auth, data=data
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Twilio refused {path}: {resp.status_code} {resp.text}")
        return resp.json()

    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str:
        result = await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Calls.json",
            {
                "To": to,
                "From": from_,
                "Twiml": dial_conference_twiml(conference_name),
                "StatusCallback": status_callback_url,
            },
        )
        return result["sid"]

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str:
        result = await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}/Participants.json",
            {
                "To": f"app:{twiml_app_sid}",
                "From": from_,
                "StatusCallback": status_callback_url,
            },
        )
        return result["sid"]

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None:
        data = {"Muted": "true" if muted else "false", "Coaching": "true" if coaching else "false"}
        if call_sid_to_coach:
            data["CallSidToCoach"] = call_sid_to_coach
        await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}/Participants/{call_sid}.json",
            data,
        )

    async def end_conference(self, *, conference_name: str) -> None:
        await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}.json",
            {"Status": "completed"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_twilio_client.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/twilio_client.py agents/tests/test_twilio_client.py
git commit -m "Add the real Twilio Voice REST client"
```

---

### Task 6: `SimulatedCallTransport`

**Files:**
- Create: `agents/agents/caller/transport/simulated.py`
- Test: `agents/tests/test_simulated_call_transport.py`

**Interfaces:**
- Consumes: `CallerAgent` (Task 1's report noted its full method list — use `opening_report`, `answer_operator`), `Bridge`.
- Produces: `SimulatedCallTransport` implementing the same `TwilioVoiceClient` Protocol from Task 5 (so the orchestrator built in Task 7 can use either behind one interface), plus `async def scripted_turns(self) -> AsyncIterator[tuple[str, str]]` yielding `(speaker, text)` pairs on a schedule for the orchestrator to turn into `TranscriptLine`s.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from agents.caller.transport.simulated import SimulatedCallTransport


@pytest.mark.asyncio
async def test_create_conference_call_returns_a_fake_sid_with_no_network():
    transport = SimulatedCallTransport()
    sid = await transport.create_conference_call(
        to="+15550004444",
        from_="+15550003333",
        conference_name="incident-inc-001",
        status_callback_url="https://unused.example/status",
    )
    assert sid.startswith("SIM-CA")


@pytest.mark.asyncio
async def test_set_participant_mode_is_recorded_not_sent_anywhere():
    transport = SimulatedCallTransport()
    await transport.set_participant_mode(conference_name="inc-1", call_sid="SIM-CA1", muted=True)
    assert transport.mode_changes[-1] == {"call_sid": "SIM-CA1", "muted": True, "coaching": False}


@pytest.mark.asyncio
async def test_scripted_turns_yields_operator_and_caller_lines_in_order():
    transport = SimulatedCallTransport()
    turns = [turn async for turn in transport.scripted_turns()]
    assert turns[0][0] == "operator"
    assert any(speaker == "caller" for speaker, _ in turns)
    assert len(turns) >= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_simulated_call_transport.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/simulated.py

No network, no Twilio account, no ElevenLabs account. Drives the exact same
orchestrator code path as RealTwilioVoiceClient (Task 7) so the demo's
fallback and everyday development exercise real Bridge/CallerAgent logic,
never a UI-only stub.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

_SCRIPT: tuple[tuple[str, str], ...] = (
    ("operator", "911, what's your emergency?"),
    ("caller", "A person entered through the back door and does not match anyone on the household roster."),
    ("operator", "Can you describe them?"),
    ("caller", "Dark jacket, medium build, currently in the living room, captured 4 seconds ago."),
    ("operator", "Units are on the way, two minutes out."),
)


class SimulatedCallTransport:
    def __init__(self) -> None:
        self._call_counter = 0
        self.mode_changes: list[dict] = []
        self.ended_conferences: list[str] = []

    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str:
        self._call_counter += 1
        return f"SIM-CA{self._call_counter:04d}"

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str:
        self._call_counter += 1
        return f"SIM-CA{self._call_counter:04d}"

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None:
        self.mode_changes.append({"call_sid": call_sid, "muted": muted, "coaching": coaching})

    async def end_conference(self, *, conference_name: str) -> None:
        self.ended_conferences.append(conference_name)

    async def scripted_turns(self) -> AsyncIterator[tuple[str, str]]:
        for speaker, text in _SCRIPT:
            await asyncio.sleep(0)  # cooperative yield; real timing lives in the orchestrator
            yield speaker, text

    async def aclose(self) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_simulated_call_transport.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/simulated.py agents/tests/test_simulated_call_transport.py
git commit -m "Add SimulatedCallTransport for network-free call testing"
```

---

### Task 7: `CallOrchestrator` — ties `Bridge`/`CallerAgent` to a `TwilioVoiceClient`

**Files:**
- Create: `agents/agents/caller/transport/orchestrator.py`
- Test: `agents/tests/test_call_orchestrator.py`

**Interfaces:**
- Consumes: `CallerAgent` (Task-1-report signatures), `Bridge`/`ParticipationMode`/`Leg`/`ModeChangeRefused` (Task-1-report signatures), `TwilioVoiceClient` Protocol (Task 5), `parse_relay_message`/`build_text_message` (Task 2), `RelayPromptMessage`/`RelaySetupMessage`/`RelayInterruptMessage` (Task 2).
- Produces: `CallOrchestrator` with `def __init__(self, *, caller: CallerAgent, transport: TwilioVoiceClient, mock_911_number: str, twilio_voice_number: str, twiml_app_sid: str, status_callback_url: str) -> None`, `async def start_call(self, incident_id: str, incident_type: IncidentType, address_spoken: str) -> str` (returns conference name, places both legs, records opening report as the first pending line), `async def handle_relay_message(self, raw: dict) -> dict | None` (returns the outbound `{"type": "text", ...}` dict to send back over the WS, or `None` for messages needing no reply), `async def set_mode(self, mode: ParticipationMode, *, by_human: bool) -> str` (delegates to `Bridge.set_mode`, then calls `transport.set_participant_mode` on the resident's leg — raises `ModeChangeRefused` unchanged if the Bridge refuses), `def transcript_so_far(self) -> list[tuple[str, str]]` (speaker, text pairs collected during the call, for the caller to push into `TranscriptEvent`s — this is Task 9's job, not this task's).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent, ModeChangeRefused, ParticipationMode
from agents.caller.transport.orchestrator import CallOrchestrator
from agents.caller.transport.simulated import SimulatedCallTransport


def _orchestrator(mesh) -> CallOrchestrator:
    return CallOrchestrator(
        caller=CallerAgent(mesh),
        transport=SimulatedCallTransport(),
        mock_911_number="+15550004444",
        twilio_voice_number="+15550003333",
        twiml_app_sid="APxxxx",
        status_callback_url="https://unused.example/status",
    )


@pytest.mark.asyncio
async def test_start_call_places_both_legs_and_records_a_conference_name(mesh):
    orch = _orchestrator(mesh)
    conference_name = await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    assert conference_name == "incident-inc-001"


@pytest.mark.asyncio
async def test_a_prompt_message_produces_a_spoken_reply(mesh):
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    reply = await orch.handle_relay_message({"type": "prompt", "voicePrompt": "what colour is the front door?"})
    assert reply is not None
    assert reply["type"] == "text"
    assert reply["token"].startswith("I don't know")


@pytest.mark.asyncio
async def test_an_interrupt_message_produces_no_reply(mesh):
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    reply = await orch.handle_relay_message({"type": "interrupt"})
    assert reply is None


@pytest.mark.asyncio
async def test_set_mode_forwards_to_the_transport_after_the_bridge_allows_it(mesh):
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    await orch.set_mode(ParticipationMode.WHISPER, by_human=True)
    assert orch.transport.mode_changes[-1]["muted"] is False


@pytest.mark.asyncio
async def test_set_mode_refuses_automation_going_louder(mesh):
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    with pytest.raises(ModeChangeRefused):
        await orch.set_mode(ParticipationMode.FULL_VOICE, by_human=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_call_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/orchestrator.py

The seam between Bridge/CallerAgent's pure decision logic and whichever
TwilioVoiceClient is behind it (real or SimulatedCallTransport). Nothing in
here knows or cares which one it has.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hawkeye_backend.models.incident import IncidentType

from ..agent import CallerAgent
from ..bridge import Leg, ParticipationMode
from .models import RelayInterruptMessage, RelayPromptMessage, RelaySetupMessage, build_text_message, parse_relay_message
from .twilio_client import TwilioVoiceClient


@dataclass
class CallOrchestrator:
    caller: CallerAgent
    transport: TwilioVoiceClient
    mock_911_number: str
    twilio_voice_number: str
    twiml_app_sid: str
    status_callback_url: str
    conference_name: str | None = field(default=None, init=False)
    resident_call_sid: str | None = field(default=None, init=False)
    transcript: list[tuple[str, str]] = field(default_factory=list, init=False)

    async def start_call(self, incident_id: str, incident_type: IncidentType, address_spoken: str) -> str:
        self.conference_name = f"incident-{incident_id}"
        await self.transport.create_conference_call(
            to=self.mock_911_number,
            from_=self.twilio_voice_number,
            conference_name=self.conference_name,
            status_callback_url=self.status_callback_url,
        )
        await self.transport.add_conference_participant(
            conference_name=self.conference_name,
            twiml_app_sid=self.twiml_app_sid,
            from_=self.twilio_voice_number,
            status_callback_url=self.status_callback_url,
        )
        for utterance in self.caller.opening_report(incident_type, address_spoken):
            self.transcript.append(("caller", utterance.text))
        return self.conference_name

    async def handle_relay_message(self, raw: dict) -> dict | None:
        message = parse_relay_message(raw)
        if isinstance(message, RelaySetupMessage):
            return None
        if isinstance(message, RelayInterruptMessage):
            self.caller.bridge.yield_to_human()
            return None
        if isinstance(message, RelayPromptMessage):
            self.transcript.append(("operator", message.text))
            reply = self.caller.answer_operator(message.text)
            self.transcript.append(("caller", reply.text))
            return build_text_message(reply.text)
        return None

    async def set_mode(self, mode: ParticipationMode, *, by_human: bool) -> str:
        announcement = self.caller.bridge.set_mode(mode, by_human=by_human)
        if self.resident_call_sid and self.conference_name:
            state = self.caller.bridge.leg_state(Leg.RESIDENT)
            await self.transport.set_participant_mode(
                conference_name=self.conference_name,
                call_sid=self.resident_call_sid,
                muted=not state.send,
            )
        return announcement

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_call_orchestrator.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/orchestrator.py agents/tests/test_call_orchestrator.py
git commit -m "Add CallOrchestrator tying Bridge/CallerAgent to a TwilioVoiceClient"
```

---

### Task 8: Twilio-facing FastAPI server (`transport/server.py`)

**Files:**
- Create: `agents/agents/caller/transport/server.py`
- Test: `agents/tests/test_transport_server.py`

**Interfaces:**
- Consumes: `CallOrchestrator` (Task 7), `validate_twilio_signature` (Task 4), `dial_conference_twiml`/`connect_relay_twiml` (Task 3).
- Produces: `def build_transport_app(orchestrator: CallOrchestrator, *, auth_token: str, elevenlabs_voice_id: str, public_base_url: str) -> FastAPI` exposing `POST /twilio/voice`, `POST /twilio/agent-leg`, `POST /twilio/status`, `WS /twilio/conversation-relay`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agents.caller import CallerAgent
from agents.caller.transport.orchestrator import CallOrchestrator
from agents.caller.transport.server import build_transport_app
from agents.caller.transport.signature import validate_twilio_signature
from agents.caller.transport.simulated import SimulatedCallTransport

AUTH_TOKEN = "test_auth_token"


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
        public_base_url="https://example.ngrok-free.app",
    )
    return orch, TestClient(app)


def _sign(url: str, params: dict[str, str]) -> str:
    import base64
    import hashlib
    import hmac

    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_voice_webhook_rejects_an_unsigned_request(mesh):
    _, client = _app_and_client(mesh)
    resp = client.post("/twilio/voice", data={"CallSid": "CA1"})
    assert resp.status_code == 403


def test_voice_webhook_returns_dial_conference_twiml_when_signed(mesh):
    _, client = _app_and_client(mesh)
    url = "https://example.ngrok-free.app/twilio/voice"
    params = {"CallSid": "CA1"}
    sig = _sign(url, params)
    resp = client.post("/twilio/voice", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert "<Conference>" in resp.text


def test_agent_leg_webhook_returns_connect_conversation_relay_twiml(mesh):
    _, client = _app_and_client(mesh)
    url = "https://example.ngrok-free.app/twilio/agent-leg"
    params = {"CallSid": "CA2"}
    sig = _sign(url, params)
    resp = client.post("/twilio/agent-leg", data=params, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert "ConversationRelay" in resp.text
    assert "wss://" in resp.text or "conversation-relay" in resp.text
```

Note: `TestClient`'s default base URL for a `POST` to a relative path is `http://testserver` unless configured — the test above builds its own signature against the literal `public_base_url` string the route handler is told to expect, matching however Step 3 constructs the URL it verifies against (using `public_base_url + request.url.path`, not `str(request.url)`, specifically so ngrok's external HTTPS URL is what gets verified rather than the internal `http://testserver` one). Implementer note: if this mismatches, adjust the test's `url` variable to match whatever construction Step 3 actually uses — the two must agree, and matching the public URL is the correct choice since that's what Twilio itself signed against.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd agents && python -m pytest tests/test_transport_server.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""agents/agents/caller/transport/server.py

The one part of this feature that is plain HTTP, not ANS — Twilio is a
transport carrying the same human-facing boundary as the 911 operator's
phone line, and that boundary belongs to caller per the root CLAUDE.md.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from .orchestrator import CallOrchestrator
from .signature import validate_twilio_signature
from .twiml import connect_relay_twiml, dial_conference_twiml


def build_transport_app(
    orchestrator: CallOrchestrator, *, auth_token: str, elevenlabs_voice_id: str, public_base_url: str
) -> FastAPI:
    app = FastAPI()

    async def _verified_form(request: Request, path: str) -> dict[str, str]:
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        signature = request.headers.get("X-Twilio-Signature", "")
        url = f"{public_base_url}{path}"
        if not validate_twilio_signature(auth_token, url, params, signature):
            raise HTTPException(status_code=403, detail="invalid Twilio signature")
        return params

    @app.post("/twilio/voice")
    async def voice(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/voice")
        xml = dial_conference_twiml(orchestrator.conference_name or "unassigned-conference")
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/twilio/agent-leg")
    async def agent_leg(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/agent-leg")
        ws_url = public_base_url.replace("https://", "wss://") + "/twilio/conversation-relay"
        xml = connect_relay_twiml(ws_url, elevenlabs_voice_id)
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/twilio/status")
    async def status(request: Request) -> PlainTextResponse:
        await _verified_form(request, "/twilio/status")
        return PlainTextResponse("", media_type="application/xml")

    @app.websocket("/twilio/conversation-relay")
    async def conversation_relay(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_json()
                reply = await orchestrator.handle_relay_message(raw)
                if reply is not None:
                    await websocket.send_json(reply)
        except WebSocketDisconnect:
            return

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd agents && python -m pytest tests/test_transport_server.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/server.py agents/tests/test_transport_server.py
git commit -m "Add the Twilio-facing FastAPI transport server for caller"
```

---

### Task 9: Wire the transport server into `caller`'s process entrypoint

**Files:**
- Modify: `agents/agents/__main__.py`
- Test: manual verification only (this task is process wiring, not new pure logic — no new unit test; the integration is exercised by Task 12's end-to-end check)

**Interfaces:**
- Consumes: `build_transport_app` (Task 8), `CallOrchestrator` (Task 7), `RealTwilioVoiceClient`/`SimulatedCallTransport` (Tasks 5/6), `Settings`/`get_settings` (Task 1).

- [ ] **Step 1: Read the current `agents/agents/__main__.py`** to see how `caller` is currently launched (what serves its A2A router today — likely `uvicorn.run(a2a_router(...))` or similar per-agent block) and match that launch style exactly rather than inventing a new one.

- [ ] **Step 2: Add a second uvicorn server for the transport app**, on a distinct port (e.g. `--transport-port`, default `8107` — pick the next free port after whatever the existing per-agent port scheme uses, checked against `scripts/build_cards.py`'s port assignments in the same read). Select `RealTwilioVoiceClient` when `get_settings().mode == "live"` and `get_settings().twilio_voice_configured`, else `SimulatedCallTransport`, mirroring `build_client`'s selection pattern in `app/backend/hawkeye_backend/main.py` exactly (same env var, same branching shape, so the two "which mode am I in" decisions in the codebase stay visibly identical).

- [ ] **Step 3: Run `caller`'s existing test suite** to confirm nothing about the A2A server's existing behavior changed:

Run: `cd agents && python -m pytest tests/test_caller.py -v`
Expected: PASS, all existing tests still green

- [ ] **Step 4: Commit**

```bash
git add agents/agents/__main__.py
git commit -m "Launch caller's Twilio transport server alongside its A2A server"
```

---

## Part B — `app/backend`: the app-facing edge

### Task 10: `MasterClient` protocol gains `start_call` and `set_participation_mode`

**Files:**
- Modify: `app/backend/hawkeye_backend/master/base.py`
- Modify: `app/backend/hawkeye_backend/master/simulated.py` (the `SimulatedMasterClient` — exact filename to confirm by reading `main.py`'s import; Task 5's report showed `SimulatedMasterClient`/`LiveMasterClient` constructed in `main.py`, so grep `from .master import` there first)
- Modify: `app/backend/hawkeye_backend/master/live.py` (same confirm-by-grep note)
- Test: `app/backend/tests/test_master_client_call_bridge.py`

**Interfaces:**
- Produces: two new `MasterClient` protocol methods: `async def start_call(self, incident: Incident) -> None` (raises `AutonomousDialRefused` via `assert_human_released` if the incident wasn't user-raised — call the existing guard, don't reimplement it), `async def set_participation_mode(self, incident_id: str, mode: str, *, by_human: bool) -> str` (returns the announcement text, raises `ModeChangeRefused`-equivalent — since `app/backend` doesn't import `agents/`, define a local `class ParticipationModeRefused(RuntimeError)` in `master/base.py` that `LiveMasterClient` raises when the A2A call comes back refused, keeping `app/backend` and `agents/` as separately deployable processes that only ever talk over HTTP/A2A, never a shared Python import of each other's exception types).

- [ ] **Step 1: Read `app/backend/hawkeye_backend/master/base.py`, `simulated.py`, and `live.py` in full** to get the real current file names, the real full `MasterClient` Protocol definition, and how `LiveMasterClient` makes its existing calls to `master`'s A2A endpoint (this determines exactly how `start_call`/`set_participation_mode` should be implemented in `LiveMasterClient` — likely a new A2A method on `master`'s own router, analogous to how Task 7 in the original repo's `A2AObservationSource.fetch` pattern works, per the earlier research report's section 4).

- [ ] **Step 2: Write the failing test**

```python
from __future__ import annotations

import pytest
from hawkeye_backend.master.base import AutonomousDialRefused, MasterClient
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.models.incident import Incident, IncidentStatus, IncidentType, RaisedBy


def _incident(raised_by: RaisedBy) -> Incident:
    return Incident(
        incident_id="inc-001",
        site_id="site-demo-01",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=raised_by,
        address="1872 Ridgeview Lane, Blacksburg VA 24060",
    )


@pytest.mark.asyncio
async def test_start_call_refuses_a_system_raised_incident():
    """The structural gate: caller never dials without a human tap, even in
    simulated mode, so a bug can't quietly skip the one rule the whole
    project is built around."""
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    with pytest.raises(AutonomousDialRefused):
        await client.start_call(_incident(RaisedBy.SYSTEM))


@pytest.mark.asyncio
async def test_start_call_accepts_a_user_raised_incident():
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    await client.start_call(_incident(RaisedBy.USER))  # must not raise


@pytest.mark.asyncio
async def test_set_participation_mode_returns_an_announcement():
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    await client.start_call(_incident(RaisedBy.USER))
    announcement = await client.set_participation_mode("inc-001", "whisper", by_human=True)
    assert isinstance(announcement, str)
    assert len(announcement) > 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_master_client_call_bridge.py -v`
Expected: FAIL — `AttributeError: 'SimulatedMasterClient' object has no attribute 'start_call'`

- [ ] **Step 4: Implement in `SimulatedMasterClient`**

Add to the class (import `assert_human_released` from wherever `base.py`'s Step 1 read shows it actually lives):

```python
    async def start_call(self, incident: Incident) -> None:
        assert_human_released(incident)
        self._call_started_for = incident.incident_id  # exact attribute name/tracking approach
                                                          # to match this class's existing style —
                                                          # confirm by reading the rest of the class
                                                          # in Step 1 before finalizing this line.

    async def set_participation_mode(self, incident_id: str, mode: str, *, by_human: bool) -> str:
        return f"mode changed to {mode}"
```

For `LiveMasterClient`, implement both as new HTTP calls to `master`'s base URL (`self._base_url`), following whatever HTTP-call helper pattern the class already uses for `raise_incident` (read in Step 1) — POST a new endpoint (e.g. `/a2a/start-call`, `/a2a/set-mode`, matching whatever URL scheme the existing calls use) and translate a non-2xx "refused" response into `ParticipationModeRefused`/`AutonomousDialRefused` respectively.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_master_client_call_bridge.py -v`
Expected: PASS, 3 passed

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/master/ app/backend/tests/test_master_client_call_bridge.py
git commit -m "Add start_call and set_participation_mode to MasterClient"
```

---

### Task 11: `/v1/incident` triggers the call; new mode-change and token endpoints

**Files:**
- Modify: `app/backend/hawkeye_backend/api.py`
- Test: `app/backend/tests/test_api_call_bridge.py`

**Interfaces:**
- Consumes: `runtime.client.start_call`/`set_participation_mode` (Task 10).
- Produces: `POST /v1/incident/{incident_id}/mode` accepting `{"mode": "whisper" | "full_voice" | "watching", "by_human": true}`, returning `{"announcement": str}` or 409 with the refusal reason; `POST /v1/incident` (existing route) additionally calls `runtime.client.start_call(incident)` right after `raise_incident` succeeds, wrapped so a `start_call` failure doesn't roll back the already-raised incident (log and set `call_state`/surface via the existing event pipe instead — the incident stays raised even if the call couldn't be placed, matching `CallState.NOT_PLACED`'s existing purpose).

- [ ] **Step 1: Read the current `post_incident` handler and the surrounding router file in full** (already partially known from the earlier research report) to find the exact existing exception-handling shape for `MasterUnavailable`, so the new `start_call` call follows the same `try`/`except`/`HTTPException` idiom rather than inventing a different one.

- [ ] **Step 2: Write the failing test**

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.main import create_app
from hawkeye_backend.config import Settings, reset_settings


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
    mode_resp = client.post(f"/v1/incident/{incident_id}/mode", json={"mode": "whisper", "by_human": True})
    assert mode_resp.status_code == 200
    assert "announcement" in mode_resp.json()


def test_an_automated_mode_escalation_is_refused_with_409(client):
    resp = client.post("/v1/incident", json={"incident_type": "burglary"})
    incident_id = resp.json()["incident_id"]
    mode_resp = client.post(
        f"/v1/incident/{incident_id}/mode", json={"mode": "full_voice", "by_human": False}
    )
    assert mode_resp.status_code == 409
```

Implementer note: adjust `create_app`'s exact call signature to whatever `main.py`'s Step-1-equivalent read in earlier tasks shows (it may take no arguments and read settings via `get_settings()` internally rather than accepting a `Settings` instance — confirm before writing this test body for real, per the "no placeholders" rule; the shape above is the design intent, not a verified signature).

- [ ] **Step 3: Run test to verify it fails**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_api_call_bridge.py -v`
Expected: FAIL — 404 on the new route

- [ ] **Step 4: Implement**

```python
class SetParticipationModeRequest(BaseModel):
    mode: Literal["watching", "whisper", "full_voice"]
    by_human: bool = True


@router.post("/incident/{incident_id}/mode")
async def set_mode(incident_id: str, request: Request, body: SetParticipationModeRequest) -> dict:
    runtime = _runtime(request)
    try:
        announcement = await runtime.client.set_participation_mode(
            incident_id, body.mode, by_human=body.by_human
        )
    except ParticipationModeRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"announcement": announcement}
```

And in `post_incident`, immediately after the existing `incident = await runtime.client.raise_incident(...)` line:

```python
    try:
        await runtime.client.start_call(incident)
    except AutonomousDialRefused:
        logger.warning("start_call refused for %s: not user-raised", incident.incident_id)
    except Exception:
        logger.exception("start_call failed for %s", incident.incident_id)
```

(Import `ParticipationModeRefused`/`AutonomousDialRefused`/`Literal`/`BaseModel` at the top of the file, matching whatever's already imported.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app/backend && .venv/bin/python -m pytest tests/test_api_call_bridge.py -v`
Expected: PASS, 2 passed

- [ ] **Step 6: Run the full backend suite to check nothing regressed**

Run: `cd app/backend && .venv/bin/python -m pytest -q`
Expected: all passed, zero new failures

- [ ] **Step 7: Commit**

```bash
git add app/backend/hawkeye_backend/api.py app/backend/tests/test_api_call_bridge.py
git commit -m "Wire /v1/incident to start a call and add the mode-change endpoint"
```

---

## Part C — iOS

### Task 12: `HawkEyeClienting` gains call-bridge methods; `MockHawkEyeClient` implements them without network

**Files:**
- Modify: `app/ios/HawkEye/Services/HawkEyeClient.swift` (the protocol)
- Modify: `app/ios/HawkEye/Services/MockHawkEyeClient.swift` (find the real filename via `find app/ios/HawkEye -iname "*Mock*Client*"` if this guess is off)
- Modify: `app/ios/HawkEye/Services/LiveHawkEyeClient.swift` (same find-if-off note)
- Test: `app/ios/HawkEyeTests/MockHawkEyeClientCallBridgeTests.swift` (create; check `app/ios/HawkEyeTests/` for the existing test target name/pattern first)

**Interfaces:**
- Produces: new protocol requirements `var participationMode: ParticipationMode { get }`, `var callState: CallState { get }` (both Swift enums mirroring the Python `ParticipationMode`/`CallState` string values exactly — `watching`/`whisper`/`full_voice` and `not_started`/`dialing`/`connected`/`ended`/`not_placed`), `func setParticipationMode(_ mode: ParticipationMode) async throws`, `func takeOver() async throws`.

- [ ] **Step 1: Read `app/ios/HawkEye/Services/HawkEyeClient.swift` in full**, and locate the actual mock/live client filenames (the earlier research pass named them `MockHawkEyeClient.swift`/no confirmed live filename — verify both before editing). Also read `app/ios/HawkEye/Models/Incident.swift` to see if a Swift `CallState`/`ParticipationMode` enum already exists there (the design assumed not, based on the earlier survey's "zero hits for Whisper/TakeOver" finding, but confirm directly before adding a duplicate).

- [ ] **Step 2: Add the Swift enums** (in `app/ios/HawkEye/Models/Incident.swift`, alongside the existing `Incident` model, matching its `Codable`/`Sendable` conformance style):

```swift
enum ParticipationMode: String, Codable, Sendable {
    case watching, whisper
    case fullVoice = "full_voice"
}

enum CallState: String, Codable, Sendable {
    case notStarted = "not_started"
    case dialing, connected, ended
    case notPlaced = "not_placed"
}
```

- [ ] **Step 3: Add the protocol requirements to `HawkEyeClienting`**

```swift
    var participationMode: ParticipationMode { get }
    var callState: CallState { get }
    func setParticipationMode(_ mode: ParticipationMode) async throws
    func takeOver() async throws
```

- [ ] **Step 4: Write the failing test** (adjust the test target import/name to whatever Step 1 found):

```swift
import Testing
@testable import HawkEye

@MainActor
struct MockHawkEyeClientCallBridgeTests {
    @Test func startsWatchingByDefault() {
        let client = MockHawkEyeClient()
        #expect(client.participationMode == .watching)
    }

    @Test func takeOverMovesToFullVoice() async throws {
        let client = MockHawkEyeClient()
        try await client.takeOver()
        #expect(client.participationMode == .fullVoice)
    }

    @Test func settingWhisperUpdatesState() async throws {
        let client = MockHawkEyeClient()
        try await client.setParticipationMode(.whisper)
        #expect(client.participationMode == .whisper)
    }
}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd app/ios && xcodebuild test -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:HawkEyeTests/MockHawkEyeClientCallBridgeTests 2>&1 | tail -40`
Expected: FAIL — `MockHawkEyeClient` does not conform to `HawkEyeClienting` / missing members

- [ ] **Step 6: Implement in `MockHawkEyeClient`**, replacing whatever hardcoded call-transcript logic Step 1 found (`scriptTask` per the earlier survey) with a network-free scripted implementation of the *new* feature — the same script content the Python `SimulatedCallTransport` uses (Task 6's `_SCRIPT` tuple), transcribed once into a Swift constant so both sides tell the same story, plus real `CallState`/`ParticipationMode` transitions:

```swift
    private(set) var participationMode: ParticipationMode = .watching
    private(set) var callState: CallState = .notStarted

    private static let scriptedTranscript: [(speaker: TranscriptSpeaker, text: String)] = [
        (.operator, "911, what's your emergency?"),
        (.caller, "A person entered through the back door and does not match anyone on the household roster."),
        (.operator, "Can you describe them?"),
        (.caller, "Dark jacket, medium build, currently in the living room, captured 4 seconds ago."),
        (.operator, "Units are on the way, two minutes out."),
    ]

    func setParticipationMode(_ mode: ParticipationMode) async throws {
        participationMode = mode
    }

    func takeOver() async throws {
        participationMode = .fullVoice
    }
```

(Wire `scriptedTranscript` into whatever timer-driven `Task` mechanism Step 1 found driving the old hardcoded script — same delivery mechanism, new content and state transitions, per this plan's Global Constraints note on replacing rather than duplicating the old mock.)

Add matching (initially unimplemented-is-fine-if-`LiveHawkEyeClient`-doesn't-exist-yet-for-this-path, but must still compile) stub implementations to `LiveHawkEyeClient` calling the new `POST /v1/incident/{id}/mode` endpoint from Task 11 — full implementation of the live networking call is in scope for this task too, not deferred, since the protocol requires it to compile:

```swift
    func setParticipationMode(_ mode: ParticipationMode) async throws {
        guard let incidentId = incident?.incidentId else { throw HawkEyeClientError.notConnected }
        // POST to {baseURL}/v1/incident/{incidentId}/mode with {"mode": mode.rawValue, "by_human": true}
        // following whatever URLSession/request-building pattern this file already uses for
        // sendContext(_:) — read that method in Step 1 and match its exact style, don't invent a
        // second HTTP-calling convention in the same file.
    }

    func takeOver() async throws {
        try await setParticipationMode(.fullVoice)
    }
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd app/ios && xcodebuild test -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:HawkEyeTests/MockHawkEyeClientCallBridgeTests 2>&1 | tail -40`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/ios/HawkEye/Services/ app/ios/HawkEye/Models/Incident.swift app/ios/HawkEyeTests/
git commit -m "Add call-bridge state to HawkEyeClienting, replace the hardcoded mock script"
```

---

### Task 13: Take Over / mode controls in `IncidentView.swift`

**Files:**
- Modify: `app/ios/HawkEye/Features/Incident/IncidentView.swift`

**Interfaces:**
- Consumes: `model.client.participationMode`, `model.client.setParticipationMode(_:)`, `model.client.takeOver()` (Task 12).

- [ ] **Step 1: Read the full `IncidentView.swift`** to find the existing hold-to-confirm gesture implementation already used elsewhere in the app (the design spec and `app/CLAUDE.md` both require every risky control to use the same 1.5s hold — find that existing modifier/view rather than writing a second hold implementation) and the existing `endCallButton`'s layout code, to place the new controls consistently with it.

- [ ] **Step 2: Add the three labeled mode controls and Take Over**, using copy verbatim from `app/CLAUDE.md`'s "Label by consequence, not by our jargon" section:

```swift
private var modeControls: some View {
    VStack(alignment: .leading, spacing: 12) {
        Text(modeLabel(for: client.participationMode))
            .font(.headline)

        HoldToConfirmButton(title: "Speak — they'll hear you, your phone stays silent", holdDuration: 1.5) {
            Task { try? await client.setParticipationMode(.whisper) }
        }

        HoldToConfirmButton(title: "Turn on sound — your phone will be audible", holdDuration: 1.5) {
            Task { try? await client.setParticipationMode(.fullVoice) }
        }

        HoldToConfirmButton(title: "TAKE OVER", holdDuration: 1.5) {
            Task { try? await client.takeOver() }
        }
    }
}

private func modeLabel(for mode: ParticipationMode) -> String {
    switch mode {
    case .watching: return "Listening only"
    case .whisper: return "Speaking, not listening"
    case .fullVoice: return "Full voice"
    }
}
```

(`HoldToConfirmButton` name is a guess at what Step 1's existing hold-gesture component is called — use the real name found in Step 1 instead if different; do not create a second hold-gesture implementation under a different name.)

- [ ] **Step 3: Place `modeControls` into the existing view body**, near `endCallButton`, matching its existing padding/spacing conventions found in Step 1.

- [ ] **Step 4: Build the app to confirm it compiles**

Run: `cd app/ios && xcodegen generate && xcodebuild build -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' 2>&1 | tail -40`
Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 5: Commit**

```bash
git add app/ios/HawkEye/Features/Incident/IncidentView.swift
git commit -m "Add Take Over and participation-mode controls to IncidentView"
```

---

### Task 14: Twilio Voice SDK — join the conference as a live audio leg

**Files:**
- Modify: `app/ios/project.yml` (add the SPM dependency)
- Create: `app/ios/HawkEye/Services/CallAudioSession.swift`
- Modify: `app/ios/HawkEye/Services/LiveHawkEyeClient.swift`

**Interfaces:**
- Consumes: an Access Token fetched from `app/backend` (new endpoint — see Step 1).
- Produces: `CallAudioSession` wrapping `TwilioVoice.connect`, with `func join(accessToken: String) async throws`, `func leave()`, `func setMuted(_ muted: Bool)`.

- [ ] **Step 1: Add a token-vending endpoint to `app/backend`** first (this task depends on it existing): `GET /v1/incident/{incident_id}/call-token` returning `{"access_token": str}`. Since minting a real Twilio Access Token needs an API Key/Secret pair (not yet in scope of Task 1's config additions), add `HAWKEYE_TWILIO_API_KEY_SID`/`HAWKEYE_TWILIO_API_KEY_SECRET`/`HAWKEYE_TWILIO_APPLICATION_SID` to `Settings` the same way Task 1 did, write the failing/passing test pair for the endpoint following Task 11's exact pattern, and implement using the `twilio` Python SDK's `AccessToken`/`VoiceGrant` classes **only for this one call** — token-minting is the one place reimplementing Twilio's JWT construction by hand in raw `httpx` is not worth it, unlike the REST client in Task 5. Add `twilio` to `app/backend/pyproject.toml`'s dependencies to support this. Commit this sub-step on its own before continuing.

- [ ] **Step 2: Add the Twilio Voice iOS SDK as an SPM package** in `app/ios/project.yml`, under whatever `packages:`/`dependencies:` key the file already uses (read it first) — `https://github.com/twilio/twilio-voice-ios`, product `TwilioVoice`.

- [ ] **Step 3: Implement `CallAudioSession`**

```swift
import TwilioVoice

@MainActor
final class CallAudioSession: NSObject {
    private var activeCall: Call?

    func join(accessToken: String) async throws {
        let connectOptions = ConnectOptions(accessToken: accessToken) { builder in }
        activeCall = TwilioVoiceSDK.connect(options: connectOptions, delegate: self)
    }

    func leave() {
        activeCall?.disconnect()
        activeCall = nil
    }

    func setMuted(_ muted: Bool) {
        activeCall?.isMuted = muted
    }
}

extension CallAudioSession: CallDelegate {
    func callDidConnect(call: Call) {}
    func callDidDisconnect(call: Call, error: Error?) {
        activeCall = nil
    }
}
```

(Exact `CallDelegate` method names/signatures must be checked against the installed SDK version's actual protocol once Step 2's package resolves in Xcode — the SDK's delegate surface has changed across major versions; verify against the resolved package's headers/docs before treating the above as final, per this task depending on a live SPM resolution that hasn't happened yet in this plan.)

- [ ] **Step 4: Wire `CallAudioSession` into `LiveHawkEyeClient`**: fetch the token from Step 1's endpoint when `callState` becomes `.connected`, call `join(accessToken:)`, call `setMuted` whenever `setParticipationMode` changes `participationMode` (muted unless mode is `.whisper` or `.fullVoice`, matching `Bridge.leg_state(Leg.RESIDENT)`'s send flag from the Python side), and enforce whisper's "resident hears nothing" client-side by setting `AVAudioSession` output to muted/disabled rather than relying on Twilio's `coaching` flag alone — per the design spec's explicit note on this.

- [ ] **Step 5: Build the app to confirm it compiles with the new dependency**

Run: `cd app/ios && xcodegen generate && xcodebuild build -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' 2>&1 | tail -60`
Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 6: Commit**

```bash
git add app/ios/project.yml app/ios/HawkEye/Services/
git commit -m "Add Twilio Voice SDK and join the conference as a live audio leg"
```

---

## Part D — Documentation and manual real-call verification

### Task 15: ngrok setup doc

**Files:**
- Create: `docs/hardware/call-bridge-dev-setup.md`

- [ ] **Step 1: Write the doc**, covering: installing ngrok, running `ngrok http <backend port>` and a second tunnel (or one multiplexed tunnel, depending on ngrok plan) for the WSS ConversationRelay path, setting `HAWKEYE_PUBLIC_BASE_URL`, registering the TwiML App's Request URL (`{base}/twilio/agent-leg`) and the Twilio number's Voice webhook (`{base}/twilio/voice`) in the Twilio console, and the note that a free ngrok URL rotates on restart so this is a per-session step unless a static domain is purchased.

- [ ] **Step 2: Commit**

```bash
git add docs/hardware/call-bridge-dev-setup.md
git commit -m "Document the ngrok setup for real call-bridge testing"
```

---

### Task 16: Real end-to-end call — manual verification (run by the user, not automated)

This task has no code changes. It is the tier-3 test from the design spec, run once the above is implemented, to let the user actually place and receive a real call.

- [ ] **Step 1:** Set every `HAWKEYE_TWILIO_*`/`HAWKEYE_ELEVENLABS_*`/`HAWKEYE_MOCK_911_NUMBER`/`HAWKEYE_PUBLIC_BASE_URL` value in `app/backend/.env` and `agents/.env` (or wherever `agents/`'s settings load from — confirm in Task 9's Step 1 read) to real values: a real Twilio account SID/auth token/phone number, a real TwiML App SID pointed at the ngrok URL, a real ElevenLabs API key and voice ID, and the actual phone number to be dialed as "911" (a teammate's real phone, with their consent).
- [ ] **Step 2:** Start ngrok per Task 15's doc, start `app/backend` with `HAWKEYE_MODE=live`, start `caller`'s process from Task 9.
- [ ] **Step 3:** From the iOS app (real client, `Config.useMocks = false`), hold Start Incident.
- [ ] **Step 4:** Confirm the teammate's phone actually rings, answering it hears the ElevenLabs-voiced opening report, and speaking a question back gets a verified-claim answer or "I don't know" rather than a fabrication.
- [ ] **Step 5:** Report back whether it worked; if the ngrok URL, Twilio console webhook config, or any single `HAWKEYE_*` value was wrong, this is where it surfaces — the pure unit tests and simulated mode from Parts A-C cannot catch a live misconfiguration, only this step can.

If the user cannot complete this task right now (no ngrok session active, teammate unavailable, etc.), the fallback is tier 2: run the app in `Config.useMocks = true` (Task 12's replaced mock) and confirm the full UI — Take Over, mode controls, transcript — behaves identically to how it would on a real call, which is the strongest available substitute verification when a real call can't be placed.

---

## End-of-session review (run once, after every task above is implemented — not per task)

Per explicit user instruction: do not code-review or debug after each task. After Task 16 (or after Task 15 if Task 16 can't be run live), do one pass covering the whole feature:

1. Run the full test suite in both Python projects: `cd agents && python -m pytest -q` and `cd app/backend && .venv/bin/python -m pytest -q`. Zero failures, zero skips.
2. Build the full iOS app once: `cd app/ios && xcodegen generate && xcodebuild build -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17'`.
3. Run a code review pass over every file touched across all 16 tasks (use `git diff main...TRIcall` to enumerate them) — check for the things a per-task review would have caught individually: consistent error handling, no leftover placeholder code, no secrets logged, the `X-Twilio-Signature` check present on every webhook route, `HAWKEYE_MOCK_911_NUMBER` never accepted as a request parameter anywhere.
4. Attempt Task 16's real call if not already done; otherwise fall back to the tier-2 verification described there.
5. Fix anything found in steps 1-4 as follow-up commits on this branch, then report the results to the user.
