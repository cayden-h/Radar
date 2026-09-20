# Retell AI Call Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Retell AI as the real phone-call transport for `agents/caller`, over Retell's Custom LLM WebSocket, so the caller agent holds a two-way call with a human 911 operator (a teammate's phone) speaking only verified claims.

**Architecture:** Retell handles telephony + turn-taking and calls back over a WebSocket for each turn; a new `RetellCallOrchestrator` adapts Retell's wire protocol onto the existing, transport-agnostic `CallerAgent.opening_report` / `answer_operator` / `bridge`. Retell is configured (in the dashboard) with ElevenLabs as its TTS voice. It lives alongside the dormant Twilio transport behind a `call_transport` config selector.

**Tech Stack:** Python 3.13, FastAPI, `httpx` (raw, no vendor SDK), pytest, pydantic-settings.

## Global Constraints

- No third-party vendor SDK — raw `httpx` only, matching `transport/twilio_client.py`.
- Own-vs-injected `httpx.AsyncClient`: `aclose()` closes only a client this object created.
- Fail closed when unconfigured: no secret → refuse every request; never fall back to a constant.
- The operator destination number is bound from server settings, never read from request input.
- The caller speaks only via `CallerAgent.opening_report` / `answer_operator` — no new speech logic.
- `agents/master` must need zero changes: the internal trigger route stays `POST /internal/start-call`, bearer-gated.
- ElevenLabs stays the voice (configured on the Retell agent); the caller agent stays the brain.
- All new code under `agents/agents/caller/transport/retell/`. Tests under `agents/tests/`.
- Retell REST base: `https://api.retellai.com`; create call: `POST /v2/create-phone-call`, `Authorization: Bearer <key>`, returns 201 with `call_id`.
- Retell Custom LLM WS: Retell connects to `<registered_url>/{call_id}`; messages carry `interaction_type` ∈ `ping_pong | call_details | update_only | response_required | reminder_required`; we reply with `response_type` ∈ `config | response | ping_pong`.
- Run tests from `agents/`: `cd agents && python -m pytest -q`.

---

### Task 1: Retell WebSocket wire protocol (pure, no I/O)

**Files:**
- Create: `agents/agents/caller/transport/retell/__init__.py` (empty)
- Create: `agents/agents/caller/transport/retell/protocol.py`
- Test: `agents/tests/test_retell_protocol.py`

**Interfaces:**
- Produces:
  - `parse_retell_message(raw: dict) -> RetellPingPong | RetellCallDetails | RetellUpdateOnly | RetellResponseRequired` (raises `ValueError` on unknown `interaction_type`)
  - dataclasses (all frozen): `RetellPingPong(timestamp: int)`, `RetellCallDetails(call: dict)`, `RetellUpdateOnly(transcript: tuple[dict, ...])`, `RetellResponseRequired(response_id: int, transcript: tuple[dict, ...])` (used for both `response_required` and `reminder_required`)
  - `build_config_message() -> dict`
  - `build_response_message(response_id: int, content: str, *, content_complete: bool = True, end_call: bool = False) -> dict`
  - `build_pong_message(timestamp: int) -> dict`
  - `latest_user_utterance(transcript: tuple[dict, ...] | list[dict]) -> str | None` (last item whose `role == "user"`, returns its `content`, else `None`)

- [ ] **Step 1: Write the failing tests**

```python
# agents/tests/test_retell_protocol.py
"""Retell Custom LLM WebSocket wire shape. Pure parse/build, no I/O."""

from __future__ import annotations

import pytest

from agents.caller.transport.retell.protocol import (
    RetellCallDetails,
    RetellPingPong,
    RetellResponseRequired,
    RetellUpdateOnly,
    build_config_message,
    build_pong_message,
    build_response_message,
    latest_user_utterance,
    parse_retell_message,
)


def test_parses_ping_pong():
    msg = parse_retell_message({"interaction_type": "ping_pong", "timestamp": 1234})
    assert msg == RetellPingPong(timestamp=1234)


def test_parses_call_details():
    msg = parse_retell_message({"interaction_type": "call_details", "call": {"call_id": "c1"}})
    assert isinstance(msg, RetellCallDetails)
    assert msg.call == {"call_id": "c1"}


def test_parses_update_only():
    raw = {"interaction_type": "update_only", "transcript": [{"role": "user", "content": "hi"}]}
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellUpdateOnly)
    assert msg.transcript == ({"role": "user", "content": "hi"},)


def test_parses_response_required():
    raw = {
        "interaction_type": "response_required",
        "response_id": 3,
        "transcript": [{"role": "agent", "content": "hello"}, {"role": "user", "content": "help"}],
    }
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellResponseRequired)
    assert msg.response_id == 3
    assert msg.transcript[-1] == {"role": "user", "content": "help"}


def test_reminder_required_is_a_response_required():
    raw = {"interaction_type": "reminder_required", "response_id": 5, "transcript": []}
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellResponseRequired)
    assert msg.response_id == 5


def test_unknown_interaction_type_raises():
    with pytest.raises(ValueError):
        parse_retell_message({"interaction_type": "nonsense"})


def test_build_config_message_shape():
    cfg = build_config_message()
    assert cfg["response_type"] == "config"
    assert "config" in cfg


def test_build_response_message_defaults_complete():
    msg = build_response_message(7, "units are two minutes out")
    assert msg == {
        "response_type": "response",
        "response_id": 7,
        "content": "units are two minutes out",
        "content_complete": True,
        "end_call": False,
    }


def test_build_pong_echoes_timestamp():
    assert build_pong_message(99) == {"response_type": "ping_pong", "timestamp": 99}


def test_latest_user_utterance_picks_last_user_line():
    transcript = [
        {"role": "user", "content": "first"},
        {"role": "agent", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    assert latest_user_utterance(transcript) == "second"


def test_latest_user_utterance_none_when_no_user():
    assert latest_user_utterance([{"role": "agent", "content": "only me"}]) is None
    assert latest_user_utterance([]) is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd agents && python -m pytest tests/test_retell_protocol.py -q`
