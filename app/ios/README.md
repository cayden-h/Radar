# Hawk Eye, iOS

The resident's side of an incident.
Read `app/CLAUDE.md` for what the app is for, and the root `CLAUDE.md` for the project.

## Generating and running

There is no `.xcodeproj` in the repo on purpose.
`project.yml` is the source of truth and the project is generated from it, so two people editing the app never collide in a `pbxproj`.

```sh
brew install xcodegen
cd app/ios
xcodegen generate
open HawkEye.xcodeproj
```

Then pick any iPhone simulator running iOS 18 or later and press Run.

Re-run `xcodegen generate` after adding, removing, or moving a Swift file.
Nothing else needs doing: the target globs `HawkEye/`, so new files are picked up automatically.

`HawkEye.xcodeproj/` and the generated `HawkEye/Info.plist` are both gitignored.
Do not edit either by hand; edit `project.yml`.

There is no `Package.swift` and there should not be one.
This is an iOS application target, not a Swift package, and making it an SPM executable would break the app lifecycle, the Info.plist, and the Bonjour entitlements.
There are no third-party dependencies at all, so there is nothing a package manifest would buy.

## Mock mode

`HawkEye/Config.swift` holds one flag:

```swift
static let useMocks = true
```

`true` runs the entire app with no Pi, no hub and no network.
`false` runs the identical UI against a real hub discovered over Bonjour.

That switch chooses the implementations in `AppModel.init()` and nothing else in the app knows which one it got.
There is no demo branch inside any view.
If you are looking for a hardcoded address or a scripted response, `Config.swift` and the two `Mock*` types are the only places to look.

Mock mode is not a stub that returns empty arrays.
It runs the whole demo:

- Two hubs appear on the Connect screen, one already paired, a beat apart so it looks like discovery rather than a fixture.
- Three presences move through the apartment at 4 Hz: the resident between the main bedroom and the hallway, a child in the second bedroom, and a curtain over the vent above the dryer in the laundry.

  **This is mock data and is richer than a 1x1 radio delivers.** Two people within about a metre merge into one, and an exact sensed headcount is not available. Live, the count is sourced from device association against the roster and the radio answers which room and whether a presence is breathing. Do not let the mock set expectations for what the hardware claims on camera; see the counting limits under `agents/occupancy`.
- A detection lands after `Config.mockDetectionAfter` (14 seconds by default) and **raises an alert, not a call.**
  Hawk Eye never dials 911 on its own; a human tap is what releases `agents/caller`.
  Set the constant to `nil` to disable the detection and drive everything from the buttons.
- A scripted two-way 911 call plays out in the transcript once a human taps, with guidance arriving alongside it and the ANS verification feed including a claim that is refused.

### The two scenarios

`Config.mockScenario` selects which incident the script runs.
Both are complete, both run off the same sensor loop and the same detection timer, and there is no scenario branch anywhere in the views.

**`.burglary`, the default.** The one the project is built around.

A fourth presence appears in the living room.

For the first `Config.mockIntruderIdentifiedAfter` seconds it has no respiration signature, so it is `unconfirmed`, exactly like the curtain over the dryer vent in the laundry.
Then respiration is acquired and it becomes a confirmed person with `expected: false`.

**What makes it unexpected is roster plus device association**, which is the rule settled 2026-09-19 in `agents/CLAUDE.md` and `docs/research/identity.md`, not an inference from the CSI stream:

```
CSI:        3 distinct presences
Roster:     2 registered residents      (configuration, not discovery)
Associated: 2 resident phones on the network
            -------------------------------------
            1 body with no corresponding device
```

The household is known rather than discovered, and the router's association table is a genuinely second modality rather than a second view of one CSI stream.
`intruder` consumes the personhood verdict first: a perturbation with no respiration signature is a curtain, not an intruder.
We do not recognise anybody and the app never implies we do.

Name the holes rather than pretending there are none: a resident who left their phone in the car, a guest, a burglar carrying a phone that never associates.
That is exactly why this surfaces as a notification the resident acts on. Nothing dials and nothing raises an incident on its own.
It then walks `Config.mockIntruderRoute`, living room to kitchen to hallway, with its position interpolated between zone centroids so it visibly moves across the floorplan rather than teleporting between rooms.

