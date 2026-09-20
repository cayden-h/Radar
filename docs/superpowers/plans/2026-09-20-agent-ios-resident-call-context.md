# agent-ios: Resident joins the call through the agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Per the user, ALL review and verification is deferred to the very end — do not run the test suite between tasks; write the tests, commit, and move on. A single review+verify pass runs after Task 6.**

**Goal:** Let the resident (app on a 2nd phone) watch the live operator↔agent transcript and inject voice/text the agent speaks, while the Retell agent keeps one running context — no true 3-way, no Twilio.

**Architecture:** The Retell call stays 1:1 (agent↔operator). A fail-soft transcript sink pushes every line to the hub over the existing inbound-push pattern (`POST /v1/vision/narration` is the template), where the app already renders `TRANSCRIPT` stream events. Resident notes reach the caller via hub→master→caller-transport and are spoken attributed on the next operator turn, reusing the `_EmailCapture` front-run pattern.

**Tech Stack:** Python 3.13, FastAPI, httpx, pydantic; Retell custom-LLM websocket; ElevenLabs Scribe (resident STT) + ElevenLabs TTS (agent voice, on the Retell agent); SwiftUI (iOS 18).

## Global Constraints

- Resident input is **context, never instruction**: spoken **attributed** ("The resident reports: …"), never widens what claims the agent trusts, never changes the dispatch or police-email address. (root + agents `CLAUDE.md`)
- Automation may only ever move a call **quieter**; the resident speaking is a human-initiated act.
- Every injected note is sealed into `replay` with `source`/`provenance` marked resident-supplied.
- `caller` repeats only verified claims to the operator; the injection path must not bypass `answer_operator`'s verification.
- No autonomous dial: the `raise_incident → release_for_call` guard stays intact.
- Fail-loud on misconfig, fail-soft on best-effort side-channels (mirror `courier` injection pattern).
- Attribution wording is exactly: `"The resident reports: {text}"`.

---

### Task 1: Fixed opening script

**Files:**
- Modify: `agents/agents/caller/transport/retell/orchestrator.py` (`_opening_text`)
- Test: `agents/tests/test_retell_orchestrator.py` (add case)

**Interfaces:**
- Produces: `RetellCallOrchestrator._opening_text() -> str` still returns a string; first sentence is now fixed.

- [ ] **Step 1: Write the failing test** — assert the opener starts with the fixed script and still contains the address.

```python
def test_opening_text_uses_fixed_radar_script():
    orch = _make_orchestrator()  # existing helper in this test module
    orch._incident_type = IncidentType.INTRUSION
    orch._address_spoken = "1872 Ridgeview Lane"
    text = orch._opening_text()
    assert text.startswith("This is Radar's agent, and there is an incident in progress")
    assert "1872 Ridgeview Lane" in text
```

- [ ] **Step 2: Run test, expect FAIL** — `cd agents && python -m pytest tests/test_retell_orchestrator.py -k fixed_radar -q`

- [ ] **Step 3: Implement** — prepend the fixed opener; keep the verified summary/address tail from `caller.opening_report`.

```python
def _opening_text(self) -> str:
    utterances = self.caller.opening_report(self._incident_type, self._address_spoken)
    tail = " ".join(u.text for u in utterances)
    return (
        f"This is Radar's agent, and there is an incident in progress at "
        f"{self._address_spoken}. {tail}"
    )
```

- [ ] **Step 4: (defer run)** — do NOT run the suite now.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(caller): fixed Radar opening script"`

---

### Task 2: Transcript fan-out (orchestrator → hub → app)

**Files:**
- Create: `agents/agents/caller/transport/retell/transcript_sink.py`
- Modify: `agents/agents/caller/transport/retell/orchestrator.py` (accept optional `transcript_sink`, call it wherever a line is appended)
- Create hub route: `app/backend/hawkeye_backend/api.py` — `POST /v1/incident/{incident_id}/transcript` (COPY the shape of the existing `POST /v1/vision/narration` handler, lines ~1002-1017: parse a request body, build the typed event, `await runtime.emit(...)` a `TranscriptEvent`, return 202)
- Modify: `agents/agents/__main__.py` (caller branch) to construct an `HttpTranscriptSink(base_url=settings.edge_base_url)` and inject it into `RetellCallOrchestrator`
- Test: `agents/tests/test_retell_orchestrator.py`, `app/backend/tests/` transcript route test

