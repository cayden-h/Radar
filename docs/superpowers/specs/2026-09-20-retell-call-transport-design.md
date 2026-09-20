# Retell AI call transport for `agents/caller`

**Date:** 2026-09-20
**Status:** Approved, ready for planning
**Supersedes (as the real transport):** `2026-09-19-twilio-call-bridge-design.md`

## Why

The caller must place a real phone call to a human 911 operator (a teammate's
phone) and hold a two-way conversation driven by what the camera is currently
seeing, speaking only claims it can verify.

The Twilio call bridge built on 2026-09-19 works but Twilio Voice is behind a
paywall. **Retell AI is free for calling**, so Retell becomes the real
transport. Twilio's transport code is retained but dormant (deprecated, no
longer the selected real path) rather than deleted — deleting it is destructive
and buys nothing this weekend.

**ElevenLabs stays.** It is a claimed MLH track and is named in the architecture
diagram in three places. Retell supports ElevenLabs as its TTS provider, so the
Retell agent is configured with `ttsProvider = ElevenLabs` and our existing
`elevenlabs_voice_id`. Retell supplies telephony + turn-taking, ElevenLabs
supplies the voice, and **`CallerAgent` still supplies every word** — the
"custom LLM is the literal brain" property from the Twilio spec is preserved
exactly.

## Scope

