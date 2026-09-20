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
T01 delete  ─►  T10 presence  ─►  T13 intruder  ─►  T14 shutter grant  ─►  T15b motion gate  ─►  T16 vision claims
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

### ~~T11 - Deploy the five existing agents to public hostnames~~ **Done 2026-09-20.**
**Lane** A · **Skill** ops · **Blocks** T12, T50

All seven are live on Vultr at `66.135.27.67`, one `hawkeye-agent@<slug>` process each behind Caddy, Let's Encrypt terminating at the edge. `curl https://master.batradar.club/.well-known/agent-card.json` works from anywhere.

The mesh is wired over the public hostnames rather than localhost: each agent builds its trust store from its peers' published trust cards, and `master` admits six verified claims per tick. **`docs/deploy.md` is the runbook**, including why the agents must be restarted one at a time.

### ~~T12 - Register the domain and the agents with ANS~~ **Done 2026-09-20.**
**Lane** A · **Skill** ops · **Needs** T11 · **Blocks** T50

**All seven are ANS ACTIVE**, certificates issued, transparency-log badges held in `agents/.ans/<slug>/`. DNSSEC is on.

`scripts/register-agents.sh` still registers a new agent from the roster. `scripts/finish-registration.sh` is the other half - it takes one already registered and stuck at `PENDING_DNS` through to ACTIVE, and re-runs safely.

```sh
cd agents && scripts/finish-registration.sh --check
```

**Four records per agent, not two.** The blocker was never only the TXT records:

| Record | Note |
|---|---|
| `_ans.<host>` TXT | |
| `_ans-badge.<host>` TXT | |
| `_443._tcp.<host>` TLSA | `3 0 1` over the certificate **the RA issued**, not the one we serve |
| `<host>` HTTPS (TYPE65) | `1 . alpn=h2`. **Required**, and easy to miss |

The HTTPS record is the trap. `master`, `intruder`, `caller` and `replay` are ACTIVE with no HTTPS record at all, which made it look optional; `verify-dns` rejected all three new agents until it was added. Do not reason from what the older four happen to have.

Three more things that cost time, recorded so they do not again:

- **The Porkbun freeze is real and avoidable.** Its bulk page does hang its own renderer, and so does the delete confirm in the per-domain drawer. The per-record **edit** and **add** forms in that drawer work fine. Everything here went in through those.
- **`verify-acme` is not re-runnable.** All three had already passed at registration, and the RA answers `Validation status is VERIFIED and cannot be retried`. That is success, not failure.
- **Check DNS against the zone's own nameserver.** A resolver asked for a name before it was published caches NXDOMAIN for the zone's 1800s negative TTL and keeps reporting a live record missing for half an hour. Both scripts query `$(dig +short NS batradar.club)` directly.

**DANE is not achievable while staying registered**, and that is settled rather than outstanding. The RA requires TLSA to be its own `3 0 1` over a certificate we do not serve, and refuses any other record - including a correct `3 1 1` published alongside it, which was tested rather than assumed. We are Bronze and we say so. Full reasoning in `docs/deploy.md` and the header of `agents/scripts/tlsa.sh`.

**Still open:** `agent.webmesh.ai verify_agent` has not been pointed at us yet. That was this task's original done-when and it is now the first half of T50. Also `transparencyReceipt` is still `null` in all seven trust cards, which is the remaining Gold blocker.

`people` stays registered and unserved. It is the pre-pivot name for `presence`. Its `_ans` and TLSA records still resolve and point at a host that no longer answers; both should be deleted.

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
**Lane** A · **Skill** py · **Needs** T02 · **Blocks** T16 · **Who** Cayden · **DONE 2026-09-19**

Frame source reading an mp4 at real time, the luminance guard, and the segment writer producing closed, hashable 10s files.

**Delivered more than the line asked for.** The task assumed a fixture file; the package also drives the live Logitech Brio, and it grew a measured person tracker, because `people_visible` as a generated number was too weak to corroborate anything.
Spec in `docs/superpowers/specs/2026-09-19-vision-tracking-design.md`, plan in `docs/superpowers/plans/2026-09-19-vision-camera-and-tracking.md`. 104 tests.

Three findings worth carrying forward:

- **`dark_threshold` was 25 and is now 10.** Measured over 675 frames of real footage: YOLO11m found people in 100% of frames from luma 10 upward, at *higher* mean confidence (0.81) than above luma 40 (0.78). The old floor discarded 72 frames in which four people were plainly visible. Recalibrate at the venue anyway.
- **On the Mac, camera index 0 is the Brio.** Every index opens and reports 1280x720, so "it works" proves nothing. `docs/hardware/logitech-camera.md` has the identification procedure.
- **There is no night vision and there cannot be.** The Brio 101 has no IR sensor and no illuminator is owned. See the limits in `vision/CLAUDE.md`.

