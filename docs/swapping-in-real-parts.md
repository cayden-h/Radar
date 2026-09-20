# Swapping mocks for real parts

Hawk Eye runs end to end today with no Pi, no router, no agents and no network.
That is deliberate: the demo must never depend on hardware being alive.

This file is the switchboard.
It lists every simulated or mocked thing in the project, where its seam is, what replaces it, how to flip it, and how to tell the flip actually worked.

Read the root `CLAUDE.md` first, especially the honesty rule.

## The three rules this project holds to

1. **One seam per thing, and one place to flip it.**
   If you are hunting for a hardcoded localhost or a stray demo branch, there is one file to look in per layer. Those files are named below.
2. **Simulated inputs are labelled in the data, not in a comment.**
   Every reading carries a `provenance`, and `source_class` / `simulated` are computed from a closed `source` enum rather than trusted from the producer. A simulated reading cannot reach the screen dressed as a measured one.
3. **A half-flipped system must fail loudly.**
   Live mode never falls back to simulated. If the agent mesh is not there, the hub returns `503`, it does not invent an answer.

## Status, after the 2026-09-19 camera pivot

| Layer | State today | Seam | Flip |
|---|---|---|---|
| iOS app | Mock client, in process | `app/ios/HawkEye/Config.swift` | `useMocks = false` |
| watchOS app | Not built | `app/watch/` | n/a |
| Hub backend | Simulated master | `HAWKEYE_MODE` env var | `HAWKEYE_MODE=live` |
| Storage | In memory | `HAWKEYE_STORE_BACKEND` | `mongodb` (not implemented, and should stay memory) |
| **Replay archive** | **Done. MongoDB Atlas, verified against the real cluster 2026-09-19** | `HAWKEYE_REPLAY_ARCHIVE` env var | Already `mongodb` in `.env` |
| Agent mesh | Six written and wired over A2A; `vision` not yet | `HAWKEYE_PEERS` env var | Set it to a `slug=url` list |
| Agent certificates | Raw public keys from published cards, no chain | `discovery._agent_from_card` | Validate `keys[].x5c` once ANS registration exists |
| mTLS between agents | Declared on the cards, not enforced | Reverse proxy | Enable, and update `x-security-note` in the same commit |
| CSI sensing | Brought up, demoted to motion | `sensor/` output contract | n/a |
| **Servo / shield** | Gate built and tested; stub backend by default | `HAWKEYE_SHUTTER_BACKEND` env var | `pigpio` (needs `sudo pigpiod` on the Pi) |
| **Camera** | **Not built. Fixture video file planned** | `vision/source.py` | Swap the file reader for V4L2 |
| **Gemini Live narration** | **Not built** | `vision/narrator.py` | Real API key, real session |
| **Police email** | **Not built** | `replay/courier.py` | Real Resend key |
| ANS identities | `.invalid` placeholders | `HAWKEYE_HUB_ANSNAME`, `HAWKEYE_MASTER_ANSNAME` | Real registered names |
| Voice to 911 | Text only, no audio | Not built | n/a |
| ~~Gas sensor~~ | **Deleted 2026-09-19** | n/a | Gone with the Fire incident type |

One of these is not "not done yet", it is settled design:

- **The operator link never gets ANS.** The far end is a person. This is the architecture, not a gap.

### What the pivot did to this page

It got shorter in the place that mattered.

The gas sensor was the project's only genuinely fabricated input, and it is gone.
**Everything still on the simulated side of this table is unbuilt rather than unbuildable**, and every one of them has a real seam with a real driver on the other side.

That is a materially better thing to say on stage than what came before it.

## iOS app

**Seam:** `app/ios/HawkEye/Config.swift`, the constant `useMocks`.

It is read in exactly one decision site, `AppModel.swift`, which picks an implementation behind the `HubBrowsing` and `HawkEyeClienting` protocols.
Nothing downstream knows which it got, and there is no demo branch inside any view.
Every other mention of `useMocks` in the codebase is a comment.

**With `useMocks = true`** the app fabricates hubs on the Connect screen, moves presences through the house, lands a scripted detection, and runs a scripted two-way 911 call once a human taps.

