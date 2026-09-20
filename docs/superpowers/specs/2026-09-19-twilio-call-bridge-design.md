# Twilio call bridge: a real (or realistically simulated) 911 call the app can listen in on

**Branch:** `TRIcall`
**Status:** approved design, pending implementation plan

## Problem

`agents/agents/caller` has real decision logic — `CallerAgent.opening_report`, `answer_operator`,
`route_question`, and `Bridge`'s WATCHING/WHISPER/FULL_VOICE state machine — but none of it is
connected to an actual phone call. `app/backend`'s `CallState` enum
(`NOT_STARTED/DIALING/CONNECTED/ENDED/NOT_PLACED`) has no code that ever transitions it. The iOS
`IncidentView.swift` call screen only ever shows a hardcoded canned transcript under
`Config.useMocks = true`; there is no Take Over button, no whisper/full-voice switch, and no real
audio path at all, live or mocked.

This work makes the call real: `caller` places an actual phone call (to a mock "911" number — a
teammate's real phone for the demo), the resident's iOS app can join that same call as a live
audio participant, and the existing pure-logic `CallerAgent`/`Bridge` code becomes the thing that
actually decides what gets said, in a voice provided by ElevenLabs.

**This also replaces the iOS app's existing hardcoded mock call script.** Today's
`Config.useMocks = true` path drives the call screen off a canned, UI-only transcript. That
duplicates what this feature needs anyway, so instead `useMocks = true` will drive the call screen
off the same `SimulatedCallTransport` the real backend uses for local dev (see "Three tiers of
testing" below) — one implementation of "a scripted call," not two.

## Non-goals for this pass

- watchOS. The user's own app already has the Take Over / whisper / full-voice controls scoped to
  `app/ios/` (the phone); `app/watch/` is a separate, later piece of work (`T03`/`T34` in
  `TASKS.md`) and out of scope here.
- Recording the call audio into the replay chain (`T41`/`T44`). Worth doing later; not blocking
  this feature, since the transcript already flows through the existing `Envelope` pipe.
- Deploying `app/backend`/`caller` to Vultr. Development and the near-term demo run through ngrok;
  real hosting is a separate, already-tracked piece of work.
- A production Twilio/ElevenLabs account with a real, verified caller ID etc. — this is a hackathon
  demo dialing a teammate's personal phone, not a PSAP integration.

## Architecture

```
watch/phone: hold "Start Incident"
        │
        ▼
app/backend  ──A2A──►  master  ──A2A──►  caller (agents/agents/caller)
   (edge svc)                              │  owns: agent.py (CallerAgent),
                                            │        bridge.py (mode state machine),
                                            │        guidance.py
                                            │
                                            │  NEW: a plain-HTTP/WS surface (no ANS — same
                                            │  boundary rule as the operator's phone line),
                                            │  reachable via ngrok in dev:
                                            │
                            ┌───────────────┼────────────────────┐
                            ▼                                    ▼
                    Twilio REST API                    Twilio webhooks/WS
                 (create conference,                 (voice TwiML, status
                  add/mute/coach                      callbacks, ConversationRelay
                  participants)                        text-in/text-out socket)
                            │                                    │
                            ▼                                    ▼
                 ┌────────────────────── Twilio Conference ──────────────────────┐
                 │  Leg 1: PSTN dial to        Leg 2: TwiML App →       Leg 3:   │
                 │  HAWKEYE_MOCK_911_NUMBER    <Connect><ConversationRelay>      │
                 │  (a teammate's real phone)   ElevenLabs voice for TTS  iOS app │
                 │                               text turns driven by     (Twilio │
                 │                               CallerAgent.answer_*     Voice   │
                 │                                                        SDK)    │
                 └──────────────────────────────────────────────────────────────┘
```

**`agents/agents/caller` owns the new Twilio-facing HTTP/WS server, not `app/backend`.** Twilio is
a transport carrying the same "no ANS, plain conversation" boundary that already applies to the
911 operator, and that boundary belongs to `caller` per the root `CLAUDE.md`. `app/backend` keeps
its existing rule — the app never talks to an agent directly — by only ever going through `master`.

### Why ConversationRelay + ElevenLabs voice, not ElevenLabs' own agent

Researched directly against ElevenLabs' and Twilio's docs before committing to this (see chat
history for sources). ElevenLabs' plug-and-play "native Twilio integration" — where their own
agent/LLM owns the whole call — **cannot stay in a conference**: their `transfer_to_number` tool's
conference-transfer mode always removes the AI agent once a transfer completes, leaving only a
2-party call. That's incompatible with a resident's app joining as a live 3rd leg.

Twilio's own documented pattern (`Add Participant` API with `To=app:{TwiML App SID}`, whose TwiML
returns `<Connect><ConversationRelay>`) adds a text-in/text-out AI leg to a conference cleanly.
ConversationRelay does STT itself, sends the operator's transcribed speech to **our** WebSocket
server as plain text, our server (running the existing `CallerAgent` logic — verified-claim
answers, discard-if-unverifiable) decides the reply text, and Twilio speaks it back using an
ElevenLabs voice (confirmed supported: Flash 2.5 model, ~75ms latency). `CallerAgent` stays the
literal brain of what gets said — ElevenLabs supplies voice quality only. This matches the
project's "caller only repeats what it verified" story more literally than routing decision-making
through a third-party LLM would.

## Components

### `agents/agents/caller/` — new

- **`transport/twilio_server.py`** — a small FastAPI app (separate process/port from the A2A
  server) exposing:
  - `POST /twilio/voice` — TwiML webhook for the mock-911 PSTN leg (`<Dial><Conference>`)
  - `POST /twilio/agent-leg` — the TwiML App's webhook, returns `<Connect><ConversationRelay>`
    pointed at the WS endpoint below, ElevenLabs voice configured as TTS provider
  - `WS /twilio/conversation-relay` — ConversationRelay's text protocol (`setup`/`prompt`/
    `interrupt` messages in, text replies out), driving `CallerAgent.opening_report` /
    `answer_operator` / `route_question`
  - `POST /twilio/status` — call status callbacks, transitions `CallState`
  - Every route validates `X-Twilio-Signature` against `HAWKEYE_TWILIO_AUTH_TOKEN` before touching
    any agent logic.
