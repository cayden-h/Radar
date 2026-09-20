# Courier demo send: ask for the police email, then force-send 5s later

**Date:** 2026-09-20
**Branch:** `talking`

## Goal

During a live Retell 911 call, the caller agent asks the operator for a police
email at the end of the call (this already happens). Then, **5 seconds after the
agent asks**, the system automatically emails the sealed incident record to a
fixed demo destination (`tringuyen7379@gmail.com`) — and also to whatever email
the operator supplied, if any.

The point is a demonstrable, reliable email landing in a real inbox a few
seconds after the agent asks.

## What already exists (do not rebuild)

- **The ask.** `agents/agents/caller/transport/retell/orchestrator.py` already
  asks "what email should I send the sealed record to?" when a closing cue
  trips (operator says "units are on the way" / an ETA), captures the operator's
  spoken email, reads it back, and calls `courier.deliver(incident_id, email)`.
- **The courier.** `app/backend/hawkeye_backend/replay/courier.py` emails the
  sealed record via Resend, with honest `operator_supplied` vs `configured`
  provenance. `ResendCourier` sends; `NullCourier` no-ops.
- **The seam.** `agents/.../retell/courier_client.py` POSTs to
  `POST /v1/incident/{id}/courier {to}`; the endpoint maps empty `to` →
  `configured` (uses `settings.courier_to`), non-empty → `operator_supplied`.
- **Auto-send on seal.** `runtime._archive_sealed()` already sends to
  `settings.courier_to` when a record seals.

## The constraint that shapes the design

`runtime.deliver()` refuses to send unless the record is **sealed**, and a
record only seals when the **call ends** (`recorder.py`, "911 call ended").
So a literal "send 5 seconds after the agent asks" — while the call is still
live — cannot attach a sealed bundle.

**Decision (chosen by the user): force-send.** 5 seconds after the agent asks,
send whatever record exists, sealed or not. Guaranteed to fire ~5s after the
ask with no dependency on the call-end→seal path. Trade-off: if the call is
still going, the emailed record is a partial snapshot. Acceptable for the demo,
and stated plainly.

## Design

### Data flow

```
operator says a closing cue
        │
        ▼
caller agent asks "what email…?"   ── starts a 5s timer (once per call)
        │                                   │
        │ (operator may answer)             │ sleep 5s
        ▼                                   ▼
capture operator email          force-send the record:
  → send to that address          • to tringuyen7379@gmail.com  (configured)
    (operator_supplied)           • to the operator email if captured (operator_supplied)
        │                                   │
        └───────────────┬───────────────────┘
                        ▼
        POST /v1/incident/{id}/courier {to, force:true}
                        ▼
        runtime.deliver(..., force=true) → ResendCourier.send → inbox
```

### Components to change

1. **Backend `deliver` + courier endpoint — add `force`.**
   - `runtime.deliver(incident_id, *, to, provenance, force=False)`: when
     `force` is true, skip the `if not session.sealed: raise RecordSealed`
     check and send a snapshot of the current record. Everything else
     (chaining the receipt, emitting the event, fail-soft) is unchanged.
   - `CourierRequest` gains `force: bool = False`. `post_courier` passes it
     through. Default false preserves existing behavior.

2. **Backend auto-send-on-seal — make it toggleable.**
   - New setting `courier_auto_send_on_seal: bool = True` (default preserves
     current behavior). Gate the `_archive_sealed` auto-deliver behind it.
   - Set `false` for the demo so the agent-driven force-send is the only send
     and the record sealing later does not double-mail.

3. **Config — new settings.**
   - `courier_delay_s: float = 5.0` — seconds after the ask before the send.
   - `courier_auto_send_on_seal: bool = True`.
   - (Existing, set via `.env`: `courier=resend`, `resend_api_key`,
     `courier_from`, `courier_to`.)

4. **Courier client (agents) — carry `force` and a configured send.**
   - `deliver(incident_id, to, *, force=False)` → POST `{to, force}`.
   - `deliver_configured(incident_id, *, force=False)` → POST `{force}` (empty
     `to`, so the backend uses `courier_to` and records `configured`).
   - Both real (`Http…`) and simulated implementations, plus the `Protocol`.

5. **Orchestrator — schedule the 5s force-send on the ask.**
   - When it transitions `NORMAL → ASKED_EMAIL` (the moment the agent asks),
     schedule exactly one background task (`asyncio.create_task`).
   - The task sleeps `courier_delay_s`, then:
     - `deliver_configured(incident_id, force=True)` → gmail.
     - if an operator email was captured by then,
       `deliver(incident_id, operator_email, force=True)`.
   - Guard so it schedules once per call. Capture `incident_id` at schedule
     time. Fail-soft (never raise into the WebSocket loop), matching the
     existing courier-client contract.
   - `courier_delay_s` is injected into the orchestrator at construction in
     `agents/__main__.py` from settings.

### Provenance stays honest

- The gmail send goes out as **`configured`** (empty `to` → `courier_to`),
  because it is this hub's own demo address, not something a human said.
- The operator send goes out as **`operator_supplied`**, because it is.
- Nothing about the fixed address is promoted to authorization; it is only a
  destination, consistent with the courier's existing doctrine.

## Configuration (`app/backend/.env`, gitignored)

```
HAWKEYE_COURIER=resend
HAWKEYE_RESEND_API_KEY=re_…
HAWKEYE_COURIER_FROM=Hawk Eye <hawkeye@cayden.tech>
HAWKEYE_COURIER_TO=tringuyen7379@gmail.com
HAWKEYE_COURIER_DELAY_S=5.0
HAWKEYE_COURIER_AUTO_SEND_ON_SEAL=false
```

## Testing (run once, at the end)

Unit / integration (no network):
- Orchestrator schedules exactly one force-send when the agent asks; it fires
  after `courier_delay_s`; it targets the configured address; and it also
  targets the operator address when one was captured.
- `deliver(force=True)` sends an **unsealed** record (does not raise
  `RecordSealed`); `force=False` still raises for an unsealed record.
- The endpoint threads `force` through; `courier_auto_send_on_seal=false`
  suppresses the seal-time auto-send.
- Simulated courier client records `force` and the configured send.

End-to-end (manual, at the very end, real Resend):
- Bring up caller + tunnel + master + hub with the `.env` above.
- Place a call; operator says a closing cue; agent asks for the email.
- ~5 seconds later, an email from `hawkeye@cayden.tech` with the record bundle
  lands in `tringuyen7379@gmail.com`.

## Risks / notes

- **Partial record.** A force-send before the call ends emails an unsealed
  snapshot. Stated plainly; acceptable for the demo.
- **Resend deliverability.** `cayden.tech` must be a verified sending domain on
  the Resend account for external delivery to a gmail inbox. An unverified
  domain yields a `sent` receipt and an empty inbox — check the inbox, not just
  the receipt.
- **The ask must happen.** The timer starts on the closing-cue ask. If the
  operator never trips a closing cue, the agent never asks and the send never
  fires. The demo operator will say a closing line.