Expected: FAIL (module `agents.caller.transport.retell.protocol` not found).

- [ ] **Step 3: Create the package init and implement the protocol**

```python
# agents/agents/caller/transport/retell/__init__.py
```

(empty file)

```python
# agents/agents/caller/transport/retell/protocol.py
"""agents/agents/caller/transport/retell/protocol.py

Wire-shape for Retell's Custom LLM WebSocket protocol. Field names verified
against Retell's llm-websocket docs at implementation time. Pure parse/build,
no I/O, so it is unit-testable without a socket - the same split as the Twilio
transport's models.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetellPingPong:
    timestamp: int


@dataclass(frozen=True)
class RetellCallDetails:
    call: dict


@dataclass(frozen=True)
class RetellUpdateOnly:
    transcript: tuple[dict, ...]


@dataclass(frozen=True)
class RetellResponseRequired:
    """Retell is asking the agent to speak. Covers both `response_required` and
    `reminder_required` - a reminder is the same request after a silence, and
    the agent answers it the same way."""

    response_id: int
    transcript: tuple[dict, ...]


RetellInbound = RetellPingPong | RetellCallDetails | RetellUpdateOnly | RetellResponseRequired


def parse_retell_message(raw: dict) -> RetellInbound:
    kind = raw.get("interaction_type")
    if kind == "ping_pong":
        return RetellPingPong(timestamp=int(raw["timestamp"]))
    if kind == "call_details":
        return RetellCallDetails(call=raw.get("call", {}))
    if kind == "update_only":
        return RetellUpdateOnly(transcript=tuple(raw.get("transcript", [])))
    if kind in ("response_required", "reminder_required"):
        return RetellResponseRequired(
            response_id=int(raw["response_id"]),
            transcript=tuple(raw.get("transcript", [])),
        )
    raise ValueError(f"unknown Retell interaction_type: {kind!r}")


def build_config_message() -> dict:
    """Sent once, when the socket opens. Ask Retell to send call_details so we
    can bind the transcript, and to auto-reconnect with ping_pong keepalives."""
    return {
        "response_type": "config",
        "config": {"auto_reconnect": True, "call_details": True},
    }


def build_response_message(
    response_id: int, content: str, *, content_complete: bool = True, end_call: bool = False
) -> dict:
    return {
        "response_type": "response",
        "response_id": response_id,
        "content": content,
        "content_complete": content_complete,
        "end_call": end_call,
    }


def build_pong_message(timestamp: int) -> dict:
    return {"response_type": "ping_pong", "timestamp": timestamp}


def latest_user_utterance(transcript: tuple[dict, ...] | list[dict]) -> str | None:
    """The operator's most recent line, or None if they have not spoken yet.

    Retell's transcript uses role `user` for the far end (the operator) and
    `agent` for us. The opening report is what we say when this is None.
    """
    for item in reversed(list(transcript)):
        if item.get("role") == "user":
            return item.get("content")
    return None
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd agents && python -m pytest tests/test_retell_protocol.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/retell/__init__.py agents/agents/caller/transport/retell/protocol.py agents/tests/test_retell_protocol.py
git commit -m "Add Retell Custom LLM WebSocket wire protocol"
```

---

### Task 2: Retell REST client (real + simulated)

**Files:**
- Create: `agents/agents/caller/transport/retell/client.py`
- Test: `agents/tests/test_retell_client.py`