- **`transport/twilio_client.py`** — thin wrapper over the Twilio REST calls actually used
  (create conference via participant dial-out, add participant, mute/coach participant, end
  conference). Same shape as `notices/sinks.py`'s `TwilioSink`: real `httpx` calls behind an
  interface that tests can fake.
- **`transport/simulated.py`** — `SimulatedCallTransport`: fakes conference/participant state and
  plays a scripted-but-realistic transcript through the same `Bridge`/`CallerAgent` code path and
  the same outbound event shape as the real transport. No network calls at all.
- A new A2A directive on `caller` ("start call") that `master` invokes after a human's Start
  Incident tap — `caller` picks real vs. simulated transport based on `HAWKEYE_MODE`.

### `app/backend/hawkeye_backend/`

- No new agent-facing logic — it already relays `Envelope` events over `WS /v1/stream`, and
  `TranscriptEvent`/`InstructionEvent`/`VerificationEvent` already model everything a call turn
  needs. No new event *type* required.
- New: an endpoint that, given an active incident, asks `master` (which asks `caller`) for a
  short-lived Twilio Access Token scoped to one Conference SID, for the iOS app's Voice SDK leg.
- New: a mode-change endpoint (Take Over / whisper / full-voice / speak) that forwards to `master`
  → `caller` → `Bridge.set_mode()`, surfacing `ModeChangeRefused` as a plain-English reason rather
  than a silent no-op.

### `app/ios/`

- Add the Twilio Voice SDK (`twilio/twilio-voice-ios`, SPM) as the **one** third-party dependency
  exception to the "no third-party dependencies" rule — justified the same way native iOS itself
  is justified: an audio path the app must control precisely enough to keep a phone silent while
  someone is hiding.
- `IncidentView.swift` gains: Take Over control (1.5s hold), the three labeled mode controls
  ("Listening only" / "Speak" / "Turn on sound") per the copy already specified in `app/CLAUDE.md`,
  and joins the conference via the SDK using the access token from `app/backend`.
- **Delete the existing hardcoded mock call transcript.** `Config.useMocks = true` now talks to a
  local instance of the same call flow backed by `SimulatedCallTransport` (via a mock
  `HawkEyeClienting` implementation, consistent with the app's existing pattern of mocking behind
  the same protocol the real client uses) instead of a bespoke canned script.

## Call data flow — starting a call

1. Resident holds **Start Incident** → `POST /v1/incident` (existing) → `master` (A2A) → `caller`
   gets the new "start call" directive.
2. `caller` creates a Twilio Conference (named by incident ID) and makes two `Add Participant`
   calls: Leg 1 dials `HAWKEYE_MOCK_911_NUMBER` into `<Dial><Conference>`; Leg 2 dials the TwiML
   App, which answers with `<Connect><ConversationRelay>`.
3. `CallerAgent.opening_report()` is spoken first, once the ConversationRelay socket's `setup`
   message arrives.
