# Unexpected-presence notice: SMS to the resident, banner in the app

Written 2026-09-19.

## The problem

`agents/intruder` already decides that a confirmed person is not accounted for, the hub already
sends it as `Presence.expected == false`, and the app already renders it: violet on the floorplan
with tracking brackets, a violet roster row reading "Unexpected person / Not accounted for", and
"· 1 not expected" in the home summary.

None of that reaches a resident who is not looking at the screen.
The detection is complete and the delivery is missing.

## What this is, and what it is not

A **notice**, not an incident.

`app/CLAUDE.md` already reserves the word: detections from the sensing agents "surface here as
alerts... An alert is information a person acts on. It is not a call."
An unexpected person is the clearest case of it.

This is on-thesis rather than a departure from it.
Hawk Eye never calls 911 on its own; the sensing agents detect, classify and **inform**, and a human
decides whether emergency services are needed.
A notice is the inform step made to actually arrive somewhere.

It does not raise an incident, does not release `agents/caller`, and does not change what the app
shows about the house.

## Delivery

Two sinks, one notice.

| Sink | Reaches the resident when | Status |
|---|---|---|
| **Twilio SMS** | Phone locked, app closed, resident asleep | Implemented here |
| **In-app banner** | App is open | Implemented here |
| APNs push | Phone locked, app closed | **Not implemented.** A third sink behind the same interface |

### Why there is no local notification

A `UNUserNotificationCenter` local notification needs no Apple Developer Program and would have been
the cheapest thing to build, but the app is what holds the WebSocket, so it can only fire while the
app is running or recently backgrounded.
That is precisely the case the resident does not need help with.

It is also an honesty hazard: on stage it looks identical to a real push, and the difference is
invisible to an audience.
Cut rather than shipped and then caveated.

### Why Twilio rather than APNs

APNs needs the $99 Apple Developer Program, an APNs auth key, a device-token registration endpoint,
and a sender in the hub.
Twilio needs four environment variables and reaches the same phone in the same state.

APNs is the better long-term answer and is the reason `NoticeSink` is an interface rather than a
function call. Adding it changes nothing above the seam.

### Twilio trial limits, stated up front

- The trial only sends to numbers verified in the Twilio console. Fine for one resident; it is why
  the destination number is configuration rather than a roster lookup.
- Every trial message is prefixed "Sent from your Twilio trial account". It will be on screen in any
  recording.
- US A2P 10DLC registration is increasingly enforced even on trial numbers, and this can begin
  refusing without warning.

The mitigation is that the SMS sink is not load-bearing for the demo: the notice is a stream event,
the in-app banner renders off that event, and a Twilio failure is logged and swallowed rather than
breaking the stream.

## The trigger rule

This is the part that decides whether the feature is trustworthy, and it is deliberately
conservative in the same direction everything else in this project is.

A notice fires when **all** of these hold:

1. A presence crosses into `isUnexpected`: `state.isPerson && expected == false`.
2. It has held that way continuously for **5 seconds**.
3. `calibration.healthy` is true.
4. No notice has yet been raised for that `presence_id`.

And then never again for that `presence_id`.

### Why each clause is there

- **`isPerson` is required**, so an `unconfirmed` perturbation can never raise one. The curtain over
  the dryer vent and the person walking through the living room looking different is the burglary
  view's entire argument, and the notice path must not flatten it.
- **Five seconds of hold**, because `expected` can flicker while `agents/intruder` is still
  resolving device association, and a notice is unrecallable once it is an SMS on someone's phone.
- **Calibration gate**, because a stale baseline invents presences. Escalation is already suppressed
  upstream when the baseline is unhealthy; texting someone that there is an intruder in their house
  at 3am on the strength of a bad baseline is its own harm, not a degraded version of a good one.
- **Once per presence**, because a presence that walks room to room is one event, not five.

### Rate limiting

Beyond the per-presence rule: at most one SMS per 60 seconds and five per process lifetime.
A rehearsal loop must not be able to send fifty texts, and a bug in the trigger must not be able to
burn the trial credit.

## Verification

