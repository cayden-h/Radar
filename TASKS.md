# TASKS.md

The Hawk Eye work board, rebuilt for the 2026-09-19 camera pivot.

**This is not a per-person assignment sheet.** It is a dependency-ordered queue that three people pull from.
Read `docs/PIVOT.md` first, then the root `CLAUDE.md`, then this.

## How to use it

1. **Claim a task by editing this file**: put your initials in the Who column and commit that change on its own, before you start work. That commit is the lock
2. **Work on a branch named after the task ID**: `git checkout -b t14-shutter-grant`
3. **A task is done when its Done-when line is true**, not when the code is written. Most of them name a command
4. **If you finish and nothing is unblocked, take the highest-numbered unblocked task in any lane.** Do not wait for your lane

Tags in the Skill column say what a task needs, so you can pull from outside your lane when yours is blocked:
`py` Python, `swift` SwiftUI, `hw` physical hardware, `web` HTML/JS, `ops` deployment, `any` no specialism.

## The three roles

Roles decide who picks first when several tasks are open, not who is allowed to do what.

| Role | Owns the outcome for | Opening lane |
|---|---|---|
| **Carry** | The agent mesh, ANS, and integration. The submission lives here | Lane A |
| **Apple** | The watch and the phone. The surface the room actually looks at | Lane C |
| **Edge** | The Pi, the backend, the record, and the media | Lanes B and D |

**The Carry should never be the person debugging a servo.** If the Carry is blocked on hardware, the hardware is being done by the wrong person.

## The critical path

Everything else is decoration if this line does not complete:

```
T01 delete  ─►  T10 presence  ─►  T13 intruder  ─►  T14 shutter grant  ─►  T16 vision claims
                                                          │                      │
                                                          ▼                      ▼
                                                    T20 master wiring  ──►  T30 notice to watch
                                                                                 │
                                                                                 ▼
                                                                          T31 start incident
                                                                                 │
                                                                                 ▼
                                                                          T40 caller  ─►  T44 police email
                                                                                 │
                                                                                 ▼
                                                                          T50 the refusal demo
```

**T50 is the submission.** If Sunday morning arrives and only one thing works, it must be T50.

---

# Phase 0 - Unblock everyone. Do these first, in parallel

These three exist so that nobody is waiting on anybody at 2pm.

### T01 - Delete what the pivot cut
**Lane** cleanup · **Skill** py · **Blocks** T10, T13, T20 · **Who** ___

Remove, do not comment out:

- `agents/agents/people/` respiration, personhood and occupancy modules
- `agents/agents/master/environment.py` and every import of it
- The Fire incident type, its classification rows, and the fire branch of `app/backend`'s demo runner
- `respirationLostS`, CO fields, and the three-state person classification from the iOS models
- Every test that tests a deleted thing. Delete them; do not skip them

**Done when** `cd agents && python -m pytest -q` and `cd app/backend && .venv/bin/python -m pytest -q` both pass with zero skips, and `grep -ri "respiration\|co_ppm\|\.fire" --include=*.py --include=*.swift` returns only history in comments.

**Watch for**: this will delete roughly 40 tests. That is correct. A test suite that still passes while testing a cut capability is worse than no test.

### T02 - Scaffold the two new agent packages
**Lane** A · **Skill** py · **Blocks** T14, T16 · **Who** ___ · **`shutter` half DONE, `vision` half open**

`agents/agents/shutter/` and `agents/agents/vision/`, each with:

- An `Agent` subclass with a real `tick`, returning `Unknown` for everything for now
- An identity, both cards, registered in `scripts/build_cards.py`
- An entry in `agents/agents/__main__.py` so `python -m agents shutter --port 8106` runs

**Done when** both agents start, serve `/a2a`, serve both cards, and `python scripts/build_cards.py --check` passes.

**Why first**: every downstream task can then be written against a running process rather than an idea.