**Interfaces:**
- Produces:
  - `RetellVoiceClient` (Protocol): `async create_phone_call(*, from_number: str, to_number: str, metadata: dict) -> str` (returns `call_id`)
  - `RealRetellVoiceClient(*, api_key: str, agent_id: str = "", client: httpx.AsyncClient | None = None)` with `create_phone_call(...)` and `async aclose()`
  - `SimulatedRetellVoiceClient()` with `create_phone_call(...)` returning `"SIM-RETELL-0001"` (incrementing) and a `calls: list[dict]` attribute recording every call's kwargs

- [ ] **Step 1: Write the failing tests**

```python
# agents/tests/test_retell_client.py
"""Retell REST client: real httpx shape and the simulated stand-in."""

from __future__ import annotations

import httpx
import pytest

from agents.caller.transport.retell.client import (
    RealRetellVoiceClient,
    SimulatedRetellVoiceClient,
)


@pytest.mark.asyncio
async def test_real_client_posts_create_phone_call_and_returns_call_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"call_id": "call_abc123"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="key_test", agent_id="agent_9", client=http)
        call_id = await client.create_phone_call(
            from_number="+15550001111", to_number="+15550002222", metadata={"incident_id": "i1"}
        )

    assert call_id == "call_abc123"
    assert seen["url"] == "https://api.retellai.com/v2/create-phone-call"
    assert seen["auth"] == "Bearer key_test"
    assert seen["body"]["from_number"] == "+15550001111"
    assert seen["body"]["to_number"] == "+15550002222"
    assert seen["body"]["metadata"] == {"incident_id": "i1"}
    assert seen["body"]["override_agent_id"] == "agent_9"


@pytest.mark.asyncio
async def test_real_client_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="payment required")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="k", client=http)
        with pytest.raises(RuntimeError):
            await client.create_phone_call(from_number="+1", to_number="+2", metadata={})


@pytest.mark.asyncio
async def test_real_client_omits_agent_id_when_blank():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"call_id": "c"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="k", client=http)
        await client.create_phone_call(from_number="+1", to_number="+2", metadata={})

    assert "override_agent_id" not in seen["body"]


@pytest.mark.asyncio
async def test_simulated_client_returns_incrementing_ids_and_records():
    client = SimulatedRetellVoiceClient()
    first = await client.create_phone_call(from_number="+1", to_number="+2", metadata={"incident_id": "i"})
    second = await client.create_phone_call(from_number="+1", to_number="+3", metadata={})
    assert first == "SIM-RETELL-0001"
    assert second == "SIM-RETELL-0002"
    assert client.calls[0]["to_number"] == "+2"
    assert client.calls[1]["to_number"] == "+3"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd agents && python -m pytest tests/test_retell_client.py -q`
Expected: FAIL (module not found). (If `pytest-asyncio` is missing, install it — check `agents/pyproject.toml` for the existing async test config first; other transport tests already use async.)

- [ ] **Step 3: Implement the client**

```python
# agents/agents/caller/transport/retell/client.py
"""agents/agents/caller/transport/retell/client.py

Raw httpx calls to Retell's REST API, matching transport/twilio_client.py's
style: no `retell` SDK, Bearer auth, own-vs-injected client tracked so aclose()
only closes what this object created.

Retell is free for calling, which is why it replaced the paywalled Twilio Voice
transport as the real path. See docs/superpowers/specs/2026-09-20-retell-call-transport-design.md.
"""

from __future__ import annotations

from typing import Protocol

import httpx

RETELL_API = "https://api.retellai.com"


class RetellVoiceClient(Protocol):
    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str: ...


class RealRetellVoiceClient:
    def __init__(
        self, *, api_key: str, agent_id: str = "", client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._client = client or httpx.AsyncClient(timeout=10.0)
        # Only close what we created; an injected client is owned elsewhere.
        self._owns_client = client is None

    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str:
        body: dict = {
            "from_number": from_number,
            "to_number": to_number,
            "metadata": metadata,
        }
        # Bind the agent explicitly when configured. Retell otherwise uses the
        # agent bound to from_number. The destination number is a server-side
        # setting, never request input - the swatting-address rule.
        if self._agent_id:
            body["override_agent_id"] = self._agent_id
        resp = await self._client.post(
            f"{RETELL_API}/v2/create-phone-call",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Retell refused create-phone-call: {resp.status_code} {resp.text}"
            )
        return resp.json()["call_id"]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SimulatedRetellVoiceClient:
    """No network, no Retell account. Drives the identical orchestrator path so
    the demo's fallback and everyday development exercise real CallerAgent logic.
    """

    def __init__(self) -> None:
        self._counter = 0
        self.calls: list[dict] = []

    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str:
        self._counter += 1
        self.calls.append(
            {"from_number": from_number, "to_number": to_number, "metadata": metadata}
        )
        return f"SIM-RETELL-{self._counter:04d}"

    async def aclose(self) -> None:
        return None
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd agents && python -m pytest tests/test_retell_client.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/retell/client.py agents/tests/test_retell_client.py
git commit -m "Add Retell REST client (real httpx + simulated)"
```