**Second switch, same file:** `Config.mockScenario` picks which incident the script runs, `.burglary` or `.fire`.
There was a third scenario until 2026-09-19, when that incident type and fall detection were cut. Its choreography is kept and rekeyed onto Fire: the presence it drives now loses its breathing signature rather than going down.
Both are complete, both run off the same sensor loop and the same detection timer, and burglary is the default because it is the demo.
Burglary adds a fourth presence that walks into the living room unconfirmed.
Once respiration is acquired it is a person, and roster plus device association makes it an unexpected one: two registered residents on the roster, both resident phones associated with the network, and **at least one more presence than those devices account for**.

**Phrase it as a surplus, not as arithmetic.** The claim that survives a 1x1 radio is "**at least one presence more than the roster accounts for**", not "three bodies minus two residents". An exact sensed count is not available; a *surplus* is, because it only requires noticing that an additional presence appeared.

The burglary case is also the favourable one for separation: an intruder is moving, and is usually in a different room from the resident. Two people close together merge, and that is the case this rule does not have to survive. Counting limits under `agents/people`.
It then routes room to room across the apartment toward the resident.
Per-scenario timings sit next to the selector; nothing about the scenario leaks into any view.
This switch is mock-only and has no effect when `useMocks = false`, where the hub decides what happens.

**With `useMocks = false`** the identical UI runs against a real hub: `NWBrowser` over `_hawkeye._tcp`, then REST and one websocket.

**To flip:**

1. Set `useMocks = false`.
2. Start the backend somewhere the phone can reach, on the same network.
3. Make sure something actually advertises `_hawkeye._tcp`. See the gap below.

**Verify it flipped:** the Connect screen sits on "Looking for your home" instead of instantly listing "Home" and "Studio". If hubs appear instantly, you are still on mocks.

**The gap that will bite you:** nothing advertises Bonjour yet.
The backend does not register a `_hawkeye._tcp` service, so with `useMocks = false` the Connect screen will wait forever and show no error, because that is what "no hub found" correctly looks like.
Until Bonjour advertisement exists, point `Config.fallbackBaseURL` at the hub directly.

**Push notifications on this side: not implemented, and not the plan.**
`remote-notification` is declared in the Info.plist but **the iOS app** registers nothing with `UNUserNotificationCenter`, and it will not.
A backgrounded or closed phone app is still reached, by SMS rather than by push. See "The unexpected-presence notice" below for the seam and its half-flipped states.
The Info.plist declaration is now misleading on its own and should be removed when someone is next in that file; it costs nothing but it reads as a capability that exists.

**The watch is a different answer and it is not a push either.** `UNUserNotificationCenter` *is* used there, in `app/ios/HawkEyeWatch/Services/NoticeNotifier.swift`, to raise a **local** notification from a notice the phone relayed.
Nothing in this project talks to Apple's push service, and no paid developer account is involved. See "watchOS app" immediately below.

## watchOS app

**Seam:** `app/ios/HawkEyeWatch/WatchConfig.swift`, the constant `useMockLink`.

The mirror of the phone's `useMocks`, and read in exactly one decision site, `WatchModel.init`, which picks an implementation behind the `WatchFeed` protocol.
No view knows which it got.

**With `useMockLink = true`** the watch scripts its own snapshots with no phone and no hub at all: shield closed, a grant at six seconds, the servo clearing the lens, and the camera's first sentence about two seconds later.

It exists because pairing a watch simulator to a phone simulator is fiddly and sometimes simply refuses, and **the demo must never depend on that working** - the same rule the phone's flag exists for.

**With `useMockLink = false`** the identical UI runs on snapshots relayed from the phone over WatchConnectivity. The watch never speaks to the hub in either mode; that is architecture, not a seam.

**To flip:**

1. Set `useMockLink = false`.
2. Pair a watch simulator to a phone simulator, or use a real pair. `xcrun simctl list pairs` must say `active, connected`, with **both devices booted**.
3. Run the phone app and connect it to a hub. Until it does, the watch is correct to say Reconnecting.

**Verify it flipped:** the watch sits on "Connecting to your phone" at launch instead of counting down to a notice on its own. Logs are the certain answer:

```sh
xcrun simctl spawn <udid> log show --last 2m --info --predicate 'subsystem == "ai.hawkeye"'
```

The phone logs `published N bytes` and the watch logs `received N bytes`. A notice carrying its still frame is roughly 8KB; a snapshot without one is a few hundred.