**`shutter` is done** and went straight past the returns-Unknown stage into T14; `python -m agents shutter --port 8106`
serves both cards and `/a2a`, and `--check` passes for six. **`vision` is still open** and is now the only thing
blocking T15 and T16.

### T03 - Scaffold the watchOS target
**Lane** C · **Skill** swift · **Blocks** T30, T31 · **Who** ___

**DONE**, and it went past the scaffold. Branch `t03-watch-app`.

A watchOS target in `app/ios/project.yml`, sharing `Models/`, `Shared/` and `DesignSystem/` by source path.
**Three screens, not four**: Idle, Notice, Saved. The live-incident and transcribe screens were cut and the reasoning is in `app/CLAUDE.md`.
WatchConnectivity both directions, carrying a `WatchSnapshot` out and a `WatchCommand` back rather than a bare heartbeat.

**Done when** `xcodegen generate && xcodebuild ... build` succeeds for both targets, and the watch simulator shows the Idle screen with a heartbeat arriving from the phone simulator.

**Verified:** both targets build; 12 unit tests on the wire codec and the router pass; the four existing UI tours still pass.
On a paired iPhone 18 Pro Max and Apple Watch Series 12, the phone logged seven `published` snapshots and the watch logged every one `received`.

**Watch for**: XcodeGen watchOS targets need a matching `WKCompanionAppBundleIdentifier` and the bundle IDs must nest exactly. Getting this wrong produces a build that succeeds and a watch app that never pairs.

---

# Phase 1 - The chain

## Lane A - Agents and ANS

### T10 - `presence`, gutted and renamed
**Lane** A · **Skill** py · **Needs** T01 · **Blocks** T13 · **Who** ___

Rename `agents/agents/people/` to `agents/agents/presence/`. Contract is the four fields in `agents/CLAUDE.md`: `motion`, `zone`, `devices_associated`, `since_s`. Nothing else.

**Done when** the agent ticks against a recorded CSI session and emits motion claims, and its card's `x-hawkeye.mustNotClaim` lists respiration, headcount, personhood and identity, with a test asserting it.

### T11 - Deploy the five existing agents to public hostnames
**Lane** A · **Skill** ops · **Blocks** T12, T50 · **Who** ___

**This is the hard track requirement and it has been open for a day.** Vultr, one box, seven processes behind a reverse proxy, TLS terminating at the edge.

**Done when** `curl https://<host>/.well-known/agent-card.json` works from a phone on cellular, for every agent that exists at that moment.

**Do this before the agents are finished.** Empty agents reachable now beats complete agents on a laptop on Sunday.

### T12 - Register the domain and the agents with ANS
**Lane** A · **Skill** ops · **Needs** T11 · **Blocks** T50 · **Who** ___

GoDaddy Registry. DNSSEC on. Register each agent, publish the `_ans` records, seal registration into the transparency log.

**Done when** `agent.webmesh.ai verify_agent` returns a passing `compatibility_verdict` for at least `master` and `shutter`.

**This also wins MLH Best Domain Name for free.** Pick a name worth saying on stage.

### T13 - `intruder` against the new `presence` contract
**Lane** A · **Skill** py · **Needs** T10 · **Blocks** T14 · **Who** ___

Roster plus device association, unchanged in shape. Sticky verdict so the shutter does not flap.

**Done when** a fixture where motion appears with no associated device returns unaccounted, one where a roster device is associated returns accounted, and the verdict survives three clear ticks before dropping.

### T14 - The shutter grant, end to end, on a stub GPIO backend
**Lane** A · **Skill** py · **Needs** T02, T13 · **Blocks** T16, T20, T50 · **Who** ___ · **DONE 2026-09-19**

**The single highest-value task on this board.** Full spec in `shutter/CLAUDE.md`.

- `shutter.challenge` issuing a single-use nonce with a 10s TTL
- `shutter.open` verifying a grant against `master`'s published trust card
- The seven refusals, each returning a signed observation and leaving the stub angle unchanged
- A `VerifiedGrant` type that only the verifier can construct, and a GPIO write that takes nothing else