The notice carries the same `Provenance` every other claim carries, and is subject to the same
verification path.

A claim from `agents/intruder` that does not verify does not become a notice.
A compromised sensing agent must not be able to buzz a resident's phone at 3am any more than it can
dial 911; the argument is identical and the enforcement point is the same one.

A DISCARDED intruder claim is already rendered on the incident screen. It does not produce a notice.

## Wire format

A ninth `EventKind`, on the existing `Envelope`, following the shape of every other payload.

```
class NoticeSeverity(StrEnum):
    INFO = "info"
    ATTENTION = "attention"

class Notice(BaseModel):
    notice_id: str
    severity: NoticeSeverity
    title: str            # "Unexpected person"
    body: str             # "Not accounted for. Living room."
    zone: str | None
    presence_id: str | None
    raised_at: datetime
    provenance: Provenance

class NoticeEvent(BaseModel):
    kind: Literal[EventKind.NOTICE] = EventKind.NOTICE
    notice: Notice
```

`app/backend` remains the authority and the Swift types follow it field for field, checked against
`app/backend/schema/` like everything else.

### The SMS body

```
Hawk Eye: unexpected person in the living room, 21:04.
Not accounted for.
```

**The street address is never in the message.** The dispatch address is bound at registration and
sealed; it does not travel in claims and it does not travel in notices. An SMS is a plaintext
message to a device that can be stolen, which is the same threat model that put the address out of
claims in the first place.

## Backend components

- `hawkeye_backend/models/notice.py` - the models above. `Provenance` comes from
  `models/common.py`, unchanged.
- `hawkeye_backend/notices/detector.py` - the trigger rule. Consumes `InteriorState` ticks, holds
  the per-presence timers and the fired set, emits `Notice` or nothing. Pure and synchronous, so the
  rule is testable without a server, a clock, or a socket.
- `hawkeye_backend/notices/sinks.py` - `NoticeSink` protocol with one method, `deliver(notice)`.
  `StreamSink` publishes the `NoticeEvent` onto the existing `EventBus`. `TwilioSink` posts to the
  Twilio REST API. Delivery failures are logged, never raised.
- `hawkeye_backend/config.py` - four new settings, all optional:
  `twilio_account_sid`, `twilio_auth_token`, `twilio_from_number`, `twilio_to_number`.
  Absent credentials mean the Twilio sink is not constructed at all, and the stream sink runs alone.
  The app must work with no Twilio account configured.

Both sinks run in `simulated` and `live` mode alike. The demo runs on the mock path and the text has
to actually arrive, so a mode gate here would defeat the purpose.

## iOS components

- `Models/Notice.swift` - mirrors the Pydantic model.
- `AppModel` gains `notices: [Notice]`, appended on the `notice` event.
- `Features/Home/NoticeBanner.swift` - a dismissible violet banner above the interior view, in
  `Palette.personUnexpected`, matching the language already used in the roster.
- `MockHawkEyeClient` emits a `notice` five seconds after the burglary scenario's fourth presence
  acquires respiration, so the mock path exercises the same code the live path does.

Silent-mode rules still apply to the banner: during an active burglary incident it is visual only,
with no sound and no haptics. A phone that buzzes while someone is hiding is the failure this
product exists to prevent.

## Testing

- The detector is unit-tested against synthetic state sequences: flicker below 5s raises nothing; an
  unhealthy baseline raises nothing; an `unconfirmed` presence raises nothing; a presence that
  qualifies raises exactly one notice however many ticks follow.
- The sink fan-out is tested with a failing sink, asserting the stream sink still receives it.
- The Twilio sink is tested against a stubbed HTTP client. No test sends a real message.
- `app/backend/schema/` gains `event-notice.json`, emitted by `tools/gen_schema.py` from the live
  Pydantic model like every other example, and the iOS decode harness covers it.

## Honesty rule

Per the root `CLAUDE.md`:

- The notice, its provenance, and the verification it is subject to are real.
- The SMS is real and arrives on a real phone.
- **APNs is not implemented**, and "the phone buzzes when the app is closed" is true because of
  Twilio and not because of push. Say which, on stage, before anyone asks.
