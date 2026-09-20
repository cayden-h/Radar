# shutter/

The agent that moves a piece of plastic.

It holds one GPIO pin, one TowerPro SG92R micro servo, and an opaque shield mounted in front of the camera lens.
It will rotate that shield out of the way for exactly one reason: a grant from `master` that it can verify.

**This is the smallest agent in the project and the most important one for the pitch.**
Everything else in Hawk Eye is software claiming things about software. This one is a physical object that moves, on stage, in front of the judge, because a signature checked out.

Read the root `CLAUDE.md` and `docs/PIVOT.md` first. `agents/CLAUDE.md` is the mesh contract this agent lives inside.

## Status

**Built and tested as of 2026-09-19.** The code is `agents/agents/shutter/`, not this directory - this directory
is the contract, and the agent lives in the package with its six siblings so it shares the identity, card,
signing and transport machinery rather than growing a second copy.

| Piece | State |
|---|---|
| The grant, the nonce, all eight refusals, the attestation | Done. `cd agents && python -m pytest tests/test_shutter.py -q` - 21 tests, no hardware |
| `VerifiedGrant` enforced structurally | Done. There is no call that typechecks from a failed verification to a GPIO write |
| Signed refusal observations | Done. Bound to the nonce of the grant refused and addressed to the agent that presented it |
| Identity, both cards, A2A surface | Done. `python -m agents shutter --port 8106` |
| `pigpio` backend | Written, unrun. Needs a servo and `pigpiod`. That is T21 |
| `master` issuing grants | Not here. That is T20, and it is the other half of this contract |

What remains is hardware and the far end of the wire. The gate itself is finished.

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
| `issued_at` | When `master` signed it. Recorded; `expires_at` is the field that decides anything |
| `schema_version` | Refuse what we do not understand rather than reading it charitably. Seven agents at different build stages is the ordinary reason this would fire, not an attack |

`action` is typed as a plain string on the envelope rather than as a pydantic `Literal`, deliberately.
A `Literal` would reject an unknown action at parse time as malformed, and the record should say `unknown_action`,
which is a different and more interesting fact about what someone just tried.

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
| `malformed_grant` | Not a grant at all: oversized, unparseable, or carrying smuggled members |

**`malformed_grant` is an eighth code and not one of the seven**, because it is the floor rather than an attack
with a name. It exists so that "we could not read it" never borrows the wire representation of a check that
actually ran. A refused grant that never parsed also has no nonce, no issuer and no incident to bind its
refusal to, and the signed refusal says so with a sentinel rather than inventing a binding that was never there.

Every one of these leaves the servo where it was.
There is no code path from a failed verification to a `set_angle` call, and it is enforced structurally rather than by discipline: the GPIO write lives behind a function taking a `VerifiedGrant`, and `VerifiedGrant` rejects any construction that does not carry a module-private sentinel only the verifier holds.

### The order the checks run in, which is not cosmetic

Three orderings are load-bearing and each was chosen against a specific way of losing information.

1. **Replay before the nonce is spent.** A nonce is spent by *any* presentation, so a byte-identical replay would otherwise report `stale_nonce` and the more specific finding would be lost.
2. **The name before the signature.** A lookalike is a naming attack and is caught at the name, before any cryptography runs, so that "some other agent entirely" and "`master`'s name over the wrong key" stay distinguishable in the record.
3. **The profile before the signature.** An UNTRUSTED verdict means this agent should not be acted on at all, so whether its signature is good is not a question worth asking.

**A nonce is spent by any presentation, pass or fail.** A nonce released back into the pool by a failed attempt is an oracle, and an attacker who can fail cheaply gets unlimited attempts at one challenge. Never issued, already spent and expired therefore collapse to one answer, because which of the three it was is information a caller has no business learning.

### What a refusal looks like on the wire

A **result**, never a JSON-RPC error. An error would be the wrong shape twice over: it would make a successful defence look like a malfunction to anything watching, and it would leave the reason in a transport frame the sealed record never sees.

```json
{"jsonrpc": "2.0", "id": "...", "result": {
  "position": "closed",
  "commanded_angle": 0,
  "refusal": "unregistered_issuer",
  "detail": "... is not in the trust store, or its discovery is suppressed",
  "observation": {"claim": "<opaque JSON string>", "proof": "<opaque JSON string>"}
}}
```

`observation` is the signed half and it is what makes a refusal evidence rather than an assertion. It is an ordinary `ClaimEnvelope` on field `shutter.refusal`, signed by `shutter`'s own key, **addressed to the agent that presented the grant and bound to the nonce of the grant it refused**. An unbound refusal would say only that a refusal happened somewhere.