**Half-flipped states to watch for:**

- **The watch says Reconnecting forever while both apps are plainly running.** The phone is up but not connected to a hub, which is the watch being honest rather than broken. Connect the phone first.
- **A paired-but-disconnected simulator pair.** `simctl list pairs` reports `active, disconnected` until both devices are booted, and WatchConnectivity delivers nothing in that state with no error anywhere.
- **`isWatchAppInstalled` reads false** for a watch app side-loaded with `simctl install` rather than installed through the phone's companion. The relay deliberately does not gate on it; gating on it means the phone silently never publishes.

### The still frame in mock mode

**Seam:** `app/ios/HawkEye/Shared/SimulatedCameraFrame.swift`.

Mock mode has to put something where the notice's photograph goes, because a notice with an empty image well does not demonstrate the thing the camera pivot bought.
This draws that something: a dark frame with a camera's burn-in, the room name, and a timestamp.

**It is never passed off as a photograph.** Everything it produces travels with `WatchNotice.simulated` set, and the views draw a `SIMULATED` marker off that flag rather than off a comment.

**It deliberately does not draw a person.** A recognisable synthetic human would be a fabricated record of someone being somewhere, which is the one thing a system that emails police must never manufacture.

**To flip:** nothing to flip here. It is reached only from the two mock feeds, and `agents/vision` supplies the real frame on the live path.

**Verify:** the `SIMULATED` marker is absent from the notice, and the frame's burn-in timestamp advances with real capture time rather than with app launch.

## Hub backend

**Seam:** `app/backend/hawkeye_backend/config.py`. Every field is an env var prefixed `HAWKEYE_`, so `HAWKEYE_MODE=live` sets `mode`.

`MasterClient` is the protocol. `SimulatedMasterClient` scripts the incident in process; `LiveMasterClient` talks to `agents/master`. `HAWKEYE_MODE` chooses, and there is no third path.

**Live mode fails loudly by design.** With no mesh up, `GET /v1/hub`, `GET /v1/state` and `POST /v1/incident` all return `503 agent mesh unavailable` rather than degrading to simulated data. That is correct: a monitoring system that quietly invents interior state is worse than one that admits it is blind.

The settings worth knowing:

| Env var | Default | What it is for |
|---|---|---|
| `HAWKEYE_MODE` | `simulated` | The one switch. `live` needs the agent mesh. |
| `HAWKEYE_MASTER_BASE_URL` | `http://127.0.0.1:8900` | Where `agents/master` listens, live mode only. |
| `HAWKEYE_SIM_SPEED` | `1.0` | Multiplies every scripted delay. `0.25` runs a rehearsal four times faster. |
| `HAWKEYE_SIM_AUTOSTART` | `false` | Start the scripted detection on boot instead of waiting. |
| `HAWKEYE_PORT` | `8787` | Must match what the iOS client resolves to. |
| `HAWKEYE_SITE_ADDRESS` | demo address | What `caller` reads out to the operator. Change this before any live test. |
| `HAWKEYE_STORE_BACKEND` | `memory` | The whole working state. `mongodb` is not implemented and should stay `memory`. |
| `HAWKEYE_REPLAY_ARCHIVE` | `off` | Where a **sealed** record goes. `mongodb` persists it; `off` keeps it in the process. |
| `HAWKEYE_MONGODB_URI` | empty | Used by the archive. Needs `motor`: `pip install -e ".[archive]"`. |

**Storage:** `Store` is a protocol, `InMemoryStore` is real, and `MongoStore` raises `NotImplementedError` rather than silently degrading. `build_store()` is the single swap point.

### The replay archive, which is real

**Seam:** `app/backend/hawkeye_backend/replay/archive.py`. `HAWKEYE_REPLAY_ARCHIVE=mongodb` turns it on.

This is a different question from `HAWKEYE_STORE_BACKEND` and the two are deliberately separate.
The store holds the hub's whole working state and sits on the incident path, where motion has to reach a wrist in about three seconds; there is no room in that budget for a round trip to Atlas.
The archive holds only a **sealed** record, is written exactly once when the 911 call ends, and exists to be read afterwards by the replay console at `/replay`.
So `store_backend=memory` with `replay_archive=mongodb` is the intended configuration rather than a half-finished one.