- **In:** the caller agent ↔ 911 operator (teammate's phone) call, two-way,
  driven by verified claims, over Retell's Custom LLM WebSocket.
- **Out:** the resident's whisper/silent/full-voice leg. See the divergence
  note below.

## The reuse that makes this cheap and reputable

`CallerAgent`'s decision logic is already transport-agnostic:

- `CallerAgent.opening_report(incident_type, address_spoken) -> [Utterance]`
- `CallerAgent.answer_operator(text) -> Utterance`
- `CallerAgent.bridge.yield_to_human()` — barge-in

The Twilio orchestrator merely *adapts* Twilio's ConversationRelay wire protocol
onto those methods. Retell needs the same kind of adapter and nothing more. The
verified-claims / honesty property (never speak an unverified claim; never claim
the call is cryptographically verified) comes for free because these methods are
reused unchanged.

## Architecture

```
agents/master  ──POST /internal/start-call (bearer)──►  RetellCallOrchestrator.start_call
                                                          │
                                                          ▼
                            POST https://api.retellai.com/v2/create-phone-call
                              from_number = our Retell number (server settings)
                              to_number   = operator's phone (server settings)
                              metadata    = { incident_id }
                                                          │
                              Retell dials the operator's phone ◄── teammate answers
                                                          │
                     Retell opens a WebSocket back to us, one per call:
                        wss://<public_base>/retell/llm-websocket/{call_id}
                                                          │
   ┌──────────────────────────────────────────────────────────────────────┐
   │ inbound (Retell → us)          │ our reaction                          │
   ├────────────────────────────────┼───────────────────────────────────────┤
   │ (on open)                      │ send {response_type:"config", ...}    │
   │ ping_pong                      │ reply pong (echo timestamp)           │
   │ call_details                   │ record call metadata, no speech       │
   │ update_only                    │ record transcript, no speech          │
   │ response_required /            │ first turn → opening_report;          │
   │   reminder_required            │ else → answer_operator(latest user)   │
   │                                │ → {response_type:"response",          │
   │                                │    response_id, content,              │
   │                                │    content_complete:true}             │
   └────────────────────────────────┴───────────────────────────────────────┘
```

Retell manages turn-taking and interruption itself. When a `response_required`
carries a fresh user (operator) utterance, that is the operator speaking; we
answer it. `bridge.yield_to_human()` is invoked when Retell signals the user
started talking over the agent (barge-in), so the barge-in rule is honored.

## New components

All under `agents/agents/caller/transport/retell/`, mirroring the existing
`transport/` module style (raw `httpx`, no vendor SDK, own-vs-injected client,
pure wire functions separated from I/O).

### `retell/client.py`
- `RetellVoiceClient` (Protocol): `create_phone_call(*, from_number, to_number, metadata) -> call_id`.
- `RealRetellVoiceClient`: raw `httpx.AsyncClient`, `Authorization: Bearer <key>`,
  `POST https://api.retellai.com/v2/create-phone-call`, returns `call_id` from
  the 201 body. Own-vs-injected client tracked so `aclose()` only closes what it
  created — matches `RealTwilioVoiceClient`.
- `SimulatedRetellVoiceClient`: returns a deterministic fake `call_id`, records
  every call for assertions. Drives the identical orchestrator path so the demo
  and tests run with no Retell account.

### `retell/protocol.py`
Pure functions + frozen dataclasses for Retell's Custom LLM WS shapes. No I/O.
Field names taken from Retell's live docs (verified at implementation time):

- Parse inbound: `interaction_type` ∈ `ping_pong | call_details | update_only |
  response_required | reminder_required`. `response_required`/`reminder_required`
  carry `response_id` (int) and `transcript` (list of `{role, content}`).
  `ping_pong` carries `timestamp`.
- Build outbound:
  - config: `{response_type:"config", config:{auto_reconnect, call_details}}`
  - response: `{response_type:"response", response_id, content, content_complete, end_call}`
  - pong: `{response_type:"ping_pong", timestamp}`
- A helper to extract the latest operator (role `user`) utterance from a
  transcript, and to detect "no operator has spoken yet" (→ opening report).

### `retell/orchestrator.py`
`RetellCallOrchestrator` — same interface shape the server + master already use:

- `start_call(incident_id, incident_type, address_spoken) -> call_id`: calls the
  client, stores `call_id` and `incident_id`, pre-loads the opening report into
  the transcript. The `call_id` is remembered so the WS route can reject any
  `call_id` this process did not initiate.
- `handle_ws_message(raw) -> dict | None`: maps each Retell message onto the
  reactions in the table above. Returns the dict to send back, or `None` for
  messages that need no reply.
- `transcript_so_far() -> [(speaker, text)]` — parity with the Twilio one.
- `set_mode(...)`: updates the `bridge` model (announcement) only. No Retell wire
  effect, because there is no resident leg on a Retell 1:1 call. Documented, not
  silently dropped.

### `retell/server.py`
`build_retell_transport_app(orchestrator, *, websocket_secret, internal_trigger_token) -> FastAPI`:

- `@app.websocket("/retell/llm-websocket/{secret}/{call_id}")` — the Custom LLM
  WS. The secret is a **path segment**, not a query param, because Retell appends
  `/{call_id}` to the base URL it is registered with; registering
  `wss://<host>/retell/llm-websocket/<secret>` yields
  `.../<secret>/{call_id}` at connect time. **Fails closed** when
  `websocket_secret` is `None` (unconfigured). Rejects any connection whose
  `secret` does not match, and any `call_id` this process did not initiate — no
  open dial/LLM endpoint on the public internet. On open, sends the config
  message, then loops handing frames to `orchestrator.handle_ws_message`.
- `@app.post("/internal/start-call")` — the same internal-trigger route the
  Twilio server exposes, gated by the same bearer token, so **`agents/master`
  needs zero changes**. Destination number is bound from server settings inside
  the orchestrator, never read from the request body (swatting-address rule).

## Wiring & config

### `hawkeye_backend/config.py`
Add:
- `retell_api_key: SecretStr = SecretStr("")`
- `retell_from_number: str = ""` (our Retell-owned E.164 number)
- `retell_agent_id: str = ""` (Retell agent set to Custom LLM + ElevenLabs voice)
- `retell_websocket_secret: str = ""` (static secret in the WS URL path/query)
- `call_transport: str = "retell"` — selector: `retell | twilio | simulated`.
  Default `retell`. Twilio is dormant/deprecated but still selectable.
- `retell_configured` property: true only when api key, from number, and
  websocket secret are all present (all-or-unconfigured, matching the Twilio
  pattern).

The **operator's phone number reuses `mock_911_number`** — it is exactly "the
fake 911 operator's phone."

### `agents/agents/__main__.py`
Replace the Twilio-only caller wiring with a `call_transport` switch:
- `retell` + `retell_configured` + live → `RealRetellVoiceClient` +
  `RetellCallOrchestrator` + `build_retell_transport_app`.
- `retell` unconfigured or not live → `SimulatedRetellVoiceClient` + same
  orchestrator + same app (fails closed on the WS, simulated REST).
- `twilio` → the existing Twilio wiring, unchanged (dormant path).
- `simulated`/default fallback → simulated.

Master's trigger URL (`/internal/start-call`) is unchanged in all cases.

### `.env.example`
Add the four `HAWKEYE_RETELL_*` vars with comments, and keep the ElevenLabs vars
(now consumed as Retell's TTS voice). Note the Retell dashboard step.

## Known divergence: Retell is 1:1, not a conference

The settled architecture is a server-side conference bridge with the resident
added as a leg later. Twilio's conference supports that; Retell's
`create-phone-call` is a direct agent↔operator call and does **not** drop into a
multi-party conference the same way. For this scope (agent↔operator only) that is
simpler and fine. The resident-leg-later path would need a different mechanism
under Retell than under Twilio; the Twilio conference path remains the reference
for it. This is recorded so nobody later assumes Retell inherits the conference
model.

## Reputability checklist (must hold)

1. The operator hears only words produced by `opening_report` / `answer_operator`
   — no unverified claim can reach the operator.
2. The agent never asserts the call is cryptographically verified.
3. The operator destination number is bound from server settings, never from
   request input.
4. The WS endpoint fails closed when unconfigured and rejects unknown `call_id`s
   and missing secrets — no open dial/LLM endpoint on the public internet.
5. `SimulatedRetellVoiceClient` drives the identical orchestrator code path, so
   the tested path is the real path.
6. ElevenLabs remains the voice; the caller agent remains the brain.

## Testing

Match `agents/tests/test_caller.py` style:
- `protocol.py`: parse each inbound type; build config/response/pong; latest-user
  and no-operator-yet detection.
- `orchestrator.py`: with `SimulatedRetellVoiceClient` and a real `CallerAgent` —
  `start_call` triggers the REST call and pre-loads the opening report; first
  `response_required` returns the opening report; a later `response_required`
  carrying an operator utterance returns `answer_operator`'s reply; `ping_pong`
  returns a pong; `update_only`/`call_details` return `None`.
- `server.py`: WS route fails closed when unconfigured; rejects a wrong secret
  path segment; rejects an unknown `call_id`; accepts a started call with the
  right secret and completes a config → response exchange. `/internal/start-call`
  rejects a missing/wrong bearer token and accepts the right one.

## Manual steps for the user (documented, not blocking)

1. Create a Retell account (free calling tier).
2. Purchase/import a Retell phone number → `HAWKEYE_RETELL_FROM_NUMBER`.
3. Create a Retell agent set to **Custom LLM**, WebSocket URL pointing at the
   public `wss://<host>/retell/llm-websocket` (+ the secret), **TTS provider =
   ElevenLabs**, voice = our `HAWKEYE_ELEVENLABS_VOICE_ID` → `HAWKEYE_RETELL_AGENT_ID`.
4. Fill `HAWKEYE_RETELL_API_KEY` and `HAWKEYE_RETELL_WEBSOCKET_SECRET`.
5. Expose the transport server publicly (ngrok or the hosted deployment).