---

### Task 3: Retell call orchestrator

**Files:**
- Create: `agents/agents/caller/transport/retell/orchestrator.py`
- Test: `agents/tests/test_retell_orchestrator.py`

**Interfaces:**
- Consumes: `parse_retell_message`, `build_config_message`, `build_response_message`, `build_pong_message`, `latest_user_utterance` (Task 1); `RetellVoiceClient` (Task 2); `CallerAgent` (existing).
- Produces:
  - `RetellCallOrchestrator(caller: CallerAgent, transport: RetellVoiceClient, *, from_number: str, operator_number: str)`
  - fields (init=False): `call_id: str | None`, `incident_id: str | None`, `transcript: list[tuple[str, str]]`
  - `async start_call(incident_id: str, incident_type: IncidentType, address_spoken: str) -> str` (returns `call_id`)
  - `config_message() -> dict` (what the WS route sends on open)
  - `async handle_ws_message(raw: dict) -> dict | None`
  - `transcript_so_far() -> list[tuple[str, str]]`

**Behaviour of `handle_ws_message`:**
- `RetellPingPong` → `build_pong_message(timestamp)`
- `RetellCallDetails` → `None` (no speech)
- `RetellUpdateOnly` → `None` (transcript already flows via response_required; no speech)
- `RetellResponseRequired`:
  - `op = latest_user_utterance(transcript)`
  - if `op is None`: join every `opening_report(...)` utterance's text with a space, record each as `("caller", text)`, return `build_response_message(response_id, joined)`
  - else: record `("operator", op)`, call `answer_operator(op)`, record `("caller", reply.text)`, return `build_response_message(response_id, reply.text)`

- [ ] **Step 1: Write the failing tests**

```python
# agents/tests/test_retell_orchestrator.py
"""RetellCallOrchestrator: adapts Retell's WS onto CallerAgent, no new speech."""

from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent
from agents.caller.transport.retell.client import SimulatedRetellVoiceClient
from agents.caller.transport.retell.orchestrator import RetellCallOrchestrator
from agents.master import MasterAgent


def _orchestrator(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    transport = SimulatedRetellVoiceClient()
    orch = RetellCallOrchestrator(
        caller, transport, from_number="+15550001111", operator_number="+15550009999"
    )
    return orch, transport


@pytest.mark.asyncio
async def test_start_call_dials_the_operator_number_from_settings(mesh):
    orch, transport = _orchestrator(mesh)
    call_id = await orch.start_call("incident-7", IncidentType.BURGLARY, "12 Elm Street")
    assert call_id.startswith("SIM-RETELL-")
    assert transport.calls[0]["to_number"] == "+15550009999"
    assert transport.calls[0]["from_number"] == "+15550001111"
    assert transport.calls[0]["metadata"]["incident_id"] == "incident-7"
    assert orch.call_id == call_id


@pytest.mark.asyncio
async def test_ping_pong_is_echoed(mesh):
    orch, _ = _orchestrator(mesh)
    reply = await orch.handle_ws_message({"interaction_type": "ping_pong", "timestamp": 42})
    assert reply == {"response_type": "ping_pong", "timestamp": 42}


@pytest.mark.asyncio
async def test_update_only_and_call_details_do_not_speak(mesh):
    orch, _ = _orchestrator(mesh)
    assert await orch.handle_ws_message({"interaction_type": "call_details", "call": {}}) is None
    assert await orch.handle_ws_message(
        {"interaction_type": "update_only", "transcript": [{"role": "user", "content": "hi"}]}
    ) is None


@pytest.mark.asyncio
async def test_first_response_required_delivers_opening_report(mesh):
    orch, _ = _orchestrator(mesh)
    await orch.start_call("i1", IncidentType.BURGLARY, "12 Elm Street")
    reply = await orch.handle_ws_message(
        {"interaction_type": "response_required", "response_id": 0, "transcript": []}
    )
    assert reply["response_type"] == "response"
    assert reply["response_id"] == 0
    assert reply["content_complete"] is True
    # The opening report identifies itself as not a person.
    assert "not a person" in reply["content"]


@pytest.mark.asyncio
async def test_later_response_required_answers_the_operator(mesh):
    orch, _ = _orchestrator(mesh)
    await orch.start_call("i1", IncidentType.BURGLARY, "12 Elm Street")
    reply = await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 2,
            "transcript": [
                {"role": "agent", "content": "opening"},
                {"role": "user", "content": "what colour is the front door?"},
            ],
        }
    )
    assert reply["response_id"] == 2
    # An unrecognised question is "I don't know", never a guess to 911.
    assert reply["content"].startswith("I don't know")
    assert ("operator", "what colour is the front door?") in orch.transcript_so_far()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd agents && python -m pytest tests/test_retell_orchestrator.py -q`