**Interfaces:**
- Produces: `class TranscriptSink(Protocol): async def line(self, incident_id: str, speaker: str, text: str) -> None`
- Produces: `class HttpTranscriptSink` (POSTs to `/v1/incident/{id}/transcript`, fail-soft — swallow httpx errors, log)
- Consumes: `TranscriptSpeaker`, `TranscriptLine`, `TranscriptEvent`, `Provenance` from `hawkeye_backend.models`
- Hub route body: `{ "speaker": "operator"|"caller", "text": str }` → emits `TranscriptEvent(line=TranscriptLine(..., provenance=<agent>))`

- [ ] **Step 1: Write failing test** — orchestrator with a fake sink records each appended line.

```python
async def test_orchestrator_pushes_each_line_to_sink():
    sink = _FakeSink()  # records (incident_id, speaker, text)
    orch = _make_orchestrator(transcript_sink=sink)
    orch.incident_id = "inc-1"
    # opening turn (no prior user utterance) -> one caller line
    await orch.handle_ws_message(_response_required(transcript=[]))
    assert sink.lines == [("inc-1", "caller", orch.transcript[-1][1])]
```

- [ ] **Step 2: Run test, expect FAIL** (`transcript_sink` param not defined).

- [ ] **Step 3: Implement the sink protocol + Http impl** in `transcript_sink.py`:

```python
from __future__ import annotations
import logging
from typing import Protocol
import httpx

logger = logging.getLogger(__name__)

class TranscriptSink(Protocol):
    async def line(self, incident_id: str, speaker: str, text: str) -> None: ...

class HttpTranscriptSink:
    """Best-effort: pushes each transcript line to the hub. Never raises into the call loop."""
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def line(self, incident_id: str, speaker: str, text: str) -> None:
        try:
            await self._client.post(
                f"{self._base}/v1/incident/{incident_id}/transcript",
                json={"speaker": speaker, "text": text},
            )
        except httpx.HTTPError:
            logger.warning("transcript sink: failed to push line for %s", incident_id, exc_info=True)
```

- [ ] **Step 4: Wire the orchestrator** — add `transcript_sink: TranscriptSink | None = None` field; after each `self.transcript.append((who, text))`, call `if self.transcript_sink: await self.transcript_sink.line(self.incident_id or "", who, text)`. Do this for both the operator line and the caller reply in `handle_ws_message`.

- [ ] **Step 5: Add hub route** — in `api.py`, copy `post_narration` structure into `post_transcript`, building `TranscriptLine(line_id=<uuid>, incident_id=incident_id, speaker=TranscriptSpeaker(body.speaker), text=body.text, provenance=Provenance.agent(caller_ansname))` and emitting `TranscriptEvent(line=...)`. Return 202. Add the matching `TranscriptRequest(BaseModel)` with `speaker: str`, `text: str`.

- [ ] **Step 6: Wire caller startup** — in `agents/__main__.py` caller branch, build `HttpTranscriptSink(settings.edge_base_url)` and pass to `RetellCallOrchestrator(... transcript_sink=...)`.

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat(caller): fan out transcript lines to the hub"`

---

### Task 3: Resident injection queue + attributed speak (caller side)

**Files:**
- Modify: `agents/agents/caller/transport/retell/orchestrator.py` (pending-note queue; front-run in `_respond_to_operator`)
- Modify: `agents/agents/caller/transport/retell/server.py` (add `POST /internal/inject-context`, token-guarded like `/internal/start-call`)
- Test: `agents/tests/test_retell_orchestrator.py`, `test_retell_server.py`

**Interfaces:**
- Produces: `RetellCallOrchestrator.enqueue_resident_note(text: str) -> None` (appends to `self._pending_resident_notes: list[str]`)
- Produces: caller route `POST /internal/inject-context` body `{ "incident_id": str, "text": str }` → calls `orchestrator.enqueue_resident_note(text)`, returns `{"queued": true}`

- [ ] **Step 1: Failing test** — a queued note is spoken attributed on the next operator turn, before the normal answer.