**Still open here:** track identities churn in the dark. 14 identities persisted past 20 frames for at most 5 people. Some of that is correct, since `track_buffer` is 2 seconds and we claim no re-identification, but ReID on `model: auto` is weak at luma 12. Expect new ids for anyone who leaves frame.

### T15b - The motion-gated shutter
**Lane** A · **Skill** py · **Needs** T13, T14, T15 · **Blocks** T16, T20 · **Who** Cayden · **DONE 2026-09-20**

Motion alone opens the lens; `vision.occupancy` closes it again. Spec in `docs/superpowers/specs/2026-09-20-motion-gated-shutter-design.md`, plan in `docs/superpowers/plans/2026-09-20-motion-gated-shutter.md`.

Delivered: `hawkeye_vision.occupancy`, `agents/agents/vision/` behind an ANS identity, `master/episode.py` (the refractory lock that keeps the SG92R from browning out the Pi), `master/shutter_client.py` (master had never issued a grant - `sign_grant` was called only from tests), `agents/people` renamed to `agents/presence` with `respiration.py` deleted, and `intruder` rewritten to read a camera against a router.

**Found and fixed on the way:** the `close` grant path had shipped with no test at all and attested `position="close"`, the action verb, where `Shutter.position` reports `"closed"`. They disagreed, and both land in the sealed record.

**Still open here, deliberately:**

- **The real `OccupancySource` adapter.** `VisionAgent` takes a Protocol and only the test fake implements it. The adapter that pulls a `Frame`, calls `Tracker.update`, feeds `TrackBook` and calls `verdict()` belongs with the capture loop and needs a camera to exercise honestly. Everything shipped runs on `StubTracker`.
- **`LocalShutterClient` is in-process.** It signs and verifies real grants against the real gate, but an in-process call verifies no transport. Same warning `LocalMesh` carries, and it must not survive into the demo.

### T16 - `vision` claims, gated on the shutter attestation
**Lane** A · **Skill** py · **Needs** T14, T15 · **Blocks** T20 · **Who** ___ · **Unblocked: T14 and T15 are both done**

The measured inputs are ready and named: `TrackBook.people_visible` and `.active` feed `vision.people_visible` and `vision.tracks`; `LightingClassifier.mode` and `mean_luminance` feed `vision.lighting` and `vision.mean_luminance`; `LightingMode.TOO_DARK` is the `frame_too_dark` trigger; `Tracker.available` and `.reason` are the `tracker_unavailable` trigger.
This task will also need a `Source.GEMINI_LIVE` and a new `SourceClass.GENERATED` in `hawkeye_backend/models/common.py`, plus the matching case in `app/ios/HawkEye/Models/Provenance.swift` or the app will fail to decode the claim.

No claim without a current verified attestation. `Unknown(reason="shield_closed")` otherwise.

**Done when** three tests pass: absent attestation, stale attestation, valid attestation, and only the third produces a description.

**The occupancy half landed 2026-09-20**, on `t20-hub-integration`. `hawkeye_vision/live_occupancy.py` is
the real `OccupancySource` T15b left open: it holds a capture thread, pulls frames from the hub's relay,
runs the tracker, and answers `VisionAgent` with a measured verdict. Seven tests, and the ones that matter
are the three ways it must refuse to answer - nothing arrived yet, the verdict aged out, the source died -
all of which come back `tracker_unavailable` rather than `no_person`, because `master` closes a verified
grant on `no_person` and a blind camera reporting an empty room fires this system's privacy mechanism at
random. `HAWKEYE_VISION_SOURCE=synthetic` is now the opt-in and the real path is the default; failing to
build the real one reports blindness rather than falling back to a script.

The attestation gate and `vision.description` are still open.

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

### ~~T20 - `master` wiring: grant issuance and the hub-facing surface~~ **Done 2026-09-20.**
**Lane** A · **Skill** py · **Blocks** T30, T40 · **Branch** `t20-hub-integration`

`HAWKEYE_MODE=live` had nowhere to point. `LiveMasterClient` had posted to `/v1/state`, `/v1/sensor`,
`/v1/agents`, `/v1/incident`, `/v1/stream` and `/v1/shutter/grant` since it was written, against a
`TODO(master)` block calling those paths its own proposal; master served none of them. Every surface
therefore ran off the scripted incident in `master/simulated.py` no matter what was on the table.

Delivered:

- **`agents/master/hub_api.py`** - the agreement that TODO block was waiting for. Composes master's
  admitted claims into `InteriorState`, pushes state plus every fresh verification verdict - acceptances
  and discards alike - down `WS /v1/stream`, and signs grants over the shutter's own nonce