Expected: FAIL (module `...retell.orchestrator` not found).

- [ ] **Step 3: Implement the orchestrator**

```python
# agents/agents/caller/transport/retell/orchestrator.py
"""agents/agents/caller/transport/retell/orchestrator.py

The seam between CallerAgent's transport-agnostic decision logic and whichever
RetellVoiceClient is behind it (real or simulated). Nothing here composes
speech: it only routes Retell's WebSocket messages onto opening_report and
answer_operator, which already enforce the verified-claims rule.

Retell places a 1:1 call to the operator, not a Twilio-style conference, so
there is no resident leg to mute here. The resident whisper/silent path remains
the Twilio conference's; see the design doc's divergence note.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hawkeye_backend.models.incident import IncidentType

from ...agent import CallerAgent
from .client import RetellVoiceClient
from .protocol import (
    RetellCallDetails,
    RetellPingPong,
    RetellResponseRequired,
    RetellUpdateOnly,
    build_config_message,
    build_pong_message,
    build_response_message,
    latest_user_utterance,
    parse_retell_message,
)


@dataclass
class RetellCallOrchestrator:
    caller: CallerAgent
    transport: RetellVoiceClient
    from_number: str
    operator_number: str
    call_id: str | None = field(default=None, init=False)
    incident_id: str | None = field(default=None, init=False)
    transcript: list[tuple[str, str]] = field(default_factory=list, init=False)

    async def start_call(
        self, incident_id: str, incident_type: IncidentType, address_spoken: str
    ) -> str:
        self.incident_id = incident_id
        # The destination is the operator number from settings, never request
        # input. The opening report is delivered on the first response_required,
        # not here, because Retell drives turn-taking once the WS opens.
        self.call_id = await self.transport.create_phone_call(
            from_number=self.from_number,
            to_number=self.operator_number,
            metadata={"incident_id": incident_id, "incident_type": incident_type.value},
        )
        self._incident_type = incident_type
        self._address_spoken = address_spoken
        return self.call_id

    def config_message(self) -> dict:
        return build_config_message()

    async def handle_ws_message(self, raw: dict) -> dict | None:
        message = parse_retell_message(raw)
        if isinstance(message, RetellPingPong):
            return build_pong_message(message.timestamp)
        if isinstance(message, (RetellCallDetails, RetellUpdateOnly)):
            return None
        if isinstance(message, RetellResponseRequired):
            operator_line = latest_user_utterance(message.transcript)
            if operator_line is None:
                text = self._opening_text()
                self.transcript.append(("caller", text))
                return build_response_message(message.response_id, text)
            self.transcript.append(("operator", operator_line))
            reply = self.caller.answer_operator(operator_line)
            self.transcript.append(("caller", reply.text))
            return build_response_message(message.response_id, reply.text)
        return None

    def _opening_text(self) -> str:
        utterances = self.caller.opening_report(self._incident_type, self._address_spoken)
        return " ".join(u.text for u in utterances)

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd agents && python -m pytest tests/test_retell_orchestrator.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/retell/orchestrator.py agents/tests/test_retell_orchestrator.py
git commit -m "Add Retell call orchestrator adapting the WS onto CallerAgent"
```

---

### Task 4: Retell transport FastAPI app (WS + internal trigger)

**Files:**
- Create: `agents/agents/caller/transport/retell/server.py`
- Test: `agents/tests/test_retell_server.py`

**Interfaces:**
- Consumes: `RetellCallOrchestrator` (Task 3).
- Produces: `build_retell_transport_app(orchestrator, *, websocket_secret: str | None, internal_trigger_token: str | None) -> FastAPI` with routes:
  - `POST /internal/start-call` (bearer-gated; body `{incident_id, incident_type, address}`; returns `{"call_id": ...}`)
  - `WS /retell/llm-websocket/{secret}/{call_id}` (fails closed when unconfigured; rejects wrong secret; rejects a `call_id` the orchestrator did not initiate; on accept sends config then loops)

- [ ] **Step 1: Write the failing tests**

```python
# agents/tests/test_retell_server.py
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd agents && python -m pytest tests/test_retell_server.py -q`
Expected: FAIL (module `...retell.server` not found).

- [ ] **Step 3: Implement the server**

