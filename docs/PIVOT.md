# The 2026-09-19 camera pivot

This file records what changed, what was deleted, and why.
It exists so that nobody re-proposes a thing that was cut, and so that a judge asking "why does the repo still contain X" gets an answer rather than a shrug.

Read it once. Then read the root `CLAUDE.md`, which describes the system as it is now rather than as it was.

## What changed, in one paragraph

Hawk Eye was a WiFi-sensing system that inferred people, breathing and responsiveness from Channel State Information, and told a 911 operator about them.
It is now a camera system that WiFi sensing gates.
CSI has two jobs left: **something moved**, and **is a registered device attached to that motion**.
When motion is not accounted for by a device on the household roster, a servo pulls a physical shield off a camera lens and the camera starts seeing.
Computer vision, not the radio, is what tells the operator what is happening.

## Why

Three reasons, in order of weight.

**The radio was claiming more than it could measure.**
Respiration, personhood, headcount and responsiveness were all derived from one 1x1 link.
Every one of them carried a limit paragraph, and the limits were load-bearing rather than footnotes: two people within a metre merged, a lost breathing signature was never a finding that someone had stopped breathing, the count actually came from device association rather than the radio.
A system whose central claim needs four caveats before a dispatcher can use it is a system making the wrong central claim.

**A camera can say things a dispatcher can act on.**
"One person, male build, dark jacket, carrying a backpack, currently in the living room moving toward the hallway" is worth more to a responding officer than any respiration figure we could honestly produce.
It is also verifiable after the fact, which the radio claims never were.

**The shutter is a better ANS story than anything we had.**
The track's decision filter asks whether identity determines that something valuable moves.
It now moves a physical object.
A servo that refuses to uncover a lens unless a cryptographically verified grant arrives is a demonstrable, on-stage, physical consequence of agent identity.
The previous answer was "an armed response to an address", which is true but abstract, and which we could never actually show.

## What was cut

| Cut | Was | Why |
|---|---|---|
| Respiration sensing | `people.respiration_lost`, the headline claim | The radio cannot separate shallow breathing, breath-holding and range limits. Camera answers the responsiveness question better |
| Personhood classification | `people` biometrics module | Existed only to decide whether a perturbation was a person. The camera decides that now, and can be checked |
| Headcount | `people` occupancy | Never came from the radio anyway. Came from device association, which survives inside `presence` |
| The Fire incident type | Second demo scenario | Depended entirely on the simulated gas reading |
| The simulated gas sensor | `agents/master/environment.py` | No hardware existed. Its only consumer was Fire |
| Fall detection | already cut 2026-09-19, earlier the same day | See the entry below |

Fall detection was cut before this pivot, for its own reasons, and stays cut.
It was a debounce problem dressed as a clinical variable.

## What was added

| Added | What it is |
|---|---|
| `shutter` agent | One GPIO pin driving a TowerPro SG92R. Verifies a grant from `master`, rotates 90 degrees, attests the position. Refuses everything else |
| `vision` agent | Logitech USB camera on the Pi. Gemini Live session for narration, continuous mp4 segments to disk for the record |
| watchOS app | The actor. Receives the notification, starts the incident, controls transcription |
| Police email handoff | `caller` asks the operator for a destination address near the end of the call and reads it back. `replay` ships the sealed package via Resend |

## What survived untouched

This matters more than the cuts, because it is where the project's value is concentrated.

- **The ANS trust layer.** `agents/core`, the signed claim envelope, the server-issued challenge, per-fetch verification against published trust cards, the thirteen fraud shapes in `app/backend/hawkeye_backend/verification/`. None of it cared what the claims were about
- **The pull-only A2A transport.** `master` still issues the nonce. Still proved end to end in `agents/tests/test_wire.py`
- **The sealed replay record.** Hash-chained, opened when an incident is raised, sealed when the call ends. It now carries video, which makes it more useful, not different
- **The human boundaries.** Plain English to the operator, plain English to the resident, ANS on every hop between. Unchanged
- **The refusal path.** Still the submission. A compromised sensing agent still cannot get a claim past `master`, and now it also cannot get a lens uncovered

## The rule that did not change

**Hawk Eye never calls 911 on its own.**