One collection, `replays`, one document per record, keyed by `incident_id` so re-archiving replaces rather than forks.
The document carries a denormalized summary alongside the record, because the console index draws one line per record and a record holds a few hundred frames.

**Hashes are stored, never recomputed on read.** A round trip that re-serialized a timestamp differently would produce a record that fails its own verifier, which is indistinguishable from tampering. The in-browser verifier on the record page is what proves this end to end.

**It fails soft, loudly.** Every method returns rather than raising: a record is already complete in memory by the time it seals, so losing the archive costs durability and nothing else, and the moment it runs is the moment a 911 call ends. The failure is then reported on `GET /v1/replay` and drawn as a banner on the console, because a configured archive that is silently unreachable looks exactly like a quiet night.

| State | Console banner |
|---|---|
| Not configured | Grey. Records are memory-only and will be lost on restart. |
| Configured, reachable | Green. Names the backend and the stored record count. |
| Configured, unreachable | **Amber.** Names the cause in plain English. |

Rows read back out of storage are badged `ARCHIVED` on the index, because a record written by a process that is gone is not the same claim as one this hub is currently holding.

#### Verified, end to end, against the real cluster

Done on 2026-09-19 against the project's own Atlas cluster, not a local stand-in:

1. Ran an incident to a sealed record, 32 entries.
2. Confirmed the document in Atlas directly: `hawkeye.replays`, `_id: inc-0001`, `schema_version: 1`, summary and full record both present.
3. **Killed the hub process.**
4. Restarted. The console listed the record as `source: archive`, served the full record, and the chain verified `INTACT`.
5. Exported the bundle and ran the shipped standalone `verify.py` against it: `INTACT: 32 entries`.
6. Recomputed the chain in the browser on the record page: `INTACT`.

That last pair is the one that matters. The record survives a restart and still verifies under a verifier that never trusted the server, which is what "the record outlives the process" has to mean to be worth claiming.

#### Two failures that look like a broken cluster and are not

Both were hit during bring-up and both are handled in code now, so neither should recur.

- **`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate.`** A python.org Python on macOS ships no system root certificates. This is a local trust-store problem and says nothing about Atlas. `MongoReplayArchive.client_kwargs()` points the driver at `certifi` so it does not happen; nobody needs to run Apple's `Install Certificates.command`.
- **`TLSV1_ALERT_INTERNAL_ERROR`.** Atlas refuses the TLS handshake outright when the client IP is not on the project's IP Access List, before authentication, so it reads like a certificate problem. It is not one. Add the machine's IP under Network Access in the Atlas console. **This will recur on a new network** - the venue Wi-Fi will have a different egress IP than wherever you tested. The banner names this cause in plain English rather than printing the driver's topology dump.

## The agents

**Written and wired as of 2026-09-19**, with their domain logic, their identities, their cards, the A2A transport between them, and 74 tests. The roster was nine until that date; the merge rationale is in `agents/CLAUDE.md`.

**The seam is `HAWKEYE_PEERS`**, a comma-separated `slug=url` list.

Unset, `LocalMesh` hands observations over in memory and **verifies nothing**. Set, master fetches each peer's published trust card, builds its trust store from the keys in it, issues a fresh challenge per fetch, and verifies every claim before anything reaches its gate.

```sh
python -m agents people --port 8101
HAWKEYE_PEERS=people=http://127.0.0.1:8101 python -m agents master --port 8100
```

**The half-flipped state is the dangerous one**, because an in-process mesh looks exactly like a working system from the app's point of view. It does not quietly pass as one, and that is by construction rather than by discipline: `TrustGate` records `envelope_verified: false` as a *failed check* on every claim, and `caller` refuses to speak anything whose source was not verified, saying so out loud on the call. **If the verification feed ever shows claims as speakable while `LocalMesh` is in place, something has been loosened that should not have been.**

How to tell the flip worked: `caller.opening_report` stops saying "I have no independently verified information about the interior to give you" and starts speaking attributed claims.

Two things that look flipped and are not:

- **Certificates.** The trust store loads the raw public key from `keys[].x`. There is no chain validation, because no certificates exist until `ans/` has a registration. That is Bronze at best, and `discovery._agent_from_card` carries the TODO.
- **mTLS.** Declared on every card as `ansIdentityCert` and explicitly not enforced, which the card says in `x-security-note`. Turning it on is a proxy change; updating that field belongs in the same commit, because a card that overclaims is a signed, published, machine-checkable lie on the surface the judge inspects first.

