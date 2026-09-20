# Motion-gated shutter, camera-answered personhood

Date: 2026-09-20.
Status: approved, not yet implemented.
Supersedes the trigger chain described in the root `CLAUDE.md` architecture diagram and in `docs/PIVOT.md`.

## The problem

Two problems, and the second one was found while diagnosing the first.

**The stated problem.** The trigger chain was `motion -> roster check -> shutter opens`.
CSI motion is not an event with a direction.
It cannot say whether somebody entered, left, crossed a doorway, or stood up.
The roster arithmetic that consumed it therefore had no way to bind a motion event to an arrival.

**The problem underneath it.** `agents/intruder` does not actually need direction, because it never asked for an event.
It does standing arithmetic every tick: `bodies seen by CSI` minus `residents whose phones are associated`.
That arithmetic needs a **body count** from the radio.
The 2026-09-19 pivot deleted the thing that produced one.
`agents/people/respiration.py` emitted `people.personhood`, and `IntruderAgent.tick` still hard-fails without it at `agents/agents/intruder/agent.py:100`.
Post-pivot CSI emits "something moved", not "there are three people".
The gate as written stands on a signal that no longer exists.

So the fix is not to add direction to the radio.
It is to stop asking the radio a question it cannot answer.

## What was rejected

**Camera as the authenticator.**
For the camera to tag a body type and decide whether to open, the camera must be watching before the decision is made.
But the decision is what opens the shutter.
Resolving that circularity means the camera runs continuously, which `docs/PIVOT.md` already rejected, and which deletes the shutter grant.
The shutter grant is the GoDaddy track submission.

**Camera-side identity matching.**
An `enrolled_resident` verdict was proposed and dropped during design.
`vision/hawkeye_vision/track.py` states that track identities are stable within a session only, and that a track id says "the same person as a moment ago", never "this particular person".
Producing `enrolled_resident` needs enrollment and cross-session re-identification.
We have no database and `docs/PIVOT.md` rejected building one.

**Closing the shutter on a timer.**
Bounds the exposure without answering the privacy question.
Rejected in favour of closing on a verdict.

## The design

### Two decisions, not one chain

`master` runs two independent decisions where it previously ran one chained one.

**Decision A, open, on motion alone.**

```
presence: perturbation, zone=Z
  -> master issues grant{action:"open", reason:"motion:<claim-id>"}
    -> shutter verifies, rotates 90 degrees, attests
      -> vision opens its Gemini Live session and starts recording
```

No roster in this path.
Motion is the whole trigger.
This drops the dependency on the body count the pivot deleted.

**Decision B, close, on vision's verdict.**

| `vision.occupancy` | `master` does |
|---|---|
| `no_person` | issues `grant{action:"close"}` |
| `person_present` | holds the lens open, hands the verdict to `intruder` |

### The sensor split

Each sensor answers only the question it can answer.

- **The camera answers personhood.** Is this a human or a curtain.
  This is exactly the question the radio used to answer with a respiration signature, and which the pivot deleted.
- **The roster answers identity.** Is this human accounted for by a device on the household roster.

Neither is asked to do the other's job.
Asking the radio to do both was the original fault the pivot was diagnosing, and this completes that correction rather than reopening it.

### What this costs, stated out loud

A resident walking through their own living room keeps the lens open.
The camera sees a person, and the roster's alibi is checked one hop later inside `intruder`.
The shield does not close until the person leaves frame.
That is the honest price of not doing face recognition, and it gets said on stage rather than extracted by a judge.

The privacy claim changes wording.
It was "the lens only opens for an unaccounted person".
It becomes "the lens opens on any motion and physically closes itself within seconds unless it finds a person it cannot account for".
The shield moving twice is a better demonstration than the shield moving once.

### What the ANS story does with this

Unchanged, and that is deliberate.
`master` still issues a grant signed and bound to a nonce that `shutter` itself issued.
`shutter` still verifies the signature and never the reason.
`GrantEnvelope.reason` stays recorded-not-trusted.
Nothing in the refusal path cares whether the grant was triggered by motion or by an intruder verdict.

`close` is already built.
`GrantEnvelope.action` accepts `"open" | "close"` at `agents/agents/shutter/grant.py:39`, and `agents/agents/shutter/shutter.py:234` maps the action to `CLOSED_ANGLE`.
Closing is already nonce-bound, signed and refusal-gated.
No new `shutter` code is required.

## Components

### `agents/people` becomes `agents/presence`

Keeps `presence.py`.
It already emits `people.perturbation` at `presence.py:236` and `people.zone` at `presence.py:213`, which is everything Decision A needs.
Both survive under `presence.*` field names.

Deletes `respiration.py` entirely.
It is 330 lines emitting `personhood`, `respiration`, `respiration_lost`, `breathing_bpm` and `heart_bpm`, all of which `docs/PIVOT.md` cut on 2026-09-19.
It is still on disk, still imported, and still load-bearing for `intruder`.

Deletes `people.headcount` at `presence.py:183`.
The pivot notes it never came from the radio.

### `agents/vision`, new

The capture pipeline in `vision/hawkeye_vision/` exists and is substantial.
The ANS agent wrapper does not: `agents/agents/` contains `people, intruder, master, caller, replay, shutter` and no `vision`.

The new agent needs an identity, its two cards, and a `tick` returning an `AgentObservation` carrying one assertion:

- `vision.occupancy`, value `no_person` or `person_present`, scoped to the one room the fixed camera sees.