4. Every operator turn: ConversationRelay transcribes → `prompt` message over the WS →
   `CallerAgent.route_question`/`answer_operator` (fans out through `master` for fresh verified
   answers) → reply text → Twilio speaks it in the ElevenLabs voice.
5. Every turn, both directions, becomes a `TranscriptEvent` on the existing `WS /v1/stream` — no UI
   change needed for the transcript feed itself.
6. `CallState` actually transitions: `DIALING` → `CONNECTED` on leg 1 answer, `NOT_PLACED` if the
   mock 911 leg never picks up (busy/no-answer/voicemail) — resident is told plainly, matching the
   project's existing "say what was refused/failed, plainly" ethos.

## Take Over / mode changes

`app/backend` never talks to `caller` directly. iOS mode control (1.5s hold) → `app/backend` →
`master` (A2A) → `caller` → `Bridge.set_mode()` (existing state machine — already enforces
"automation only moves quieter") → on success, `caller` calls Twilio's Participant API (`Muted`,
`Coaching`/`CallSidToCoach`) on the app's leg. Whisper's "resident hears nothing" half is enforced
client-side in the iOS app (mute local playback of the remote track), since Twilio's `coaching`
alone would still let the coach hear the conference.

## Security / "reputable"

- Every Twilio webhook route validates `X-Twilio-Signature`; unsigned/forged requests are rejected
  before reaching any agent logic.
- `HAWKEYE_MOCK_911_NUMBER` is a fixed env value, never a request parameter — `caller` only ever
  dials that number, mirroring the project's existing rule that a dispatch address must be sealed,
  not carried in a claim.
- iOS Access Tokens are short-lived, scoped to one Conference SID, minted by `caller` and handed
  through `master`/`app/backend` — never a long-lived credential in the app.
- Every transcript line keeps its attribution when it reaches `agents/replay` later (operator-said
  vs. resident-typed vs. agent-verified-claim), matching the existing rule for the "what is
  happening" box.
- Secrets load from env only (`HAWKEYE_TWILIO_ACCOUNT_SID/AUTH_TOKEN`, `HAWKEYE_ELEVENLABS_API_KEY`),
  never logged.

## Three tiers of testing

1. **Pure unit tests, no network.** `Bridge` mode logic, ConversationRelay message parsing/routing,
   TwiML building, `twilio_client.py` against a fake `httpx` client (same pattern as the existing
   `TwilioSink` tests). Runs in CI, every change.
2. **Simulated call mode, no external accounts.** `SimulatedCallTransport` drives the identical
   `Envelope`/WS pipe and the identical iOS call screen code as a real call, with a scripted
   transcript. Used for all UI iteration and is also the demo's fallback if live infra flakes.
   This is also what `Config.useMocks = true` now uses on iOS.
3. **Real end-to-end, needs ngrok.** `ngrok` tunnels local `app/backend`/`caller` to a public
   HTTPS/WSS URL (`HAWKEYE_PUBLIC_BASE_URL`), registered as the TwiML App's Request URL and the
   Twilio number's voice webhook (manual, one-time-per-ngrok-session Twilio console step, documented
   in a new `docs/hardware`-style setup note). Exercised occasionally, not on every change.

## New configuration

All under the existing `HAWKEYE_` prefix (`hawkeye_backend/config.py`) plus equivalents in
`agents/agents/caller`'s own settings:

```
HAWKEYE_TWILIO_ACCOUNT_SID=            # already exists (SMS sink)
HAWKEYE_TWILIO_AUTH_TOKEN=             # already exists (SMS sink)
HAWKEYE_TWILIO_VOICE_NUMBER=           # Twilio number originating the outbound dial
HAWKEYE_TWILIO_CONFERENCE_APP_SID=     # TwiML App SID for the ConversationRelay leg
HAWKEYE_MOCK_911_NUMBER=               # E.164, a teammate's real phone
HAWKEYE_ELEVENLABS_API_KEY=
HAWKEYE_ELEVENLABS_VOICE_ID=           # voice used for the caller's ConversationRelay TTS
HAWKEYE_PUBLIC_BASE_URL=               # ngrok URL in dev; real host later
```

## Open items for the implementation plan (not this doc)

- Exact ConversationRelay WS message schema (frame types/fields) needs pinning down against
  Twilio's WebSocket-messages reference at implementation time — the architecture doc above found
  the high-level protocol (text in, text out) but not the wire-level field names.
- Whether the iOS Voice SDK access token is minted directly by `caller` or proxied once more
  through `master`/`app/backend`'s existing token-vending patterns, if any exist — to be resolved
  by whoever implements the token endpoint, checking current `app/backend` auth code first.