```python
# agents/agents/caller/transport/retell/server.py
"""agents/agents/caller/transport/retell/server.py

The public HTTP/WS surface of the Retell transport. Two auth boundaries, both
fail-closed when unconfigured, mirroring the Twilio transport server:

- `/internal/start-call` is the trigger agents/master POSTs to after its own
  `/a2a/start-call` guards pass. Bearer-gated by HAWKEYE_INTERNAL_TRIGGER_TOKEN,
  shared out of band. An unauthenticated route that can dial a phone is a
  swatting vector as direct as an unsigned Twilio webhook.

- `/retell/llm-websocket/{secret}/{call_id}` is the Custom LLM WebSocket Retell
  connects to. Retell does not sign the WS handshake, so it is gated two ways:
  a static secret path segment (registered as part of the URL Retell connects
  to) and a check that the call_id is one this process actually initiated. An
  unconfigured deployment (no secret) refuses every connection rather than
  exposing an open LLM/dial endpoint on the public internet.
"""

from __future__ import annotations

import hmac

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from hawkeye_backend.models.incident import IncidentType

from .orchestrator import RetellCallOrchestrator


class _InternalStartCallBody(BaseModel):
    incident_id: str
    incident_type: str
    address: str


def build_retell_transport_app(
    orchestrator: RetellCallOrchestrator,
    *,
    websocket_secret: str | None,
    internal_trigger_token: str | None,
) -> FastAPI:
    app = FastAPI()
    internal_configured = internal_trigger_token is not None
    ws_configured = websocket_secret is not None

    def _verify_internal_token(request: Request) -> None:
        if not internal_configured:
            raise HTTPException(
                status_code=503, detail="the internal trigger route is not configured on this deployment"
            )
        header = request.headers.get("Authorization", "")
        expected = f"Bearer {internal_trigger_token}"
        if not hmac.compare_digest(header, expected):
            raise HTTPException(status_code=403, detail="invalid internal trigger token")

    @app.post("/internal/start-call")
    async def internal_start_call(request: Request, body: _InternalStartCallBody) -> dict[str, str]:
        _verify_internal_token(request)
        incident_type = IncidentType(body.incident_type)
        call_id = await orchestrator.start_call(body.incident_id, incident_type, body.address)
        return {"call_id": call_id}

    @app.websocket("/retell/llm-websocket/{secret}/{call_id}")
    async def llm_websocket(websocket: WebSocket, secret: str, call_id: str) -> None:
        # Fail closed, wrong secret, or unknown call_id: refuse before accept so
        # nothing is ever handed to the orchestrator over an ungated socket.
        if (
            not ws_configured
            or not hmac.compare_digest(secret, websocket_secret)
            or orchestrator.call_id is None
            or not hmac.compare_digest(call_id, orchestrator.call_id)
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json(orchestrator.config_message())
        try:
            while True:
                raw = await websocket.receive_json()
                reply = await orchestrator.handle_ws_message(raw)
                if reply is not None:
                    await websocket.send_json(reply)
        except WebSocketDisconnect:
            return

    return app
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd agents && python -m pytest tests/test_retell_server.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agents/caller/transport/retell/server.py agents/tests/test_retell_server.py
git commit -m "Add Retell transport server (Custom LLM WS + internal trigger)"
```

---

### Task 5: Config + package exports + .env.example

**Files:**
- Modify: `app/backend/hawkeye_backend/config.py` (add Retell settings + property + selector)
- Modify: `agents/agents/caller/transport/retell/__init__.py` (export the public names)
- Modify: `app/backend/.env.example` (add Retell vars; keep ElevenLabs vars)
- Test: `agents/tests/test_retell_config.py`

**Interfaces:**
- Produces on `Settings`: `retell_api_key: SecretStr`, `retell_from_number: str`, `retell_agent_id: str`, `retell_websocket_secret: str`, `call_transport: str = "retell"`, property `retell_configured: bool`.
- Produces on the package: `from agents.caller.transport.retell import RetellCallOrchestrator, RealRetellVoiceClient, SimulatedRetellVoiceClient, build_retell_transport_app`.

- [ ] **Step 1: Write the failing test**

```python
# agents/tests/test_retell_config.py
"""Retell settings: all-or-unconfigured, and the transport default."""

from __future__ import annotations

from hawkeye_backend.config import Settings


def test_retell_unconfigured_by_default():
    s = Settings(_env_file=None)
    assert s.retell_configured is False
    assert s.call_transport == "retell"


def test_retell_configured_when_all_present():
    s = Settings(
        _env_file=None,
        retell_api_key="key",
        retell_from_number="+15550001111",
        retell_websocket_secret="s3cr3t",
    )
    assert s.retell_configured is True


def test_retell_not_configured_when_secret_missing():
    s = Settings(_env_file=None, retell_api_key="key", retell_from_number="+15550001111")
    assert s.retell_configured is False
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd agents && python -m pytest tests/test_retell_config.py -q`
Expected: FAIL (`retell_configured` / fields do not exist).