Keys live in `agents/build/keys/<slug>.pem`, created on first use and gitignored. **The card builder signs each agent's card with that same key**, which is not a detail: the card exists so master can learn the public half, so a card published under a different key makes every claim that agent sends fail verification. That was a real bug on 2026-09-19, caught by running two processes rather than by a test.

Separately, the hub's own flip to the mesh is `HAWKEYE_MODE=live` plus `HAWKEYE_MASTER_BASE_URL`.
Three questions in `master/live.py` are marked `TODO(master)` and need answering first: whether the hub reads a merged state document or fans out, whether push is websocket or SSE or webhook, and whether the hub must present an ANS identity over mTLS to raise an incident.

## CSI sensing

**Not brought up.** This is the largest single risk in the project.

`docs/hardware/bring-up-checklist.md` is the path from unboxed hardware to CSI frames flowing.
`sensor/CLAUDE.md` holds the output contract, the fallback ladder, and the point at which to stop trying.

There is no software seam to flip here, because there is no capture code yet.
When there is, it feeds `agents/people`, which is the only CSI consumer, and `intruder` reads `people` in turn. The hub sees all of it only through `master`.

Two failure modes from the hardware guides are worth repeating, because both report healthy while producing useless data:

- Without the traffic generator, CSI updates only on beacons at roughly 10 Hz, which never resolves a heart rate or a short motion transient.
- With the router and the Pi on the same side of the room, the capture goes flat and looks exactly like a failed firmware patch.

## The shield, which is built, and the camera, which is not

**`shutter` is built and its gate is tested.** The grant, the nonce, all seven refusals, the signed refusal
observation and the attestation all run against a stub GPIO backend that records the angle it was told to
move to. `cd agents && python -m pytest tests/test_shutter.py -q` proves the whole thing on a laptop with no
hardware present, which is the point: the gate is what is being judged, and the servo is what makes it visible.

Flipping it is one environment variable: `HAWKEYE_SHUTTER_BACKEND=pigpio`, `sudo pigpiod` running, and the
calibrated pulse widths from `docs/hardware/servo-sg92r.md`. Nothing above the backend changes.

**It does not fall back.** Asking for `pigpio` on a machine with no daemon raises rather than quietly
returning the stub, because a shutter that silently became a number would report `open` with the lens covered,
which is the one failure this agent exists to prevent.

**How to tell the flip worked:** the position claim's `provenance.source` reads `servo-gpio` rather than
`servo-stub`, and `provenance.simulated` goes false. That is computed from the backend rather than asserted by
it, so a stub-backed shutter cannot present as a pin-backed one even by mistake.

**The half-flipped state that looks like something else:** the servo moves and the shield does not.
The SG92R is open-loop, so a jammed, slipped or mis-glued shield attests `open` exactly as a working one does -
`commanded_angle` is the angle we *sent*, never the angle the shield reached, and the attestation says
`position_basis: commanded` for precisely this reason. **The only thing that catches it is the frame itself
being dark**, which is the black-frame check in the camera guide and is T23 on the board. Re-run it after the
mount is touched for the last time. A shield leaving a crescent of lens visible turns the project's central
privacy claim into a prop, and nobody would notice.

**The refusal, in the app:** `Config.mockShutterRefuses` makes `master`'s grant fail verification, so the shield stays closed and the apps show the fourth state.
It is a mock-only switch and has no effect when `useMocks = false`, where `shutter` decides for itself.
**The refusal path matters more than the happy path**, so this switch is worth exercising before every rehearsal rather than on the night.

**Verify it flipped:** the watch's Idle screen reads "Shield held closed" with the refusal in plain English under it, and **the notice arrives with no picture at all**, saying so. A notice that still carries a frame while this is on means the frame was cached from an earlier run.

**`vision`** is developed against a fixture video file played at real time.
The claim shape, the shutter gate, the luminance guard and the segment writer are all exercised without a camera.
Flipping it is one class: V4L2 instead of the file reader.

**How to tell the flip worked:** the segment files have a growing timestamp and a non-trivial file size, and the narration changes when someone walks in front of the lens. A fixture that loops produces narration that repeats on a cycle, which is the half-flipped state to watch for.