**Done when** `pytest agents/tests/test_shutter.py` passes all seven refusal cases plus the happy path plus the bytes-survive-JSON guard, with no hardware attached.

**Done.** 22 tests pass with no hardware. Beyond the spec, three things came out of building it and are worth knowing
before you touch the neighbouring tasks:

- **An eighth refusal, `malformed_grant`**, as the floor beneath the seven, so "we could not read it" never borrows
  the wire representation of a check that actually ran
- **Refusals come back signed**, bound to the nonce of the grant refused, and verify as ATTRIBUTED rather than
  ASSERTED - which is `shutter`'s TRANSACTIONAL profile working correctly
- **`Agent.a2a_methods(signer)` is new.** `shutter` is the one agent that takes an order rather than answering a
  question, and its methods share the one `/a2a` with `hawkeye.observe`. Two routers on that path silently
  resolved to whichever registered first, which would have surfaced as a baffling T20 bug

**T13 turned out not to block it.** The verification path reads no `intruder` verdict; only *master issuing* grants
does, which is T20.

### T15 - `vision` against a fixture video file
**Lane** A · **Skill** py · **Needs** T02 · **Blocks** T16 · **Who** ___

Frame source reading an mp4 at real time, the luminance guard, and the segment writer producing closed, hashable 10s files.

**Done when** running `vision` against a fixture produces segment files with correct hashes, and a deliberately dark fixture produces `frame_too_dark` rather than a description.

### T16 - `vision` claims, gated on the shutter attestation
**Lane** A · **Skill** py · **Needs** T14, T15 · **Blocks** T20 · **Who** ___

No claim without a current verified attestation. `Unknown(reason="shield_closed")` otherwise.

**Done when** three tests pass: absent attestation, stale attestation, valid attestation, and only the third produces a description.

### T17 - Gemini Live narration
**Lane** A · **Skill** py · **Needs** T15 · **Blocks** T40 · **Who** ___

Persistent WebSocket session per incident, 1 fps frames in, narration out. Claims carry `source: generated` and the room scope.

**Done when** a session dropped mid-fixture produces `narrator_unreachable` and **the recording keeps running**. That second half is the test that matters.

### T18 - Certificate drift detection
**Lane** A · **Skill** py · **Needs** T12 · **Who** ___

The cheapest demonstrable use of ANS available to us, and currently not surfaced at all. Watch each peer's card hash and server cert fingerprint; a drifted peer's claims get discarded with a stated reason.

**Done when** changing a peer's card on disk causes `master` to discard its next claim and log the drift.

### T19 - Trust Index safety-dimension evidence producer
**Lane** A · **Skill** py · **Needs** T12, T16 · **Who** ___

**The strongest available differentiator on the track, and the pivot makes it much stronger.**
POST observations to `/v1/internal/observations/import`: an agent that described a person the recorded footage does not show is behaving unsafely.

**Done when** a staged mismatch between a claim and the footage produces a posted observation, and the Trust Index reflects it.

*Optional-but-valuable. Take it only if the critical path is clear.*

### T20 - `master` wiring: grant issuance and the new classification table
**Lane** A · **Skill** py · **Needs** T01, T14, T16 · **Blocks** T30, T40 · **Who** ___

The five-row table in `agents/CLAUDE.md`. The shutter grant on an unaccounted verdict. `traceparent` generated at incident open and propagated.

**Done when** the row "unaccounted motion + shutter refused to open" produces a system event and **no incident and no visual claim**, with a test asserting master does not reach for the radio to fill the gap.

## Lane B - The Pi

### T21 - Servo wired, powered and calibrated
**Lane** B · **Skill** hw · **Needs** T14 ✅ · **Blocks** T22, T60 · **Who** ___ · **unblocked**

Follow `docs/hardware/servo-sg92r.md`. Separate supply, common ground, `pigpio`, hardware PWM.