- [ ] **Step 3: Add the settings**

In `app/backend/hawkeye_backend/config.py`, inside `class Settings`, after the existing Twilio-voice block (near the `mock_911_number` / `elevenlabs_*` lines), add:

```python
    # Retell AI, the real call transport (Twilio Voice is paywalled and now
    # dormant). All three of api key, from number, and websocket secret are
    # required for a real call; missing any one reads as unconfigured, the same
    # all-or-nothing rule as the Twilio blocks above. The operator's phone is
    # `mock_911_number`, reused - it is exactly the fake 911 operator's phone.
    # ElevenLabs stays: it is configured on the Retell agent as the TTS voice,
    # so `elevenlabs_voice_id` above is still consumed.
    retell_api_key: SecretStr = SecretStr("")
    retell_from_number: str = ""
    retell_agent_id: str = ""
    retell_websocket_secret: str = ""
    # Which call transport the caller agent wires at startup: retell | twilio |
    # simulated. Default retell; twilio is retained but dormant.
    call_transport: str = "retell"
```

Then add the property alongside the other `*_configured` properties:

```python
    @property
    def retell_configured(self) -> bool:
        return all(
            [
                self.retell_api_key.get_secret_value(),
                self.retell_from_number,
                self.retell_websocket_secret,
            ]
        )
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd agents && python -m pytest tests/test_retell_config.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Export the package names**

Replace the contents of `agents/agents/caller/transport/retell/__init__.py` with:

```python
"""agents/caller Retell transport - the real call path. Retell handles
telephony and turn-taking, ElevenLabs is its TTS voice, CallerAgent is the brain.
"""

from .client import RealRetellVoiceClient, RetellVoiceClient, SimulatedRetellVoiceClient
from .orchestrator import RetellCallOrchestrator
from .server import build_retell_transport_app