**The Gemini Live session** is the one part with an external dependency, and it is deliberately the least load-bearing.
With no key, `vision` still records, and claims go to `Unknown(reason="narrator_unreachable")`.
The half-flipped state to watch for is a key that authenticates but has no quota, which returns errors that look like network failures.

## The gas sensor, which was deleted

Kept here as history, because it was this file's headline entry for a day and someone will look for it.

`agents/master` read a simulated carbon monoxide sensor. No gas sensor was ever purchased. The reading carried `provenance.source = "demo-trigger"`, and the iOS app rendered a `SIM` chip next to the number so a simulated reading could not reach the screen dressed as a measured one.

**It was deleted in the 2026-09-19 pivot**, along with `agents/master/environment.py` and the Fire incident type it existed to serve.

The reason it is worth a paragraph rather than a deletion: it was the only input in the system that **skipped the verification gate**, because `master` was both its producer and its consumer.
Removing it means every input `master` now acts on arrived through the gate from an independently registered agent. That is a strictly better trust story and it costs one sentence to tell.

**Never claim a sensing capability the physics does not support.** CSI cannot measure gas composition. Oxygen absorption is a roughly 60 GHz phenomenon and the BCM43455c0 is a 2.4/5 GHz radio.

## The unexpected-presence notice

**Nothing about the notice itself is simulated.** The detector in
`hawkeye_backend/notices/detector.py` runs on whatever `InteriorState` it is given, with no branch
for mode: on the mock path it fires off `ruview-sim` frames, on the live path it fires off
`nexmon-csi` frames, and it cannot tell which one it is looking at.

**What is not implemented: APNs.** "The phone buzzes with the app closed" is true today because of
Twilio, not because of push. Say which, on stage, before anyone asks. `NoticeSink` is an interface
with one method, so adding APNs later is a driver behind it and changes nothing above the seam.

**To flip Twilio on:** set `HAWKEYE_TWILIO_ACCOUNT_SID`, `HAWKEYE_TWILIO_AUTH_TOKEN`,
`HAWKEYE_TWILIO_FROM_NUMBER`, and `HAWKEYE_TWILIO_TO_NUMBER`.

**Verify it flipped:** the startup log line reads `notices: twilio sms sink enabled`, and a fired
notice logs `twilio sent ntc-p4` rather than staying silent.

**The half-flipped state that looks like something else:** three of the four Twilio variables set
reads as unconfigured. The startup line is `notices: twilio not configured, in-app banner only`, and
the in-app banner still appears, so the failure looks like Twilio being slow rather than Twilio being
off. Check the startup line, not the banner.

**A second half-flipped state worth naming:** a Twilio trial account only sends to numbers verified
in its console, and US A2P 10DLC enforcement can begin refusing trial sends without warning. A
refused send is logged and swallowed by design, the same as any other sink failure, so the in-app
banner appears and no text arrives. The log line is `twilio refused ntc-p4: status=... code=...`.

**The one that will surprise you on the hub path, and is owned elsewhere:** in simulated mode the
notice arrives *after* the resident taps Burglary, not before it.

That inverts the product story, where the notice is what informs a person so they can decide
whether to call. The cause is not in the notice path: `SimulatedMasterClient` only creates the
`expected: false` presence inside `_run_typed_call`, which runs after `assert_human_released`, so
until a human taps there is no unaccounted-for person for the detector to see. It detects the
presence that exists, when it exists, which is correct behaviour on an incorrect script.

The iOS mock sequences it the right way round: `Config.mockIntruderIdentifiedAfter` is 5s and
`mockDetectionAfter` is 14s, both well before any tap. So **the app demo tells the true story and
the hub demo does not**, and the two disagree today.

Fixing the hub scenario belongs to whoever owns `master/scenario.py` and `master/simulated.py` and
is deliberately not done here. Until it lands, demo the notice off the app's mock path, and do not
narrate the hub path as "the system told the resident, and then they decided".

## The household roster

**What is simulated: the association table.** No router integration exists, so `associated_devices`
on a state frame comes from `master/simulated.py` with `Provenance` saying `ruview-sim` and a detail
of "association table, simulated". Swapping in the real table is a producer change behind a field
that already exists, and nothing above it moves.