The driver is written (`agents/agents/shutter/pigpio_backend.py`) and unrun. Flip with
`HAWKEYE_SHUTTER_BACKEND=pigpio`; it **raises rather than falling back** to the stub if `pigpiod` is not up,
because a shutter that silently became a number would report `open` with the lens covered.

**Done when** `python -m agents.shutter.selftest --backend pigpio` moves a real servo, and a camera frame taken with the shield closed has a mean luminance near zero.

**The self-test bypasses the gate deliberately** and proves nothing about it - the gate is proved by
`tests/test_shutter.py` on a laptop. This task is the physical half only.

**The power step is not optional and not a detail.** A servo on the Pi's 5V rail will brown the Pi out mid-demo and the failure will not mention the servo.

### T22 - Camera mounted and configured
**Lane** B · **Skill** hw · **Needs** T21 · **Blocks** T60 · **Who** ___

Follow `docs/hardware/logitech-camera.md`. MJPG, fixed exposure, fixed white balance, exposure settings in the `vision` startup path rather than someone's shell history.

**Done when** both capture paths run off one open device for five minutes with no dropped frames, and `vcgencmd get_throttled` returns `0x0`.

### T23 - Build the shield and verify it actually shields
**Lane** B · **Skill** hw · **Needs** T22 · **Who** ___

Opaque flag, fully covering at the closed position, clear at open.

**Done when** the black-frame check in the camera guide passes, **and is re-run after the mount is touched for the last time**.

**This is the check that protects the project's central privacy claim.** A shield leaving a crescent of lens visible turns it into a prop, and nobody would notice.

### T24 - Capture a representative CSI session at the house
**Lane** B · **Skill** hw · **Needs** T10 · **Who** ___

A person entering an empty room, several times, from the entry point the demo uses. That is the only shape the pivot needs.

**Done when** the session replays through `presence` and produces a clean motion event at each entry, and the file is committed or stored somewhere the team can reach.

**Do this while the capture path is working**, not after it breaks.

## Lane C - Watch and phone

### T30 - The notice on the watch, carrying the camera's first sentence
**Lane** C · **Skill** swift · **Needs** T03, T20 · **Blocks** T31 · **Who** ___

**DONE.** Branch `t03-watch-app`.

Still frame and narration line. **Two controls, not three**: Start Incident and This is expected.
Remember this visitor stayed on the phone because naming needs a keyboard, and the Saved screen says so rather than leaving the control unexplained.

It also ships as a real wrist notification, with a custom long look carrying the frame and the sentence.
It is a **local** notification the watch raises from the relayed notice, not a push: no APNs, no push server, no paid account.

**Done when** a notice fired from the mock reaches the watch simulator within three seconds of the trigger, carrying a real sentence rather than a generic string.

**Verified:** the notice crosses the live relay carrying its JPEG, and `PhoneWatchRelay` refuses to build a `WatchNotice` without a narration line, so a generic string cannot reach the wrist by accident.

**This is the demo's emotional beat.** A generic "motion detected" here throws away the whole pivot.

### T31 - Start Incident from the watch
**Lane** C · **Skill** swift · **Needs** T30 · **Blocks** T40 · **Who** ___

**DONE against the mock hub. Not yet verified against a live backend.** Branch `t03-watch-app`.

Hold 1.5s, relayed through the phone, which calls `raiseIncident`. The watch shows the hub's answer rather than its own optimism: `recorded` is set from the acknowledgement, never on send.

**Done when** holding the control on the watch simulator opens an incident in the backend, and a tap shorter than 1.5s does nothing at all.

**Still open:** the hold and the relay are exercised end to end, but only against `MockHawkEyeClient`. Point the phone at a running hub and confirm the incident actually lands before calling this closed.

### T32 - The shield states in the iOS interior view
**Lane** C · **Skill** swift · **Needs** T20 · **Blocks** T50 · **Who** ___

Four states: closed, opening, open, **refused**.

**Done when** all four render from the mock, and **the refused state is good with nothing to show**: no feed, no motion dot, and a plain-English line saying something asked to open the camera and could not prove it was allowed to.