It verifies as **ATTRIBUTED, not ASSERTED**, and that is the roster working rather than a shortfall. `shutter` is TRANSACTIONAL: it asserts one physical fact about one piece of plastic, so what it says is relayed as a reported observation. An ASSERTED refusal would mean this agent's word carried further than a shield position should.

## The attestation

After moving, `shutter` signs and returns its own position.
`vision` will not produce a claim unless it has a current attestation saying the shield is clear.

This is not ceremony. It closes a real gap: a camera that reports what it sees while a shield is in front of it is either broken or lying, and both need to be visible rather than silently producing a dark frame that a vision model will happily describe as "a dimly lit room".

The attestation carries the position, the timestamp, the nonce of the grant that caused it, and the servo's commanded angle.
It does **not** carry a claim that the shield is physically where the servo says it is. We have no position feedback on an SG92R.

Said in the data rather than only here: the attestation carries `position_basis: "commanded"` as a field, so a consumer cannot read it as a measurement by accident. It crosses the wire as an opaque JSON string, same as everything else that is signed.

## Choosing a backend

One environment variable, and the stub is the default:

```sh
python -m agents shutter --port 8106                          # StubShutter
HAWKEYE_SHUTTER_BACKEND=pigpio python -m agents shutter ...   # the real pin
```

**The stub is not a placeholder standing in for the real thing.** The demo must never depend on hardware being
alive, so the servo-less path is a first-class implementation and every test in the suite runs against it.

**It does not fall back.** Asking for `pigpio` on a machine with no daemon raises rather than quietly returning
the stub. An operator who asked for the pin and silently got a number has a shutter reporting `open` while the
lens is covered, which is the one failure this agent exists to prevent.

The two are told apart in the data, not by a log line. Each backend declares its own `Source`:

| Backend | `provenance.source` | Class | `simulated` |
|---|---|---|---|
| `StubShutter` | `servo-stub` | SIMULATED | `true` |
| `PigpioShutter` | `servo-gpio` | DERIVED | `false` |

`source_class` and `simulated` are computed from `source` rather than supplied, so a stub-backed shutter cannot
present as a pin-backed one even by mistake. **DERIVED and not MEASURED**, and that is not a technicality:
the SG92R is open-loop, so a position is the angle we commanded and never the angle the shield reached.

## Wiring

Full guide: `docs/hardware/servo-sg92r.md`. The two things that will bite:

- **Do not power the servo from the Pi's 5V rail under load.** The SG92R stalls at over 700mA and the Pi browns out mid-demo, which presents as the whole capture path dying for no visible reason. Separate supply, common ground
- **Software PWM jitters.** The shield twitching between frames looks like a fault and will show up in the footage. Use hardware PWM on GPIO 12 or 18, or `pigpio`

## Limits, stated in the data

1. **There is no position feedback.** The SG92R is open-loop. The attestation reports the commanded angle and says it is commanded, not measured. A shield that jammed would attest open while covering the lens, and the only thing that catches that is the frame itself being dark
2. **The physical shield is a demo-grade mount.** It is not tamper-resistant and does not claim to be. Someone standing at the camera can hold it shut
3. **Nothing stops the camera at the driver level.** The shield is the guarantee, not a software disable. That is deliberate, because a software disable is a claim and a shield is an object

## Tests this agent has

`agents/tests/test_shutter.py`, 21 of them, none of which touch hardware:

```sh
cd agents && python -m pytest tests/test_shutter.py -q
```

They mirror the shapes in `agents/tests/test_wire.py`, because they are the same attacks pointed at a
different target.

| Group | What it holds |
|---|---|
| The nonce | Single use, never-issued, expired |
| The eight refusals | Wrong key, lookalike ANSName, nonce never issued, nonce spent twice, expired nonce, byte-identical replay, expired grant, unknown action, untrusted profile - **and each asserts the commanded angle is unchanged** |
| The happy path | A verified grant does move the stub, so the suite proves a gate rather than a brick |
| The wire | The signed bytes survive the JSON layer; a refusal crosses as a result; a refusal comes back signed and verifies |
| The endpoint | `shutter.challenge`, `shutter.open` and `hawkeye.observe` share one `/a2a`, because that is the endpoint the card publishes and the one `agent.webmesh.ai verify_agent` sends its live message to |
| The honesty rule | A stub-backed shutter says so in the claim; the position is never claimed as measured |
| The pulse arithmetic | Both angles land inside the SG92R's range, and an angle outside its travel is refused rather than clamped |

**The happy-path test is the one that makes the other twenty mean something.** A shutter that refused
everything would pass every refusal case and be useless.

Still owed, and both need hardware: run a real servo through the happy path before the demo and record it
(`python -m agents.shutter.selftest`), and re-run the black-frame check after the mount is touched for the
last time.