- **`A2AShutterClient`** - master had no way to reach the real shutter over the wire. `LocalShutterClient`
  signed real grants against the real gate in-process, which verifies a signature and nothing about a
  transport. `HAWKEYE_PEERS` now turns the shutter hop on the same way it turns the mesh on, and a
  missing shutter means no grant rather than a silent in-process substitute
- **`build_app` hooks** - `routers`, `on_start`, `on_stop`, used by exactly one agent. What differs
  between agents should be `tick`, and a hook the other six pass nothing to keeps that visible
- **`scripts/up.sh`** - seven processes in dependency order, with a port wait rather than a guessed
  sleep. The failure it exists for is master starting before shutter can serve its trust card, which
  leaves master refusing every grant as `unregistered_issuer`, correctly, and looking like a gate bug

**Verified end to end**, not merely tested: the full mesh up, the Brio at 7.6 fps across the edge link,
`vision` pulling real frames off the hub's relay and running YOLO11m on them, and master composing a
`person_present` verdict for the living room into the state document all three surfaces read.

**What it left open.** `presence` still runs on RuView's synthetic generator and says so in every claim
(`source: ruview-sim`): `sensor/` holds no capture code, and the Pi's radio path and its camera path want
the WiFi interface in two different modes. The RSSI detector in `wifi-rssi-motion-template/` is the real
motion source when someone wires it in - it is a live process with a real signal today and nothing reads it.

### ~~T25 - The edge link: camera and servo on the Pi, compute on the Mac~~ **Done 2026-09-20.**
**Lane** A/B · **Skill** py · **Blocks** T33, T60 · **Branch** `t20-hub-integration`

New task, added and completed the same day, because nothing connected the four finished parts to a screen.

`WS /v1/edge/link`: the Pi dials the Mac, JPEG frames go up, shutter grants come down.
`python -m hawkeye_vision.edge` on the Pi captures and pushes and runs no model.
`RelayFrameSource` lets `vision/` read those frames on the Mac, so YOLO, Gemini and the recorder run unchanged.
Frames reach the three surfaces at three rates: MJPEG at `/v1/camera/live`, a 1 Hz thumbnail on the event stream for the watch, a still on demand.

Four cross-app controls, all landing on `HubRuntime.emit()` so every surface sees every outcome: start incident, add context, shutter open/close, dismiss notice.
`app/web/live/` is the third surface and the proof the backend is shared.

**Verified end to end**, not merely tested: 194 frames across the link, MJPEG at 9 fps in a browser, the shield to 90 and back to 0 against the real `agents/shutter` that discovered `master`'s trust card from `master.batradar.club`, and the same grant refused as `unregistered_issuer` by a shutter with an empty trust store.
Killing the edge flips `camera.live` false within four seconds rather than serving a frozen frame as current.

**What it left for T20:** `master` still does not expose a grant endpoint, so in simulated mode the hub signs with `master`'s own key and says so at startup. `LiveMasterClient.issue_shutter_grant` already posts to `/v1/shutter/grant` and needs the other end.

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

**The hub's half is built as of 2026-09-20.** `app/backend/hawkeye_backend/replay/courier.py`: `NullCourier` by default, `ResendCourier` behind `HAWKEYE_COURIER=resend`, sending the export bundle - record, readable chain, standalone verifier, README - as one zip attachment. Automatic when a record seals, plus `POST /v1/incident/{id}/courier` for the operator-supplied address and for retrying a failed send. The courier section of `app/backend/README.md` has the whole design.

Address provenance is carried: `operator_supplied` off the request, `configured` off `HAWKEYE_COURIER_TO`. Neither is authorization for anything.

The send is an event in the chain. `ReplaySession.append_courier_receipt` is the one thing allowed to append past a seal, and it adds rather than edits: the emailed copy is a byte-exact prefix of the archived one and both verify under the same unchanged `verify.py`. A failed send chains as loudly as a successful one; retries accumulate until one succeeds.

**Still to do, and it is the half that closes the task:**

1. **Send one real email and open it.** Nothing has been sent for real. 18 tests cover the path against a mock transport, which proves the shape and not the delivery.
2. **`caller` asking the operator for the address and reading it back.** That is T40 territory and nothing here implements it; the endpoint just accepts an address once somebody has it.
3. **Video in the bundle.** T41. The export is four text members today.

**Done when** a real test email arrives with attachments intact and the verifier in it runs standalone, **and** a failed send is visible in the chain rather than silent.

**Verify the Resend domain early.** An unverified domain accepts sends and delivers nothing, and the chain will record success. `cayden.tech` is verified on the project account as of 2026-09-20 and is the default From domain - but a verified domain is not a tested inbox.

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
