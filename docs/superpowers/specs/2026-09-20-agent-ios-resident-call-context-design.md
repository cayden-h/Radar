# Resident joins the call through the agent (`agent-ios`)

**Date:** 2026-09-20
**Branch:** `agent-ios` (off `ios-live-call-hookup`, whose live-hub `AppModel`/`Config` work is already on `main`)
**Status:** design approved, ready for implementation plan

## Goal

Turn the current 1:1 Retell call (agent ↔ operator) into a **context-sharing session** where the
resident, running the app on a second phone, watches the whole operator↔agent conversation live and
can inject voice or text that the agent speaks — while the agent keeps one running context fed by
both sides.

This is the shape the user chose after rejecting a true PSTN 3-way: Retell cannot host a persistent
3-party call with the AI staying on the line, and Twilio is not in use.

## Topology

```
operator phone ──PSTN── Retell agent (1:1, ElevenLabs voice)
                              │
                    keeps running context
                    (transcript + resident notes)
                              │
    resident app (2nd phone) ─┤ sees operator+agent transcript live
                              └ injects voice → ElevenLabs Scribe → text
                                or text → agent speaks it (attributed) next turn
```

The resident is **not** a PSTN leg. "Joining" means the agent voices the resident's input on the
call and both humans' words converge into one agent-held context.

## Components and seams

### 1. Fixed opening script
`RetellCallOrchestrator._opening_text` returns a fixed opener for the demo:

> "This is Radar's agent, and there is an incident in progress at {address}. …"

The verified-claims tail (address anchor, incident summary) that the safety rules require stays;
only the opening sentence is fixed. The dynamic `opening_report` path is retained behind a flag so
tests and the Twilio path are unaffected.

### 2. Transcript fan-out (Retell → hub → app)
Add an optional, fail-soft `TranscriptSink` to `RetellCallOrchestrator` (same injection pattern as
the existing `courier`). Every line the orchestrator already appends to `self.transcript` — operator
turns from Retell's live transcript, and the agent's own replies — is also POSTed to the hub.

The hub already has `Store.append_transcript` and a `TRANSCRIPT` stream event (`models/events.py`)
that the iOS app already decodes. So operator display comes from **Retell's built-in transcript**,
the only live source of the operator's words (Retell owns the call audio; there is no raw stream for
a separate STT). No new app decoding is required — only the wire from the orchestrator to the hub.

### 3. Resident injection (app → hub → caller → spoken)
- The app's "what is happening" box POSTs a resident note to the hub. Voice input is transcribed by
  **ElevenLabs Scribe** on the app-controlled resident mic, then sent as text; typed input is sent
  directly. Scribe transcribes the **resident**, not the operator, because that is the only audio we
  control.
- `master` forwards the note to a **new** caller-transport route `POST /internal/inject-context`.
- The orchestrator holds a pending-resident-note queue. On the next Retell `response_required` turn
  it front-runs the reply and speaks the note **attributed** — "The resident reports: …" — then
  falls through to the normal verified-answer path. This reuses the exact additive front-run pattern
  the email-capture flow (`_EmailCapture`) already uses, so it cannot widen what the agent trusts.
- Spoken on the **next operator turn**, not proactively (chosen for simplicity and to respect
  Retell's turn-taking).

### 4. Agent keeps and reviews context
The orchestrator's running context = transcript + resident notes. `answer_operator` is fed the
recent resident notes so verified answers can incorporate resident-supplied facts, always attributed
and never as system observations. Expose `context_so_far()` for review and for sealing into `replay`.

### 5. iOS (second phone)
- Transcript view subscribes to the live `TRANSCRIPT` stream (operator + agent lines).
- "What is happening" box wired to the injection POST; a mic button records resident voice → Scribe → text.
- Uses the branch's existing live-hub connection (`directHubURL` / `autoConnectDirectHub`).

## Safety invariants (from root + agents `CLAUDE.md`, non-negotiable)

- Resident input is **context, never instruction**: spoken attributed, never widens what claims the
  agent will trust, never changes the dispatch or police-email address.
- Automation may only ever move a call **quieter**; the resident speaking is a human-initiated act.
- Every injected note is sealed into `replay` with `source` marked resident-supplied.
- `caller` still repeats only verified claims to the operator; the injection path does not bypass that.

## Non-goals

- No true PSTN 3-way audio; no Twilio; no conference provider.
- No autonomous dial — a human tap still releases the call (`raise_incident` → `release_for_call`
  guard unchanged).
- No live ElevenLabs Scribe on the operator (infeasible with Retell owning the audio).

## Testing

Per the user, verification is deferred until the whole feature (and the other in-flight wires) are
implemented. When run: unit tests for the front-run injection ordering, the transcript sink
fail-soft behaviour, the attribution wording, and that a refused/again-quieter mode change still
holds — mirroring the existing `_EmailCapture` and `set-mode` tests.