The frame that matters is then on screen: the intruder and the resident as two distinct tracked presences, in different rooms, both moving.
The resident is on the left of the apartment and the intruder crosses the whole plan to reach them, so the two are in different rooms for the entire route until the last leg.
The unexpected person is violet with tracking brackets; the residents are the calm blue; the curtain is still a dashed grey lozenge in the laundry.
That last contrast is the argument, and it is why the curtain was kept rather than replaced.

**`.faint`.** The child goes down in the second bedroom, a six second debounce runs, and `still_down_s` starts climbing and does not reset.
The long lie, which is the clinical outcome the product moves.

Per-scenario timings live next to the selector in `Config.swift` and nowhere else.

## What is real and what is not

The project has an explicit honesty rule, so here is the line, drawn plainly.

### Real

- **Bonjour discovery.** `BonjourHubBrowser` is a real `NWBrowser` over `_hawkeye._tcp`, with the `NSLocalNetworkUsageDescription` and `NSBonjourServices` entries it needs in the Info.plist. Point it at any host advertising that service and it finds it.
- **The client transport.** `LiveHawkEyeClient` is a real `URLSessionWebSocketTask` with reconnect backoff, plus REST for commands. No part of it is scaffolding.
- **The data model.** Every `Codable` type in `Models/` is matched field for field against the generated example payloads in `app/backend/schema/`, which are produced from the live Pydantic models. All eighteen example files plus a 1,661-frame capture from a running hub decode without error. See "Wire format" below.
- **The verification feed.** `verification` events are modelled in full: the claim, the agent, its ANSName and version-bound certificate, the Trust Index with its unimplemented dimensions named rather than zeroed, the decision, and every check with its reason. The incident screen renders refusals as refusals.
- **The unexpected person.** `Presence.expected` is an orthogonal axis to `PresenceState`, not a fourth state, and it is rendered as one: a confirmed person the system did not expect turns violet and gains tracking brackets on the floorplan, and takes a violet headline, border and row tint in the roster, whichever of the two person states they are in. `nil` means expected, so a frame that omits the field does not turn the household into intruders. The words are factual, "Unexpected person" and "Not accounted for", because the claim `agents/intruder` makes is that the presence is unaccounted for and not that it knows who anyone is.
- **The presence states.** The hub decides `presence.state` and the client trusts it. `PresenceState.derive` remains as the fallback for a frame that omits the field, and it follows `agents/biometrics`: respiration carries the verdict, a recorded collapse outranks a marginal respiration estimate, and absence of respiration is never treated as absence of a person.
- **The interior view.** Everything drawn is computed from the frame that just arrived. Confidence drives blur radius, opacity, jitter and drift, so a 0.4 presence genuinely looks uncertain. No baked animation, no asset files.
- **The simulated-CO label.** The app reads `environment.provenance.simulated`, which the hub computes from `source` rather than accepting from a producer, and renders a `SIM` chip off it. A simulated reading cannot reach the screen dressed as a measured one.
- **Gap detection.** Every frame carries a monotonic `seq`. A hole in the sequence sets `missedFrames`, and the home screen says the view may be behind rather than quietly drawing a stale house.
- **The notice banner.** An unexpected presence that holds for five seconds raises a `notice` event, and the app draws a dismissible violet banner above the interior view carrying the same words and colour as the roster row: "Unexpected person," "Not accounted for." Dismissing it is local to the device; the notice itself stays in the sealed log regardless. It does not raise an incident and the three buttons below it still need a human hold. `MockHawkEyeClient` scripts the notice off `Config.mockNoticeHoldSeconds` rather than re-deriving the hold rule in Swift, because two copies of a rule is how they drift.

  **The banner carries the time it was raised, and that is load-bearing rather than decoration.** A notice records where a person was when it fired, and the presence keeps moving afterwards, so a banner reading "Living room" can sit directly above a roster row reading "Kitchen". Both are correct: the banner is history and the roster is live. Without the timestamp the pair reads as a contradiction and a viewer calls it a bug. The SMS already stated the time for the same reason, and two renderings of one notice should not disagree about what kind of thing it is.

  The banner is visual only. No haptic, no sound, now or later: a burglary defaults to silent mode precisely because a phone that buzzes gives away someone hiding, and `app/CLAUDE.md` is explicit that a silent mode which still buzzes is not silent.

