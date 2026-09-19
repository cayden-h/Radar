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

## Status, as of 2026-09-19

| Layer | State today | Seam | Flip |
|---|---|---|---|
| iOS app | Mock client, in process | `app/ios/HawkEye/Config.swift` | `useMocks = false` |
| Hub backend | Simulated master | `HAWKEYE_MODE` env var | `HAWKEYE_MODE=live` |
| Storage | In memory | `HAWKEYE_STORE_BACKEND` | `mongodb` (not implemented yet) |
| Nine agents | Not written | n/a | n/a |
| CSI sensing | Not brought up | n/a | n/a |
| Gas sensor | Simulated, permanently | `provenance.source` | Stays `demo-trigger` |
| ANS identities | `.invalid` placeholders | `HAWKEYE_HUB_ANSNAME`, `HAWKEYE_MASTER_ANSNAME` | Real registered names |
| Voice to 911 | Text only, no audio | Not built | n/a |

Two of these are not "not done yet", they are settled design:

- **The gas sensor stays simulated.** No gas sensor was purchased and none will be. The interface is real and a driver drops in behind it. See the honesty rule.
- **The operator link never gets ANS.** The far end is a person. This is the architecture, not a gap.

## iOS app

**Seam:** `app/ios/HawkEye/Config.swift`, the constant `useMocks`.

It is read in exactly one decision site, `AppModel.swift`, which picks an implementation behind the `HubBrowsing` and `HawkEyeClienting` protocols.
Nothing downstream knows which it got, and there is no demo branch inside any view.
Every other mention of `useMocks` in the codebase is a comment.

**With `useMocks = true`** the app fabricates hubs on the Connect screen, moves presences through the house, lands a scripted detection, and runs a scripted two-way 911 call once a human taps.

**Second switch, same file:** `Config.mockScenario` picks which incident the script runs, `.burglary` or `.faint`.
Both are complete, both run off the same sensor loop and the same detection timer, and burglary is the default because it is the demo.
Burglary adds a fourth presence that walks into the living room unconfirmed.
Once respiration is acquired it is a person, and roster plus device association makes it an unexpected one: two registered residents on the roster, both resident phones associated with the network, and **at least one more presence than those devices account for**.

**Phrase it as a surplus, not as arithmetic.** The claim that survives a 1x1 radio is "**at least one presence more than the roster accounts for**", not "three bodies minus two residents". An exact sensed count is not available; a *surplus* is, because it only requires noticing that an additional presence appeared.

The burglary case is also the favourable one for separation: an intruder is moving, and is usually in a different room from the resident. Two people close together merge, and that is the case this rule does not have to survive. Counting limits under `agents/occupancy`.
It then routes room to room across the apartment toward the resident.
Per-scenario timings sit next to the selector; nothing about the scenario leaks into any view.
This switch is mock-only and has no effect when `useMocks = false`, where the hub decides what happens.

**With `useMocks = false`** the identical UI runs against a real hub: `NWBrowser` over `_hawkeye._tcp`, then REST and one websocket.

**To flip:**

1. Set `useMocks = false`.
2. Start the backend somewhere the phone can reach, on the same network.
3. Make sure something actually advertises `_hawkeye._tcp`. See the gap below.

**Verify it flipped:** the Connect screen sits on "Looking for your home" instead of instantly listing "Home" and "Garage". If hubs appear instantly, you are still on mocks.

**The gap that will bite you:** nothing advertises Bonjour yet.
The backend does not register a `_hawkeye._tcp` service, so with `useMocks = false` the Connect screen will wait forever and show no error, because that is what "no hub found" correctly looks like.
Until Bonjour advertisement exists, point `Config.fallbackBaseURL` at the hub directly.

**Push notifications on this side: not implemented, and not the plan.**
`remote-notification` is declared in the Info.plist but nothing registers with `UNUserNotificationCenter`, and nothing will.
A backgrounded or closed app is still reached, by SMS rather than by push. See "The unexpected-presence notice" below for the seam and its half-flipped states.
The Info.plist declaration is now misleading on its own and should be removed when someone is next in that file; it costs nothing but it reads as a capability that exists.

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
| `HAWKEYE_STORE_BACKEND` | `memory` | `mongodb` is the sponsor track and is not implemented. |

**Storage:** `Store` is a protocol, `InMemoryStore` is real, and `MongoStore` raises `NotImplementedError` rather than silently degrading. `build_store()` is the single swap point.

## The nine agents

**Not written.** `agents/CLAUDE.md` has the contracts; there is no code.

Until they exist, `SimulatedMasterClient` stands in for all nine, including the verification decisions and the discarded claim.

When they land, the flip is `HAWKEYE_MODE=live` plus `HAWKEYE_MASTER_BASE_URL`.
Three questions in `master/live.py` are marked `TODO(master)` and need answering first: whether the hub reads a merged state document or fans out, whether push is websocket or SSE or webhook, and whether the hub must present an ANS identity over mTLS to raise an incident.

## CSI sensing

**Not brought up.** This is the largest single risk in the project.

`docs/hardware/bring-up-checklist.md` is the path from unboxed hardware to CSI frames flowing.
`sensor/CLAUDE.md` holds the output contract, the fallback ladder, and the point at which to stop trying.

There is no software seam to flip here, because there is no capture code yet.
When there is, it feeds `agents/occupancy`, `intruder`, `biometrics` and `collapse`, and the hub sees it only through `master`.

Two failure modes from the hardware guides are worth repeating, because both report healthy while producing useless data:

- Without the traffic generator, CSI updates only on beacons at roughly 10 Hz, which never resolves a heart rate or a fall transient.
- With the router and the Pi on the same side of the room, the capture goes flat and looks exactly like a failed firmware patch.

## The gas sensor, which stays simulated

`agents/environment` is the clear case of the honesty rule, and it is not a gap to close.

No gas sensor was purchased and none will be. The reading is simulated and says so in the data: `provenance.source` is the literal string `demo-trigger`, and `source_class` and `simulated` are computed from it rather than set by the producer.
The iOS app reads that field and renders a `SIM` chip next to the CO number, so a simulated reading cannot reach the screen dressed as a measured one.

Adding a real sensor is a driver behind an interface that already exists, and nothing above it changes.

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

## ANS identity

Every ANSName in the codebase today ends in `.invalid`, which is reserved by RFC 2606 and can therefore never be mistaken for a real registration.

`HAWKEYE_HUB_ANSNAME` and `HAWKEYE_MASTER_ANSNAME` carry the hub side. The nine agent names live in `master/scenario.py`.

**Before these become real, two questions need answering**, both marked `TODO(ans)` in the code:

1. Is the hub itself ANS-registered, or does it quote `master`'s identity? The app to hub hop is a human-facing hop, so the working assumption is that it quotes rather than holds its own anchor.
2. Is the name shape `collapse.hawkeye.example` or `hawkeye.example/agents/collapse`? Check `agent.webmesh.ai/.well-known/agents-index.json`.

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

## Which mode for which demo

**Laptop only, no hardware.** iOS `useMocks = true`. Nothing else running. This is the fallback that must work on Sunday morning regardless of what else broke.

**Hub running, no agents.** iOS `useMocks = false`, backend `HAWKEYE_MODE=simulated`, phone and hub on the same network. This exercises the real transport, the real Codable types and the real websocket against a scripted incident.

**Full stack.** Everything above plus `HAWKEYE_MODE=live` and the agent mesh up.

Per the working agreements in the root `CLAUDE.md`: anything that must be demoed live needs a recorded fallback by Saturday night.