**What is real:** the roster itself, the hashing, the matching, the approval, and the record that a
human made the decision. A roster entry carries `USER_INPUT` provenance, which computes to
`SourceClass.HUMAN`, so `caller` can say "the resident says this person is expected" and cannot say
"the system verified this person".

**How to tell which you are looking at:** the Household list shows a device fingerprint per member.
The simulated ones come from the fixed pair in `master/simulated.py`. Real ones will not.

**The half-flipped state that looks like something else:** a member remembered with no device is
legal and is not a bug. They were named by a resident and carry no phone the system can see, so they
will never be auto-recognised, and the Household list says "no device, will not be recognised
automatically" for exactly that reason. If every member reads that way, the association table is not
arriving at all, which is a different problem: check `associated_devices` on a state frame.

**The one that will look like the feature is broken:** remembering a visitor changes nothing until
the devices present actually account for the people present. Two residents remembered, both phones
associated, and a third presence in the house still raises a notice, because the surplus is one.
That is the feature working, not failing.

## ANS identity

Every ANSName in the codebase today ends in `.invalid`, which is reserved by RFC 2606 and can therefore never be mistaken for a real registration.

`HAWKEYE_HUB_ANSNAME` and `HAWKEYE_MASTER_ANSNAME` carry the hub side. The five agent names live in `agents/core/identity.py`, with a copy still in `master/scenario.py` that should be deleted once the hub imports from it.

**Before these become real, two questions need answering**, both marked `TODO(ans)` in the code:

1. Is the hub itself ANS-registered, or does it quote `master`'s identity? The app to hub hop is a human-facing hop, so the working assumption is that it quotes rather than holds its own anchor.
2. Is the name shape `people.hawkeye.example` or `hawkeye.example/agents/people`? Check `agent.webmesh.ai/.well-known/agents-index.json`.

**A thing the app must never start claiming:** connecting to a hub checks that `/v1/hub` reports the same ANSName it advertised over Bonjour. That is a consistency check, not ANS verification. ANS verification lives in the agent mesh, behind `master`. The UI says so today and must keep saying so.

## Voice to the 911 operator

**Not built.** The transcript is text on both sides; nothing is spoken and no call is placed.

ElevenLabs is the intended voice and the sponsor track. When it lands it sits behind `agents/caller`, which is the only agent that acts on the outside world.

**Do not point this at a real PSAP.** Ever. Test against a phone you own.

## Half-flipped states, and what they look like

These are the combinations that waste an evening, because most of them look like something else.

| You flipped | You forgot | What you see |
|---|---|---|
| iOS to live | Nothing advertises Bonjour | "Looking for your home", forever, no error |
| iOS to live | Backend on a different network | Same as above. Check both are on the router's subnet. |
| iOS to live | `HAWKEYE_PORT` changed | Hub found, then "That hub did not give a usable address." |
| Backend to live | No agent mesh | Every endpoint `503`. This is correct behaviour, not a bug. |
| Backend to live | Expecting `/v1/demo/run` | `404`. There is no way to fake an emergency against a live mesh, deliberately. |
| Store to mongodb | It is not implemented | `NotImplementedError` at boot, on purpose, rather than silent data loss. |
| Nothing | Pi and router on one table | Flat capture that looks exactly like a failed firmware patch. |
| Shutter to real GPIO | Servo on the Pi's 5V rail | The Pi browns out when the shield moves. Presents as the camera dying, or the CSI capture dying, or an unreachable Pi. Never mentions the servo. |
| Shutter to real GPIO | Pulse width not stopped after the move | The shield buzzes and twitches at rest, on camera, in the footage. |
| Shutter to real GPIO | Closed position not recalibrated after the mount was touched | **The worst one.** The shield partly covers, frames are not black, and the privacy claim is quietly false while everything reports healthy. Check with a live frame, not by eye. |
| Vision to real camera | Fixture file still configured | Narration repeats on a fixed cycle. Looks like a model quirk, is a config bug. |
| Vision to real camera | Auto-exposure left on | Narration contradicts itself one second apart on a live call. |
| Vision to real camera | Two processes opening `/dev/video0` | "Device busy", usually the first time the recorder and narrator are run separately. |
| Gemini key set | No quota on the key | Errors that look exactly like network failures. `narrator_unreachable` either way, so recording continues, which is the design working. |
| Resend key set | Domain not verified | Sends accepted, nothing delivered. The chain records a successful send. **Verify the domain and send one real test email before the demo.** |