**Spend your best hour here.** It is the only place a non-technical judge sees a cryptographic refusal as a thing that protected them.

### T33 - The camera panel and live narration in the iOS app
**Lane** C · **Skill** swift · **Needs** T20 · **Who** ___

Feed, narration beneath it as it arrives, timestamp, and the `generated` label rendered differently from measured fields.

**Done when** the mock's narration lines animate in and the panel degrades correctly to the shield-closed state.

### T34 - Watch transcribe mode
**Lane** C · **Skill** swift · **Needs** T31 · **Who** ___

Mic open on the wrist, speech to the operator, **no audio ever played back**. Haptics only.

**Done when** the mode is enterable, announced, exits on barge-in, and the watch is provably silent throughout.

*Take this after T32 and T33. It is the weakest of the four watch screens if time runs out.*

## Lane D - Backend, record, courier

### T40 - `caller` driven by the current frame
**Lane** D · **Skill** py · **Needs** T17, T20, T31 · **Blocks** T44 · **Who** ___

Outbound narration from live verified claims, not cached state. Inbound operator questions fanning out as fresh ANS-verified queries.

**Done when** "what are they wearing" returns an answer sourced from a frame taken after the question was asked, and an unverifiable source produces "I don't know" rather than an invention.

### T41 - Video into the replay chain
**Lane** D · **Skill** py · **Needs** T15 · **Blocks** T44 · **Who** ___

Each segment hashed as it closes, hash into the chain, mp4 beside the record.

**Done when** the standalone verifier in the zip export checks segment hashes as well as chain links, and altering one byte of one mp4 fails verification.

### T42 - The replay console plays the video
**Lane** D · **Skill** web · **Needs** T41 · **Who** ___

Scrubber aligned to the claim log, so a detective can see what the system believed at the moment a frame was taken.

**Done when** scrubbing the video moves the claim log with it, and the in-browser chain check still passes.

### T43 - Notice sinks: add the watch, keep the SMS
**Lane** D · **Skill** py · **Needs** T30 · **Who** ___

Watch relay as a `NoticeSink` alongside Twilio. The notice payload gains a still frame and the narration line.

**Done when** all three sinks fire from one detector call, and the SMS carries the narration text rather than a generic string.

### T44 - The police email
**Lane** D · **Skill** py · **Needs** T40, T41 · **Blocks** T50 · **Who** ___

`caller` asks the operator for an address near the end of the call and reads it back. `replay` seals and sends via Resend: video, transcript, claim log with every discard and refusal, chain, and the standalone verifier.

Address recorded as `operator_supplied`, never trusted as authorization. The send itself is an event in the chain.

**Done when** a real test email arrives with attachments intact and the verifier in it runs standalone, **and** a failed send is visible in the chain rather than silent.

**Verify the Resend domain early.** An unverified domain accepts sends and delivers nothing, and the chain will record success.

---

# Phase 2 - The demo

### T50 - The refusal, staged
**Lane** A · **Skill** py · **Needs** T14, T32, T44 · **Who** ___

**This is the submission.** An impostor agent at a lookalike ANSName, running as a real process rather than an in-process test, asking `shutter` to open.

Stage `underpay_valid_sig` specifically: a genuinely valid signature that must still be refused. It is the probe that demonstrates authentication versus authorization to a room, and with a camera shield as the target it lands on a non-technical judge instantly.

**Done when** the impostor runs from a second machine, the shield does not move, the iOS refused state appears, and the refusal is in the sealed record with its reason. Rehearsed three times.

### T51 - Point the judge's verifier at us, live
**Lane** A · **Skill** ops · **Needs** T12 · **Who** ___

`agent.webmesh.ai verify_agent` against our hostnames, on stage. Preparation is entirely card work: `ans/CARD.md`.

**Done when** it passes for every agent, from a laptop on the venue network, twice in a row.