__all__ = [
    "RealRetellVoiceClient",
    "RetellCallOrchestrator",
    "RetellVoiceClient",
    "SimulatedRetellVoiceClient",
    "build_retell_transport_app",
]
```

- [ ] **Step 6: Update `.env.example`**

In `app/backend/.env.example`, add under the Twilio/ElevenLabs section (mark Twilio dormant, keep ElevenLabs):

```bash
# --- Retell AI (the real call transport; Twilio Voice is paywalled/dormant) ---
# Free calling. Create an agent set to Custom LLM pointing at
#   wss://<public-host>/retell/llm-websocket/<HAWKEYE_RETELL_WEBSOCKET_SECRET>
# with TTS provider = ElevenLabs and voice = HAWKEYE_ELEVENLABS_VOICE_ID above.
HAWKEYE_CALL_TRANSPORT=retell            # retell | twilio | simulated
HAWKEYE_RETELL_API_KEY=
HAWKEYE_RETELL_FROM_NUMBER=              # your Retell-owned E.164 number
HAWKEYE_RETELL_AGENT_ID=                 # the Custom-LLM agent id
HAWKEYE_RETELL_WEBSOCKET_SECRET=         # static secret in the WS URL path
# The operator's phone (teammate acting as 911) reuses HAWKEYE_MOCK_911_NUMBER.
```

(If `app/backend/.env.example` does not exist, check for `app/backend/.env 2.example` and create `.env.example` from the same block; do not touch the ` 2.example` stray.)

- [ ] **Step 7: Run the config + package import check**

Run: `cd agents && python -m pytest tests/test_retell_config.py -q && python -c "import agents.caller.transport.retell as r; print(sorted(r.__all__))"`
Expected: tests PASS; prints the five exported names.

- [ ] **Step 8: Commit**

```bash
git add app/backend/hawkeye_backend/config.py agents/agents/caller/transport/retell/__init__.py app/backend/.env.example agents/tests/test_retell_config.py
git commit -m "Add Retell settings, package exports, and .env.example entries"
```

---

### Task 6: Wire the caller startup to select the Retell transport

**Files:**
- Modify: `agents/agents/__main__.py` (the `if args.slug == "caller":` block, ~lines 191-235)

**Interfaces:**
- Consumes: `Settings.call_transport`, `Settings.retell_configured`, `Settings.mock_911_number`, `Settings.retell_*`, `os.environ["HAWKEYE_INTERNAL_TRIGGER_TOKEN"]`; `RetellCallOrchestrator`, `RealRetellVoiceClient`, `SimulatedRetellVoiceClient`, `build_retell_transport_app` (Tasks 2-5).
- Produces: at startup, when `call_transport == "retell"`, the process serves `build_retell_transport_app` instead of the Twilio app. `twilio` keeps the existing wiring; anything else falls back to a simulated Retell transport.

- [ ] **Step 1: Read the current block**

Run: `sed -n '191,240p' agents/agents/__main__.py`
Confirm the Twilio wiring shape (variables `settings`, `transport_app`, and how `transport_app` is subsequently served — note the lines after 235 that run uvicorn on it).

- [ ] **Step 2: Replace the transport selection**

Replace the body of the `if args.slug == "caller":` block (from the imports through the `transport_app = build_transport_app(...)` assignment) with a `call_transport` switch. Keep everything after `transport_app` (the uvicorn serving of `transport_app`) unchanged. New block:

```python
    if args.slug == "caller":
        import os

        from hawkeye_backend.config import get_settings

        settings = get_settings()
        transport = (settings.call_transport or "retell").strip().lower()
        internal_token = os.environ.get("HAWKEYE_INTERNAL_TRIGGER_TOKEN", "").strip() or None

        if transport == "twilio":
            # Dormant path, retained. Paywalled; not the default.
            from agents.caller.transport.orchestrator import CallOrchestrator
            from agents.caller.transport.server import build_transport_app
            from agents.caller.transport.simulated import SimulatedCallTransport
            from agents.caller.transport.twilio_client import RealTwilioVoiceClient

            if settings.mode == "live" and settings.twilio_voice_configured:
                voice_client = RealTwilioVoiceClient(
                    account_sid=settings.twilio_account_sid,
                    auth_token=settings.twilio_auth_token.get_secret_value(),
                )
            else:
                voice_client = SimulatedCallTransport()
            orchestrator = CallOrchestrator(
                caller=agent,
                transport=voice_client,
                mock_911_number=settings.mock_911_number or "+15550004444",
                twilio_voice_number=settings.twilio_voice_number or "+15550003333",
                twiml_app_sid=settings.twilio_conference_app_sid or "APxxxx",
                status_callback_url=(settings.public_base_url or f"http://{args.host}:{args.transport_port}") + "/twilio/status",
            )
            transport_app = build_transport_app(
                orchestrator,
                auth_token=settings.twilio_auth_token.get_secret_value() if settings.twilio_voice_configured else None,
                elevenlabs_voice_id=settings.elevenlabs_voice_id or "voice123",
                public_base_url=settings.public_base_url or f"http://{args.host}:{args.transport_port}",
                internal_trigger_token=internal_token,
            )
        else:
            # Default: Retell (free). Real client only when live + configured;
            # otherwise a simulated client that drives the identical path.
            from agents.caller.transport.retell import (
                RealRetellVoiceClient,
                RetellCallOrchestrator,
                SimulatedRetellVoiceClient,
                build_retell_transport_app,
            )

            if settings.mode == "live" and settings.retell_configured:
                retell_client = RealRetellVoiceClient(
                    api_key=settings.retell_api_key.get_secret_value(),
                    agent_id=settings.retell_agent_id,
                )
            else:
                retell_client = SimulatedRetellVoiceClient()
            orchestrator = RetellCallOrchestrator(
                agent,
                retell_client,
                from_number=settings.retell_from_number or "+15550003333",
                operator_number=settings.mock_911_number or "+15550004444",
            )
            transport_app = build_retell_transport_app(
                orchestrator,
                websocket_secret=(settings.retell_websocket_secret or None) if (settings.mode == "live" and settings.retell_configured) else None,
                internal_trigger_token=internal_token,
            )
```

- [ ] **Step 3: Byte-compile check**

Run: `cd agents && python -c "import ast; ast.parse(open('agents/__main__.py').read()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Import-smoke the wiring**

Run: `cd agents && python -c "from agents.caller.transport.retell import build_retell_transport_app, RetellCallOrchestrator; print('wired')"`
Expected: prints `wired`.

- [ ] **Step 5: Commit**

```bash
git add agents/agents/__main__.py
git commit -m "Select the Retell transport at caller startup, Twilio dormant"
```

---

## Final verification (run once, after all tasks)

- [ ] Full agents suite: `cd agents && python -m pytest -q` — expect all green, no regressions in `test_caller.py`.
- [ ] Config import from backend context resolves (the config lives in `app/backend`; the agents tests already import `hawkeye_backend`, so a green `test_retell_config.py` confirms it).
- [ ] Grep for accidental Twilio hard-dependency in the new files: `grep -rn "twilio" agents/agents/caller/transport/retell/` — expect no matches.

## Self-review notes

- Spec coverage: protocol (T1), REST client real+sim (T2), orchestrator reuse of opening_report/answer_operator (T3), WS+trigger fail-closed gating (T4), config+exports+env+ElevenLabs-retained (T5), startup selector with Twilio dormant (T6), divergence note carried in orchestrator docstring. All spec sections mapped.
- Verify config lands: `test_retell_config.py` imports `hawkeye_backend.config`, so a green run confirms the new fields resolve from the agents test context.