## Which mode for which demo

**Laptop only, no hardware.** iOS `useMocks = true`. Nothing else running. This is the fallback that must work on Sunday morning regardless of what else broke.

**Hub running, no agents.** iOS `useMocks = false`, backend `HAWKEYE_MODE=simulated`, phone and hub on the same network. This exercises the real transport, the real Codable types and the real websocket against a scripted incident.

**Full stack, no hardware.** Everything above plus `HAWKEYE_MODE=live` and the agent mesh up, with `shutter` on its stub GPIO backend and `vision` on a fixture video file. **This is the mode the live judging demo should run in if the hardware is not cooperating**, and it exercises every ANS path including the refusal.

**Full stack with hardware.** The above, plus the servo on `pigpio` and the camera on V4L2. This is what the house shoot films and what the judging table runs if the bring-up holds.

Per the working agreements in the root `CLAUDE.md`: anything that must be demoed live needs a recorded fallback by Saturday night.

## There is no night vision, and there is no path to one

The camera is a Logitech Brio 101, USB `046d:094d`.
It has no IR sensor, unlike the original Brio 4K which carried one for Windows Hello, and no IR illuminator is owned.
Root `CLAUDE.md` states no further hardware is being purchased.

So there is no infrared capability to swap in, and no seam for one, because the missing part is a physical sensor rather than a mocked implementation.
X-ray imaging is not a capability any camera has and is not a thing to look for a seam for.

What exists instead is two separate, real things, and neither is ever called night vision:

- **Low-light capture mode**, in `vision/hawkeye_vision/lighting.py` and `profiles.py`.
  Measured mean luminance selects one of three states, and the state travels in the claim as `vision.lighting`.
  In `low` the frame is greyscaled and CLAHE contrast-stretched before detection and the confidence floor is raised.
  Below `dark_threshold` the system stops describing the room rather than describing a dark one.
- **Client-side viewing enhancement**, in the iOS app and the replay console, still to be built.
  CLAHE, gamma and temporal denoise applied at display time so a resident can see the room.
  It never touches the recorded segments, which are hashed and emailed to a police department.

**How to tell the flip worked:** run `python3 -m hawkeye_vision` and turn the room lights off.
The status line must move `day` to `low` to `too_dark`, and must not flicker between them on the way.
Each change needs the dwell to elapse, roughly three seconds at 15fps, so it is deliberately not instant.
A change the signal holds for less than the dwell is skipped entirely, which is why a fast fade can go `day` straight to `too_dark` without ever reporting `low`.

**The half-flipped state that looks like something else:** a shield still covering the lens produces the same black frame as an unlit room.
Both correctly report `too_dark`, and that is deliberate: `shutter` is open-loop and attests the angle it commanded rather than the angle the shield reached, so the luminance guard is the only thing that catches a jammed shield.
Distinguishing the two cases means checking whether a shutter attestation is held, not looking at the picture.

## Which camera index is the Brio, on the Mac

Covered in full in `docs/hardware/logitech-camera.md`, and repeated here because it is a swap-time trap.
Every AVFoundation index opens and reports the same 1280x720, so an index that works is not evidence it is the right camera.
On the MacBook, index 0 is the Brio, 1 is an iPhone over Continuity Camera, and 2 is the built-in FaceTime.
The Pi does not have this problem.

## The detector, and what happens without it

`vision/hawkeye_vision/yolo_tracker.py` holds the real YOLO11m plus BoT-SORT tracker; `hawkeye_vision.track.StubTracker` is the scripted stand-in every test runs against.
`build_tracker` is the single place that chooses, and it never raises: missing weights, no torch, or no MPS all yield an `UnavailableTracker` that reports `available = False` and why.

**How to tell the flip worked:** the startup log says nothing when the real tracker loads, and logs `running without measured counts` when it did not.
Boxes and a non-zero `people` count in the preview are the positive evidence.

**The half-flipped state:** `yolo11m.pt` is roughly 40MB, gitignored, and downloaded on first use.
A machine that has never run the tracker and has no network gets an `UnavailableTracker` and carries on quietly, which looks exactly like an empty room.
Pre-fetch the weights before the demo.