### T52 - Record the fallback video
**Lane** media · **Skill** any · **Needs** T21, T22, T23, T31 · **Who** ___

**Due Saturday night, per the working agreements, and this one is not negotiable.**
The full sequence at the house: someone walks in, the shield opens, the watch buzzes, a human starts the incident, the call runs, the email sends.

**Done when** the file exists, plays from a local disk with no network, and someone who was not there can follow it.

### T53 - Devpost, and the upstream line
**Lane** media · **Skill** any · **Who** ___

State clearly what is RuView's and what is ours. After the pivot we take much less of RuView: the capture path and motion detection only.
Ours: the ANS identity layer, the agent mesh, the shutter grant, the verified-caller path, the compromised-sensor threat model.

**Done when** the page names the boundary explicitly. Judges reward a clearly-scoped modification and punish a fork presented as original work.

### T54 - The honesty slide
**Lane** media · **Skill** any · **Who** ___

Four limits, said out loud before anyone asks: no face recognition against any database, one camera seeing one room, ~1 fps sampling, an authored floor plan.

**Done when** each one has a single sentence that is true and does not sound like an apology.

---

# Phase 3 - Only if the critical path is clear

- **T60** - Full hardware integration run at the house, end to end, three times · hw · needs T21-T24, T50
- **T61** - mTLS at the reverse proxy, and `x-security-note` updated in the same commit · ops · needs T11
- **T62** - DANE for Silver, stapled receipt for Gold · ops · needs T12
- ~~**T63** - MongoDB Atlas behind `HAWKEYE_STORE_BACKEND`, for the stackable track · py~~ **Done differently, and deliberately.**
  The MongoDB Atlas track is served by `HAWKEYE_REPLAY_ARCHIVE=mongodb`, which persists **sealed replay records** - one collection, one document per record, written once when a call ends and read by `/replay` afterwards.
  `HAWKEYE_STORE_BACKEND` stays `memory` and `MongoStore` stays unimplemented on purpose: the store is on the incident path, where motion has to reach a wrist in about three seconds, and there is no room in that for a round trip to Atlas.
  See `hawkeye_backend/replay/archive.py` and the archive section of `docs/swapping-in-real-parts.md`.
  **Verified against the real Atlas cluster on 2026-09-19**: sealed a 32-entry record, confirmed the document in Atlas, killed the hub, restarted, and got the record back with the chain verifying INTACT under the server check, the exported standalone `verify.py`, and the in-browser verifier.
  **One recurring gotcha, not a code problem:** Atlas refuses the TLS handshake before authentication when the client IP is not on the project's Network Access list. Expect to re-add it at the venue, whose egress IP will differ.
- **T64** - Blender hero loop: a shield rotating off a lens with the grant's signature resolving alongside · any

---

# The end-to-end test

Run this with Claude driving, against the full stack with `shutter` on the stub backend and `vision` on a fixture, before any hardware is involved.

It is written as a sequence of assertions rather than a script, because the interesting failures are ordering failures.

1. All seven agents up and answering `/a2a`. Every card fetches and verifies
2. Motion injected into `presence` from the recorded session. `intruder` returns unaccounted within 600ms
3. `master` issues a grant. `shutter` verifies it and the stub angle changes. **Assert the attestation is signed and carries the grant's nonce**
4. `vision` gets the attestation and produces its first description. **Assert it refused to produce one before the attestation arrived**
5. Notice reaches the watch within 3s of step 2, carrying the narration line
6. Nothing has dialled. **Assert no outbound call exists at this point.** This is the ethics claim and it must be a test, not a promise
7. Incident started from the watch. `caller` opens the call
8. Operator question injected. Answer sourced from a frame taken after the question
9. Call ends. Address supplied and read back. Package sends. Chain verifies
10. **Then run the impostor.** Assert the shield does not move, the refusal is signed and sealed, and the iOS refused state renders
11. Alter one byte of one mp4. Assert the verifier fails

Steps 6 and 10 are the two that matter. Everything else is plumbing that either works or does not.