The pivot makes this easier to hold rather than harder.
The only thing that happens automatically is a shutter opening, which is a privacy decision with a privacy-sized consequence.
A human decides that emergency services are needed, now from the watch, and only then does `caller` dial.

## Things that were considered and rejected during the pivot

Do not re-propose these.

- **Face recognition against any database.** We have no database and no lawful basis for one. `vision` describes a person and states whether they match an enrolled resident. Nothing stronger
- **The camera running continuously with software-side privacy.** A checkbox is not a privacy guarantee. A physical shield is, and it is the thing that makes the ANS grant meaningful
- **Folding `shutter` into `vision`.** It makes the authorization gate internal, which means it stops being demonstrable, which was the entire reason for adding it
- **Auto-dialing on an unaccounted person.** Same objection as before the pivot, now with a camera's worth of false-positive surface
- **Keeping Fire as a second scenario.** One scenario done properly beats two done thinly, and the second one rested on a sensor we do not own

---

# The 2026-09-20 trigger change

A follow-on to the pivot above, recorded here for the same reason: so nobody re-proposes what it rejected.

## What changed

The trigger chain was `motion -> roster check -> shutter opens`.
It is now two independent decisions.

**Motion alone opens the lens.** `presence` reports a perturbation, `master` issues a signed `open` grant, `shutter` verifies it and the shield clears.
No roster in that path.

**The camera's own verdict closes it again.** `vision` reports `no_person`, `master` issues a `close` grant, and the shield drops.
`person_present` holds it open and hands the verdict to `intruder`, which does the roster arithmetic that used to gate the open.

## Why

The stated problem was that CSI motion has no direction: it cannot say whether somebody entered, left, or stood up.

The real problem was underneath it. `intruder` never needed direction, because it never asked for an event - it did standing arithmetic over a **body count**, and the pivot above had already deleted the thing that produced one.
`IntruderAgent.tick` still hard-failed without `people.personhood`, which came from the respiration signature that was cut on 2026-09-19.
The gate was standing on a signal that no longer existed.

So the fix was not to add direction to the radio. It was to stop asking the radio a question it cannot answer.

**Each sensor now answers only the question it can answer.** The camera answers personhood, which is what the radio used to answer with a respiration signature and could never support without four caveats. The roster answers identity. Neither is asked to do the other's job, which was the original fault the pivot was diagnosing.

## What this costs, and it gets said on stage

The privacy claim changes wording.
It was "the lens only opens for an unaccounted person".
It is now "the lens opens on any motion and physically closes itself within seconds unless it finds a person it cannot account for".

A resident walking through their own living room keeps the lens open until they leave frame, because the roster alibi is checked one hop later in `intruder`.
That is the honest price of not doing face recognition.

What it buys is a better demo beat: the shield moves twice, and the second movement is the system deciding it had no reason to look and physically stopping.

## Rejected during this change

Do not re-propose these.

- **The camera as the authenticator.** For the camera to identify a body type and decide whether to open, it must be watching before the decision is made - but the decision is what opens the shutter. Resolving that circularity means the camera runs continuously, which the pivot above already rejected, and which deletes the shutter grant that is the GoDaddy track submission.
- **Camera-side identity matching.** An `enrolled_resident` verdict was proposed and dropped during design. `vision/hawkeye_vision/track.py` states that track identities are stable within a session only, and that a track id says "the same person as a moment ago", never "this particular person". Producing that verdict needs enrolment and cross-session re-identification. We have no database and no lawful basis for one.
- **Closing the shutter on a timer.** Bounds the exposure without answering the privacy question, and a silence timeout is exactly what an attacker who can kill `vision` wants.

## What this deleted

`agents/people` became `agents/presence` and `respiration.py` was deleted outright: personhood, respiration, the responsiveness clock, breathing rate and heart rate.
The pivot above cut them on paper on 2026-09-19; the code went on 2026-09-20.

`people.headcount` and `people.presence_class` went with it. The first never came from the radio, and the second had no input left once respiration was gone.

Three tests in `agents/tests/test_trust.py` that drove Fire classification from a CO reading plus a breathing signature went too. Both inputs were already cut.

`caller`'s operator-question router kept its routes for breathing, respiration and responsiveness, and **points them at an explicit refusal**.
Deleting the routes would let "is she still breathing?" fall through to whatever matched next, and a dispatcher getting a confident answer to a different question is worse than getting none.