The room scope is carried as a field on the assertion, per the honesty rule in the root `CLAUDE.md`.
A scoped claim must not be presentable as an unscoped one by accident.

It consumes the existing `Tracker` Protocol.
`StubTracker` backs every test and the whole mock demo path; `YoloBotSortTracker` is the same interface over real weights.

### `agents/intruder`

Stops reading the radio.
New rule:

```
vision.occupancy == person_present
  AND no registered device associated in that zone
    -> intruder.unexpected_presence
```

Same arithmetic shape, same basis paragraph naming the same holes: the resident who left their phone in the car, the guest, the device that never associates to this router.

Its corroboration claim gets stronger rather than weaker.
It was CSI-derived personhood plus the network.
It becomes a camera plus a router, which are two sensors that fail in genuinely unrelated ways.

### `agents/master`, the refractory lock

Without a lock, a benign close at tick T is followed by a re-open at tick T+1 while the resident is still moving, and the servo oscillates at roughly 1 Hz.
The SG92R stalls over 700mA and `docs/hardware/servo-sg92r.md` records that this browns out the Pi.
Oscillation is not a cosmetic bug here.
It is the demo dying on stage.

`master` holds a `_ShutterEpisode`:

- opened at tick T on a perturbation in zone Z
- closed at tick T+n on a `no_person` verdict
- locked, refusing to issue another `open` for zone Z until perturbation has been clear for `CLEAR_TICKS_TO_DROP` ticks

`CLEAR_TICKS_TO_DROP` is 10 and already exists in `agents/agents/intruder/agent.py` for the track lifecycle.
The same constant and the same reasoning apply.

A suppressed re-open is recorded as a discard with a reason, the way `TrustGate` records everything else it refuses.
The replay console shows the suppression rather than a gap:
`motion at t=14, open suppressed: benign close at t=11, 6 clear ticks of 10`.

The lock lives in `master` and not in `shutter`.
`shutter` must stay a thing that verifies a grant and moves.
Giving it an opinion about whether it should have been asked makes it a second policy engine, which `docs/PIVOT.md` rejected when it rejected folding `shutter` into `vision`.
Keeping the bound in `master` also keeps it testable with no hardware, which the existing 22 shutter tests already prove is the right seam.

## Failure modes

| Failure | Required behaviour |
|---|---|
| `vision` returns no verdict: Gemini down, camera unplugged, agent dead | Shutter stays **open**, and `master` records why. Closing on silence lets an attacker blind the camera by killing one agent. Open-on-failure is safe here precisely because opening is the privacy-costly move and it has already been paid for by a verified grant |
| `vision` returns `no_person` but unverified over the transport | Do **not** close. An unverified claim cannot retire a verified grant's effect. Cap at CORROBORATING and say so in the basis, the same rule `intruder` already applies to its own upstream |
| Motion floods: a fan, a curtain in a draft | The refractory lock holds. The servo receives a bounded number of commands over a long noisy run |
| A replayed `close` grant | Already covered. `ChallengeBook.spend()` burns the nonce on presentation, not on success |
| `master` compromised, issues `open` with no motion | Unchanged and still the headline. `shutter` verifies the signature, never the reason |

### The unbounded open

An open that no verdict ever closes stays open indefinitely, because every automatic way to close it is a way for an attacker to close it.
A silence timeout is exactly the behaviour an attacker who can kill `vision` wants, so there is no timeout.

Instead the condition is made loud.
When `master` has held a grant open for longer than a bounded number of ticks with no `vision.occupancy` verdict at all, it raises a `vision.silent` state to the resident on the watch and the phone, saying that the lens is uncovered and the camera is not reporting.
Closing it is then a human decision, which is the same rule the whole system already applies to calling 911.
The resident closing the lens from the app is a `close` grant like any other, signed by `master` and nonce-bound, so the sealed record shows who retired the open and when.

## Testing

New and changed:

- `agents/tests/test_intruder.py`, rewritten. Its fixtures feed CSI body counts that will no longer exist
- `agents/tests/test_people.py`, shrinks with `respiration.py`
- `agents/tests/test_vision_agent.py`, new. Against `StubTracker`, no weights and no camera
- `agents/tests/test_master.py`, new. The refractory lock, the open-on-vision-failure rule, and the unverified-close rule
- `agents/tests/test_shutter.py`, unchanged. That it needs no changes is the point

The single most important new test is the motion-flood bound.
It asserts a bounded servo command count over a long noisy run, and it is the test that protects the physical demo.

## Documentation to update with the code

`agents/agents/shutter/grant.py` carries two docstrings that describe the old causality, and they are among the first things a judge reads:

- `reason`, currently "The `intruder` verdict id that justified this".
  It is a motion claim id for `open` and a vision verdict id for `close`.
- `incident_id`, currently "Null when the shutter opens on an unaccounted-motion verdict, which is the normal case".
  The normal case is now plain motion.

`docs/swapping-in-real-parts.md` gains a row for `vision.occupancy`.
The seam is the `StubTracker` to `YoloBotSortTracker` swap.
The half-flipped state that looks like something else is a real tracker with no weights file: it returns zero detections, which reads as `no_person`, which produces a closed shutter that looks like a working benign close and is actually a blind camera.
That state needs a startup assertion, not only a documentation line.

The root `CLAUDE.md` architecture diagram and timing budget both show the old chain and need redrawing.
`docs/PIVOT.md` gains a short entry recording this change and the two rejections above, so neither gets re-proposed.
