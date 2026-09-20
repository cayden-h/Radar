# shutter/

The agent that moves a piece of plastic.

It holds one GPIO pin, one TowerPro SG92R micro servo, and an opaque shield mounted in front of the camera lens.
It will rotate that shield out of the way for exactly one reason: a grant from `master` that it can verify.

**This is the smallest agent in the project and the most important one for the pitch.**
Everything else in Hawk Eye is software claiming things about software. This one is a physical object that moves, on stage, in front of the judge, because a signature checked out.

Read the root `CLAUDE.md` and `docs/PIVOT.md` first. `agents/CLAUDE.md` is the mesh contract this agent lives inside.

## Why it is its own agent

The merge principle in `agents/CLAUDE.md` says an agent is a context boundary, not a task, and that two components sharing an input and a tick are one agent with two steps.

`shutter` shares nothing with `vision`.
It has one input (a grant), one output (a position), and no knowledge of what a camera is for.
Folding it into `vision` would make the authorization gate internal to the agent that benefits from it, which is the exact structure the whole project argues against.

It is also the only way the gate is demonstrable.
An internal check is a claim. A separate process that refuses a command and leaves the lens covered is evidence.

## The grant

This is the one place the mesh inverts its pull-only rule, and the inversion is handled rather than ignored.

Everywhere else, `master` asks and sensing agents answer, so `master` controls the nonce.
Here `master` is the one asking for something to happen, so **`shutter` controls the nonce**. The verifier issues the challenge, always, in both directions. That invariant is what the rule was protecting.

Two round trips, DPoP-shaped:

```
master ──POST /a2a  {"method": "shutter.challenge"} ──►  shutter
       ◄── {"nonce": "<opaque, single-use, 10s TTL>"}

master ──POST /a2a  {"method": "shutter.open",
                     "grant": "<opaque JSON string>"} ──►  shutter
       ◄── {"position": "open", "attestation": "<opaque JSON string>"}
```

On localhost the extra round trip costs under a millisecond. Against the 800ms budget in the root `CLAUDE.md`, it is free.

### What a grant contains

The grant crosses the wire as an **opaque JSON string**, never a nested object.
`ClaimVerifier` verifies bytes. Any layer that parses and re-serializes breaks every signature and the failure looks exactly like tampering. `agents/tests/test_wire.py::test_the_signed_bytes_survive_the_json_layer` is the existing guard and the shutter path needs its own.

Fields, all of them covered by the signature:

| Field | Why |
|---|---|
| `nonce` | The one `shutter` just issued. Required and non-empty. "The verifier did not ask for one" and "the presenter omitted it" must not share a wire representation |
| `issuer` | `master`'s ANSName. Checked against the trust card `shutter` fetched, not a configured key list |
| `action` | `open` or `close`. There is no third value and an unknown one is a refusal, not a default |
| `reason` | The `intruder` verdict id that justified this. Recorded, not trusted |
| `expires_at` | Seconds, not minutes. A grant that outlives the situation that produced it is a replay waiting to happen |
| `incident_id` | Null when the shutter opens on an unaccounted-motion verdict, which is the normal case. Set when a human raised the incident first |

### What `shutter` refuses, and what a refusal looks like

A refusal is not an error. It is an observation, it is signed, and it goes into the sealed record.
**The lens stays covered and the agent says why**, which is the demo beat.

| Refusal | Trigger |
|---|---|
| `unregistered_issuer` | The signing key is not the one `master`'s published trust card carries |
| `lookalike_ansname` | An ANSName that resolves to something other than the registered `master` |
| `stale_nonce` | The nonce was never issued, was already spent, or has expired |
| `replayed_grant` | A grant byte-identical to one already honoured |
| `expired_grant` | `expires_at` is in the past |
| `unknown_action` | Anything other than `open` or `close` |
| `untrusted_profile` | `master`'s Trust Index `recommendedProfile` came back UNTRUSTED. Discovery suppression, not revocation |

Every one of these leaves the servo where it was.
There is no code path from a failed verification to a `set_angle` call, and that should be enforced structurally: the GPIO write lives behind a function that takes a `VerifiedGrant` type which only the verifier can construct.

## The attestation

After moving, `shutter` signs and returns its own position.
`vision` will not produce a claim unless it has a current attestation saying the shield is clear.

This is not ceremony. It closes a real gap: a camera that reports what it sees while a shield is in front of it is either broken or lying, and both need to be visible rather than silently producing a dark frame that a vision model will happily describe as "a dimly lit room".

The attestation carries the position, the timestamp, the nonce of the grant that caused it, and the servo's commanded angle.
It does **not** carry a claim that the shield is physically where the servo says it is. We have no position feedback on an SG92R. Say so in the field, do not imply otherwise, and see the limits section.

## Wiring

Full guide: `docs/hardware/servo-sg92r.md`. The two things that will bite:

- **Do not power the servo from the Pi's 5V rail under load.** The SG92R stalls at over 700mA and the Pi browns out mid-demo, which presents as the whole capture path dying for no visible reason. Separate supply, common ground
- **Software PWM jitters.** The shield twitching between frames looks like a fault and will show up in the footage. Use hardware PWM on GPIO 12 or 18, or `pigpio`

## Limits, stated in the data

1. **There is no position feedback.** The SG92R is open-loop. The attestation reports the commanded angle and says it is commanded, not measured. A shield that jammed would attest open while covering the lens, and the only thing that catches that is the frame itself being dark
2. **The physical shield is a demo-grade mount.** It is not tamper-resistant and does not claim to be. Someone standing at the camera can hold it shut
3. **Nothing stops the camera at the driver level.** The shield is the guarantee, not a software disable. That is deliberate, because a software disable is a claim and a shield is an object

## Tests this agent owes

Mirror the shapes in `agents/tests/test_wire.py`, because they are the same attacks pointed at a different target.

- Wrong key, and the lens stays covered
- Unregistered agent, and the lens stays covered
- Lookalike ANSName, and the lens stays covered
- Replayed grant, and the lens stays covered
- Nonce the shutter never issued
- Nonce spent twice
- Expired grant
- The signed bytes survive the JSON layer
- A verified grant with a stub GPIO backend does move, so the tests prove a gate rather than a brick

Run a real servo through the happy path at least once before the demo and record it.