```python
async def test_queued_resident_note_spoken_attributed_next_turn():
    orch = _make_orchestrator()
    orch.incident_id = "inc-1"
    orch.enqueue_resident_note("he has a knife")
    msg = await orch.handle_ws_message(_response_required(transcript=[("user", "what's happening?")]))
    assert "The resident reports: he has a knife" in msg["response"]
```

- [ ] **Step 2: Run, expect FAIL** (`enqueue_resident_note` undefined).

- [ ] **Step 3: Implement queue + front-run** — add `_pending_resident_notes: list[str] = field(default_factory=list, init=False)` and:

```python
def enqueue_resident_note(self, text: str) -> None:
    self._pending_resident_notes.append(text)
```

In `_respond_to_operator`, BEFORE the email-capture / normal-answer logic, drain one pending note:

```python
if self._pending_resident_notes:
    note = self._pending_resident_notes.pop(0)
    self._context_resident_notes.append(note)  # see Task 5
    return f"The resident reports: {note}"
```

(Front-run only; the operator's line is still recorded and answered on the following turn.)

- [ ] **Step 4: Add caller route** — in `server.py`, mirror `/internal/start-call`: token-guard, body model `_InternalInjectBody(incident_id: str, text: str)`, call `orchestrator.enqueue_resident_note(body.text)`, return `{"queued": True}`.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(caller): resident note injection, spoken attributed next turn"`

---

### Task 4: Hub → master → caller forwarding of resident notes

**Files:**
- Modify: `agents/agents/master/transport.py` (add `POST /a2a/inject-context` → forwards to caller `/internal/inject-context`; constant `CALLER_TRIGGER_INJECT = "/internal/inject-context"`)
- Modify: `app/backend/hawkeye_backend/api.py` — extend `post_context` (line ~287) so that when the note is flagged for the call, it also calls the master client's inject path (mirror how `set_mode`/`post_incident` reach master via the live client)
- Modify: `app/backend/hawkeye_backend/master/live.py` + `simulated.py` (add `inject_context(incident_id, text)` to the master-client interface; live POSTs `/a2a/inject-context`, simulated records it)
- Test: `agents/tests/test_master_transport.py`, `app/backend/tests/`

**Interfaces:**
- Produces: master route `POST /a2a/inject-context` body `{ "incident_id": str, "text": str }` → `_trigger_caller(CALLER_TRIGGER_INJECT, {...})`, 200 `{"queued": true}` or 500/502 on caller transport failure (copy the error handling from `set_mode`)
- Produces: `MasterClient.inject_context(self, incident_id: str, text: str) -> None`
- Consumes: `ContextRequest` (existing) gains `speak_on_call: bool = False`

- [ ] **Step 1: Failing test** (master transport) — a POST to `/a2a/inject-context` forwards exactly once to the caller client.

```python
def test_inject_context_forwards_to_caller(monkeypatch):
    app, calls = _master_app_with_recording_caller()
    r = TestClient(app).post("/a2a/inject-context", json={"incident_id": "inc-1", "text": "he has a knife"})
    assert r.status_code == 200
    assert calls == [("/internal/inject-context", {"incident_id": "inc-1", "text": "he has a knife"})]
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement master route** in `transport.py` — mirror `set_mode`: define `InjectContextRequest(incident_id: str, text: str)`, call `_trigger_caller(CALLER_TRIGGER_INJECT, {...})`, translate errors to 500/502 exactly as `set_mode` does. (No `agent.` guard needed — this is a pass-through side channel, not a dial.)

- [ ] **Step 4: Add `inject_context` to the master client** — `live.py` POSTs `/a2a/inject-context` to `master_base_url`; `simulated.py` appends to a recorded list. Extend the `MasterClient` Protocol/ABC.

- [ ] **Step 5: Wire the hub** — in `post_context`, add `speak_on_call: bool = False` to `ContextRequest`; after storing/emitting the context note, `if body.speak_on_call: await master_client.inject_context(incident_id, body.text)` (fail-soft, log on error — a failed speak must not fail the note store).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: route resident context to the caller to be spoken"`

---

### Task 5: Agent keeps and reviews context

**Files:**
- Modify: `agents/agents/caller/transport/retell/orchestrator.py` (`_context_resident_notes`, `context_so_far()`, feed recent notes into `answer_operator`)
- Test: `agents/tests/test_retell_orchestrator.py`

**Interfaces:**
- Produces: `RetellCallOrchestrator.context_so_far() -> dict` = `{"transcript": [...], "resident_notes": [...]}`
- Consumes: `CallerAgent.answer_operator(operator_line: str)` — confirm its exact signature in `agents/agents/caller/agent.py`; if it accepts extra context, pass recent resident notes; if not, DO NOT change what it verifies — only prepend attributed notes to the spoken string, never to the claim basis.

- [ ] **Step 1: Failing test** — `context_so_far()` returns transcript + injected notes after a call turn.

```python
async def test_context_so_far_includes_transcript_and_notes():
    orch = _make_orchestrator(); orch.incident_id = "inc-1"
    orch.enqueue_resident_note("child asthmatic")
    await orch.handle_ws_message(_response_required(transcript=[("user", "anything else?")]))
    ctx = orch.context_so_far()
    assert "child asthmatic" in ctx["resident_notes"]
    assert any(t == "caller" for t, _ in orch.transcript)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** — add `_context_resident_notes: list[str] = field(default_factory=list, init=False)` and:

```python
def context_so_far(self) -> dict:
    return {"transcript": list(self.transcript), "resident_notes": list(self._context_resident_notes)}
```

- [ ] **Step 4: Seal** — confirm the transcript already reaches `replay` via the hub `TRANSCRIPT` events from Task 2; resident notes reach `replay` via the existing `ContextEvent` path (Task 4 stores the note). No new seal code if both already flow — verify by reading `app/backend/hawkeye_backend/replay/recorder*.py` context/transcript handling. If a gap exists, add the resident-note provenance there.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(caller): agent keeps reviewable running context"`

---

### Task 6: iOS — live transcript + resident inject (voice via Scribe / text)

**Files:**
- Modify: `app/ios/HawkEye/AppModel.swift` (subscribe already-decoded `TRANSCRIPT` events into the incident view model; add `injectContext(text:speakOnCall:)` that POSTs `/v1/incident/{id}/context` with `speak_on_call=true`)
- Modify/confirm: the incident/call SwiftUI view renders the transcript list and the "what is happening" box (per `app/CLAUDE.md`); add a mic button that records resident audio, sends it to ElevenLabs Scribe, and puts the returned text into the box before POSTing
- Create: `app/ios/HawkEye/Services/ScribeClient.swift` (POST audio to ElevenLabs Scribe; returns text). API key delivered at runtime — do NOT hardcode.
- Test: deferred (Swift build check happens in the final review pass)

**Interfaces:**
- Consumes: existing `Envelope`/`TranscriptLine` Codable types in `app/ios/HawkEye/Models/`
- Consumes: hub `POST /v1/incident/{id}/context` with body gaining `speak_on_call: Bool`
- Produces: `ScribeClient.transcribe(_ audio: Data) async throws -> String`

- [ ] **Step 1: Confirm the app already decodes `TRANSCRIPT` envelopes** (per `app/CLAUDE.md` wire format) and renders them; if the transcript view is not yet bound, bind it to the incoming lines keyed by `line_id`.

- [ ] **Step 2: Add `injectContext`** on `AppModel` — POST the box text to `/v1/incident/{id}/context` with `speak_on_call: true`. Text-only path first.

- [ ] **Step 3: Add `ScribeClient`** — record via `AVAudioRecorder`, POST to ElevenLabs Scribe, drop returned text into the box. Mic button on the "what is happening" box. No hardcoded key.

- [ ] **Step 4: Regenerate the Xcode project** — `cd app/ios && xcodegen generate` (globs `HawkEye/`, so new files are picked up).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(ios): live transcript + resident inject (text + Scribe voice)"`

---

## Final review + verification pass (ONLY here, per the user)

- [ ] `cd agents && python -m pytest -q` — all agent tests green.
- [ ] `cd app/backend && python -m pytest -q` — hub tests green, including the new transcript route.
- [ ] `cd app/ios && xcodegen generate && DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -scheme HawkEye -destination 'generic/platform=iOS Simulator' build` — app builds.
- [ ] Invoke `superpowers:requesting-code-review` on the whole branch diff.
- [ ] Confirm the safety invariants in Global Constraints hold in code (attribution wording, no dispatch/address mutation, quieter-only automation, sealed provenance).