### Not real yet

- **The household.** A notice carries two actions. "This is expected" vouches for that presence for the session; "Remember this visitor" opens a sheet that names them and optionally binds the device that just appeared. The sheet says which device it is about to bind and offers "no device", because binding is an inference from timing rather than proof: two people arriving together can bind the wrong phone. The Household list in the header is read-only plus swipe to delete, and it says plainly when a member has no device and so will not be recognised automatically. `HouseholdTour` covers the whole flow on the mock path, which is what makes it safe to show at a judging table.
- **The hub.** Nothing answers at `_hawkeye._tcp` today. With `useMocks = false` the Connect screen will sit on "Looking for your home" until something does.
- **Endpoint resolution.** `LiveHawkEyeClient.resolveBaseURL` uses the port from the Bonjour service record when the hub publishes one, and falls back to `Config.defaultHubPort` (8787, the backend's default) when it does not.
- **Hub verification.** Connecting checks that `GET /v1/hub` reports the same ANSName the hub advertised over Bonjour. That is a consistency check and **not** ANS verification, which is per claim, happens in the agent mesh, and reaches the app on the `verification` event. The UI never claims otherwise, and it must not start to.
- **Standing an incident down.** The backend exposes no stand-down endpoint, so the app does not offer one. An incident closes when `master` sends a `resolved` incident event. Do not add a button that posts to a route that does not exist.
- **The replay record.** `GET /v1/incident/{id}/replay` is not called by the app, so `ReplayRecord` is not modelled. The verification payloads inside it are the same types and do decode.
- **Push notifications.** `remote-notification` is declared in the Info.plist because `app/CLAUDE.md` requires background delivery, but no `UNUserNotificationCenter` registration is wired up. The resident will not be alerted with the app backgrounded.
- **First aid text.** The app contains none, deliberately. Every instruction shown comes from `agents/guidance`, which is the one component reviewed against the safety rules in `agents/CLAUDE.md`. The strings in `MockHawkEyeClient` are stand-ins for that agent's output, and they stay inside well-established public guidance: do not move a fall victim, defer to the dispatcher, wait for responders. Do not add medical copy to the client.

## Layout

```
app/ios/
  project.yml                  XcodeGen spec. The source of truth.
  README.md
  .gitignore
  HawkEye/
    HawkEyeApp.swift           @main, and the Connect -> Main transition
    AppModel.swift             The two stages and the hub handoff
    Config.swift               The mock/live switch and the base URL. One file.
    Models/
      Hub.swift                A discovered hub, and why this is not a WiFi list
      Provenance.swift         Source, SourceClass, and the honesty rule
      InteriorState.swift      Presence states, presences, floorplan, state
      Incident.swift           Incident, context notes, transcript, instructions
      Verification.swift       Claims, Trust Index, decisions, checks
    Services/
      HubBrowser.swift         HubBrowsing + BonjourHubBrowser + MockHubBrowser
      HawkEyeClient.swift      HawkEyeClienting, the Envelope, seq tracking
      LiveHawkEyeClient.swift  WebSocket + REST
      MockHawkEyeClient.swift  The scripted demo, shaped like the real contract
    Features/
      Connect/ConnectView.swift
      Home/HomeView.swift      Roster and incident buttons
      Home/InteriorView.swift  The Canvas floorplan. The centerpiece.
      Incident/IncidentView.swift
    DesignSystem/
      Palette.swift            Colour. State only, never decoration.
      Typography.swift         Six sizes
      Layout.swift             Spacing, radii, tap targets
      Motion.swift             Four curves. Nothing bounces.
      Components.swift         Wordmark, signal bars, card, press style
```

## The Bonjour constraint, said once more

The Connect screen looks like a WiFi picker and it is not one.

iOS does not let a third-party app enumerate nearby SSIDs.
That requires the `NEHotspotHelper` entitlement, which Apple grants only to MFi hotspot vendors on request and which we do not have.
`NEHotspotNetwork` reports only the network the device has already joined, and only with Location permission.

So the app does the honest thing: the phone is already on the home WiFi, and it browses Bonjour for Hawk Eye hubs on that network.
The footer on the Connect screen says this in one line, because a user who expects a WiFi list will otherwise be confused, and because a judge who knows iOS will check.

## Wire format

**`app/backend` is the authority on the wire format and this client follows it.**
The example payloads in `app/backend/schema/` are generated from the live Pydantic models by `tools/gen_schema.py`, so they cannot drift from the code, and the `Codable` types here are matched against those files rather than against prose.

One socket, `WS /v1/stream`, carries every event. Each frame is an `Envelope`:

```json
{ "seq": 1208, "at": "2026-09-20T04:12:45.843012Z", "incident_id": "inc-0001",
  "payload": { "kind": "verification", "result": { } } }
```

Two things about that shape are easy to get wrong and both are handled here.

- **The payload key differs per kind and is not uniformly `payload`.**
  `state` carries `state`, `incident` carries `phase` and `incident`, `transcript` carries `line`, `instruction` carries `instruction`, `verification` carries `result`, `context` carries `note`, `error` carries `code` and `message`, and `hello` carries its fields inline with no wrapper at all.
- **Timestamps are RFC 3339 UTC with microseconds**, e.g. `2026-09-20T04:12:45.843012Z`.
  `JSONDecoder.iso8601` rejects fractional seconds outright, so `HawkEyeCoding.decoder` parses both shapes.

`seq` is monotonic and server-wide. `SequenceTracker` watches it and sets `missedFrames` on a hole.
The two frames the hub sends on connect, the `hello` and the replayed last state, both carry `seq` 0 and are excluded from gap detection.

### REST

| Call | Route | Used for |
|---|---|---|
| `GET` | `/v1/hub` | The Connect handshake. Returns `hub_ansname`, checked against what Bonjour advertised. |
| `GET` | `/v1/state` | The first interior state, so the house is drawn before the first tick. |
| `POST` | `/v1/incident` | `{"incident_type": "faint"}`. 202, and what happens next arrives on the stream. |
| `POST` | `/v1/incident/{id}/context` | The "what is happening" box. |

There is no stand-down route on the backend, so there is no stand-down button in the app.

## Verification status

Built and run against Xcode 27.0.

- `xcodegen generate` produces `HawkEye.xcodeproj` with every Swift file in the target and the correct Info.plist, including both Bonjour keys.
- `xcodebuild -project HawkEye.xcodeproj -scheme HawkEye -destination 'generic/platform=iOS Simulator' build` reports **BUILD SUCCEEDED** with zero errors and zero compiler warnings.
- Every example payload in `app/backend/schema/` decodes through these `Codable` types, plus a 1,661-frame capture taken from a running hub in simulated mode with `POST /v1/demo/run`: 0 decode failures, 0 sequence gaps.
- Every closed enum in `schema/enums.json` is compared set-for-set against its Swift counterpart, and every `event_kind` the backend can send has a `HubEvent` case.

- Three UI tours run on an iPhone 17 simulator and all pass. `ScreenshotTour` walks Connect through to an open incident and writes a PNG per screen. `VerificationTour` covers the refusal path, which is the submission. `NoticeTour` covers the unexpected-presence banner: that it appears, that dismissing it makes it stay gone, and that the roster row survives the dismissal because the person is still in the building.

`NoticeTour` earns its place rather than padding the count. The first implementation gated re-raising on `notices.isEmpty`, and dismissing empties that array, so the banner came back within one sensor tick of being swiped away. The test was confirmed to fail with that guard restored, so it catches the bug rather than merely passing alongside the fix.

What has not been verified: behaviour against a real hub on real hardware, because no hub answers at `_hawkeye._tcp` yet, and the Twilio SMS against a real account, which has only ever been exercised against a mocked transport.

**There are no push notifications and there is no local notification, by decision rather than by omission.** A notice reaches a closed app by SMS. APNs is a third sink behind `NoticeSink` and is not implemented. A `UNUserNotificationCenter` local notification was considered and rejected: it only fires while the app holds the socket, which is exactly the case the resident does not need help with, and on stage it is indistinguishable from a real push.
