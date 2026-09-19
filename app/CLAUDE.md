# app/

The Hawk Eye iOS app. The resident's side of an incident.

Read the root `CLAUDE.md` first.

## What it is

An iOS app the resident holds during the worst ten minutes of their year.

It does three things: raise an incident, show what is happening on the 911 call, and tell the user what to do.
Everything else is out of scope.

## Raising an incident

Three buttons, named for the three incident types:

- **Burglary**
- **Fire**
- **Faint**

One tap raises the incident to `agents/master`, which classifies, verifies, and routes.

**This is the only path.** Hawk Eye never calls 911 on its own; settled 2026-09-19. A human tap is what releases `agents/caller` to dial.

`collapse` and `environment` still detect, and their detections surface here as **alerts**: "a fall was detected in the west bedroom four minutes ago." An alert is information a person acts on. It is not a call.

The value is not that the system dials for you. It is that when you do tap, the dispatcher is told how many people are in the house, which rooms they are in, whether each is breathing, and how long since one of them went down.

## During the call

This screen is the product. Give it everything.

### Live transcript

Real-time transcription of the conversation between `agents/caller` and the 911 operator, shown to the **user**.

The operator does not see this. It exists so the resident is not left in silence while a synthetic voice speaks on their behalf, which would be unbearable.
Being able to watch what is being said about you, as it is said, is the thing that makes an agent calling 911 tolerable rather than frightening.

### "What is happening" box

A free-text input where the user adds context mid-incident.

The agents know what the radio can see. They do not know that the intruder had a knife, that the child is asthmatic, or that the smoke is coming from the garage.
Whatever the user types goes to `master` and becomes available to `caller` for the rest of the call.

Keep it a single always-visible field. Someone in an emergency will not find a disclosure triangle.

**Treat this field as untrusted input, because it is.**
It is the one path in the whole system where free-form natural language written by a human reaches `master` and then `caller`, which is OWASP ASI01, agent goal hijack, in its most direct form.
The phone is a device that can be stolen, and a resident under duress is a real scenario for a burglary product.

Three rules, none of them expensive:

- What the user types is **context, never instruction**. It can add facts a dispatcher should hear. It cannot change what `master` verifies, what `caller` is willing to say, or where a response is sent.
- It is attributed as user-supplied when `caller` speaks it, in the same way a sensing claim is attributed to its agent. "The resident reports the smoke is coming from the garage" is honest; stating it as a system observation is not.
- It is sealed into `agents/replay` alongside everything else, with its source marked.

The parallel is exact: `caller` must not widen what it trusts because an operator asked, and it must not widen what it trusts because the resident typed. See `docs/threat-landscape.md`.


### Joining the call

The call runs on a server-side bridge and **the phone is not a leg of it by default.** Full reasoning in `agents/CLAUDE.md`.
The reason is concrete: on iOS, call audio cannot be silenced below a floor, and a speaking phone gives away someone hiding during a burglary.

Three modes, switchable at any time, with a large persistent control:

| Mode | Mic | Audio out |
|---|---|---|
| **Watching** | off | none |
| **Whispering** | open | **none** |
| **Full voice** | open | on |

**Whisper mode is the important one.** The resident speaks; nothing plays back. They read the replies on screen.

Send and receive are **independent switches on the bridge**, so whisper is send-only. Silence is enforced server-side: if the bridge never transmits audio to the phone, there is nothing for iOS to play, and no volume floor to fight. Full matrix in `agents/CLAUDE.md`.

Hold the WebRTC leg open from the start of the call with **both switches off**. Switching modes is then one bit flipped server-side, with no connection handshake and no ring in the middle of an emergency. This is the reason the resident's leg must not be a phone call: a PSTN leg cannot be pre-established silently.
Implement the resident's leg as **in-app WebRTC audio, not a phone call** - the app owns its `AVAudioSession` and simply never renders the far side. Skip CallKit so it does not present as a call, with its connect tone and call UI.

**TAKE OVER** sits on screen permanently and large. **Hold 1.5s**, same as every other risky control; the agent then goes silent mid-sentence.
Keep **End call** visually separate from it. Someone panicking hits the biggest button, so the biggest button must be the recoverable one.

If the agent needs to stop immediately, **speaking does it** - barge-in is instant and needs no button. See below.

After takeover the agent stops speaking on the call and keeps feeding facts to this screen instead: CO ppm, room, respiration, time down. The resident is the voice; the app is the teleprompter.

### Choosing a mode, and what may choose it for you

Settled 2026-09-19.

**The rule: automation may only ever move toward quieter. Going louder requires a human hand.**

The asymmetry is the whole justification. Guess wrong toward silence and the resident taps once to get audio back. Guess wrong toward audio and **the phone makes noise while someone is hiding.** Those are not comparable failures, so the inference is trusted in one direction only.

#### The incident type is the default; the text box is a correction

Tapping Burglary already selects silent. That is deterministic and needs no inference.

What the "what is happening" box adds is the case where the tap and the reality disagree:

- Tapped **Faint**, typed "someone is in the house"
- Tapped **Fire**, typed "I can't talk, he's downstairs"

Phrases along the lines of *can't talk, he's here, hiding, quiet, don't make noise* pull the call toward silence regardless of which button was pressed.

**Act on partial input.** If someone types "he's in the h" and stops, that is enough. Do not wait for a submit.

#### Auto-silence yes, auto-mic no

| Action | Automatic |
|---|---|
| **Receive off** - the phone stops making sound | **Yes.** Always safe. |
| **Send on** - mic opens, 911 hears them | **No.** One tap, large button. |

Opening someone's microphone to emergency services without being asked is a meaningful act, and the inference argues against it anyway: a resident who typed "I can't talk" has said not to.

This also keeps the box consistent with the untrusted-input rules above. **What the resident types is context, never instruction.** It may lower the volume. It may not take an action on their behalf.

#### Label by consequence, not by our jargon

"Whisper" and "full voice" are our words. On screen, name what happens:

```
  Listening only                       <- current state

  [ Speak - they'll hear you,
    your phone stays silent ]

  [ Turn on sound - your phone
    will be audible ]
```

Always visible. Never behind a menu or a disclosure triangle.

#### Preventing accidental presses

Settled 2026-09-19. **Hold-to-confirm, not modal dialogs.**

| Control | Protection | Why |
|---|---|---|
| Raise incident (Burglary / Fire / Faint) | **Hold 1.5s** | An accidental tap calls 911. A pocket-dial to emergency services is a real harm, not an inconvenience |
| End call | **Hold 1.5s** | Hanging up on 911 mid-incident is catastrophic |
| Turn on sound | **Hold 1.5s** | Makes the phone audible and can reveal a hiding person |
| **Take over** | **Hold 1.5s** | Consistent with every other risky control. Voice barge-in remains the instant path |
| Speak / whisper | Single tap | Low harm if triggered by accident; being heard is rarely the danger |

**Hold rather than a modal**, for reasons that matter specifically to a panicking user:

- A modal makes you find and hit a **second** target with shaking hands. A hold is one gesture on the target you already found.
- A modal can be dismissed by accident too, so it trades one misfire for another.
- A hold gives **continuous feedback** and **release-to-cancel**. You can change your mind halfway.
- It is faster end to end than tap, read, confirm.
- It works one-handed, in the dark, without aiming twice.

Apple's Emergency SOS uses the same pattern, so it needs no teaching.

Show a **fill animation** on the button through the hold, so the progress is legible and release-to-cancel is discoverable without instructions.

**In silent mode the hold feedback must be purely visual.** No haptics, no sound. A confirmation that buzzes defeats the mode it is confirming inside of.

#### Every control is held. Barge-in is what stays instant.

**All risky controls use the same 1.5s hold**, including `TAKE OVER`. Settled 2026-09-19.

Uniformity is itself a safety property here. A resident under stress should not have to remember which buttons behave which way; every control that matters works identically, and a stray palm or pocket press does nothing anywhere in the app.

The reason this costs nothing is that **the hold is not the only way to stop the agent.** Voice barge-in is instant and cannot be triggered by accident, because it is not a button:

| Path | Speed | Misfire risk |
|---|---|---|
| Speak | instant | none - it is a voice, not a target |
| `TAKE OVER` | 1.5s hold | none - deliberate |

So the urgent case is covered by talking, which is what a person does instinctively anyway, and the button is the deliberate path for someone who would rather not speak.
**Barge-in is therefore load-bearing, not a nicety.** If it is cut, `TAKE OVER` becomes the only stop and the hold duration needs revisiting.

#### Friction goes where the danger is

This is the rule that resolves the no-confirmation-dialog principle above rather than contradicting it:

- **Every risky or irreversible control is a 1.5s hold**: raising an incident, take over, turn on sound, end call. One consistent gesture, nothing to remember.
- **Voice barge-in stays instant**, because it is not a button and cannot misfire. That is what makes holding the buttons safe.

The consequence stays written on the button itself. Reading "your phone will be audible" is half the confirmation; the hold is the other half.
Someone panicking slaps the biggest button, so the biggest button must always be the safe one.

#### The operator can ask, never grant

Dispatchers will want this: "can you speak?" surfaces as a prompt in the app via `agents/caller`.
The resident still taps. The operator requests; only the resident decides.

### Silent mode

A phone in a dark closet gives someone away three ways, and volume is only one:

| Leak | Handling |
|---|---|
| Speaker audio | Call is server-side. Nothing to play. |
| **Vibration and haptics** | **Off entirely.** A phone buzzing against a floor is loud. |
| Screen brightness | Dim hard, dark UI. A bright screen is visible under a door. |
| Notification sounds | Suppressed for the duration. |

Haptics are the one people forget. A silent mode that still buzzes is not silent.

Defaults by incident type, with a manual toggle in every mode because a medical emergency can also be one where noise is unsafe:

| Incident | Default |
|---|---|
| Faint | Audio on |
| Fire | Audio on |
| **Burglary** | **Silent.** No audio, no haptics, dimmed, whisper or typed only |

The "what is happening" box doubles as typed takeover in silent mode: what the resident types is read aloud by `caller`, attributed as the resident's report rather than a system observation. See the untrusted-input rules above; typing is context, never instruction.


### Instructions from the agents

`agents/guidance` pushes updates and instructions as the call progresses.

Two sources, and the UI should not distinguish them because the user does not care:

- **Relayed from the operator.** When the dispatcher says something that matters, the user is told. "Units dispatched." "Two minutes out." "Unlock the front door if you can do it safely." Match on meaning rather than exact strings; a dispatcher will not say the phrase you hardcoded.
- **First aid.** CPR, recovery position, stay low and cover your nose, do not move someone who fell.

See the safety rules in `agents/CLAUDE.md` before writing any of the first-aid path. Bad first-aid instructions are a real-world harm, not a demo bug.

Notifications must arrive when the app is backgrounded. The resident will not be staring at the screen.

## What this app is not

- **Not a dashboard.** No settings, no accounts, no onboarding, no history browser. One resident, hardcoded.
- **Not the operator's view.** There is no console for the 911 operator. The operator is a person on a phone and we cannot ship software into a PSAP.
- **Not where the architecture is explained.** That is the demo video's job. See `media/CLAUDE.md`.

## The 3D view

The interior map is the app's centerpiece: where people are in the house, live.

Pure Three.js / react-three-fiber, procedural, driven by the `sensor/` contract.
Do not round-trip dynamic primitives through Blender; Blender is the cinematic layer only.

**The floor plan is authored, not sensed.** The system does not map walls and cannot; walls are the static baseline it subtracts to see people. See `sensor/CLAUDE.md`.
We film in one house, so measure it once and hardcode the room model. Presences are placed into **labeled zones** that come from a one-time enrollment walk, not into recovered geometry.

Do not let the visual imply the layout was discovered. Honesty rule, same category as the simulated gas sensor.
If it reads as a live map of an unknown house, add a line of UI that says the plan was set up once.

Render confidence as coherence rather than as a number floating in space. A presence at 0.4 should look uncertain.
That is honest and it also looks better.

**Distinguish a confirmed person from an unconfirmed presence.** `agents/biometrics` decides personhood from a respiration signature, so the view has three states to show, not one:

- Moving, breathing: a person, confirmed.
- Still, breathing: a person who is not responding. **This is the one the whole system exists for. Make it the loudest thing on screen.**
- A perturbation with no respiration signature: unconfirmed. Render it as such rather than as a person.

The difference between the second and third states is the difference between dispatching an ambulance and reporting a curtain, and the UI should carry that weight rather than flattening everything into identical dots.

For burglary, the single most important frame in this entire project: **the intruder and the resident as two distinct tracked presences, in different rooms, moving.**
Everything else is supporting material for that image.

Target Best UI/UX Hack while you are here. It is stackable and this view is the strongest candidate on the team.

## Platform note

Native iOS is now justified, where it was not before: push notifications, background delivery, and live transcription are the core of the experience, and a home-screen web app does them badly.

Budget for it. If iOS becomes a time sink, the fallback is a web app on the home screen with polling instead of push, and the demo video narrates over the gap.

## Implementation

The app lives in **`app/ios/`**. SwiftUI, iOS 18, Swift 6, no third-party dependencies at all.
Full build and honesty notes are in `app/ios/README.md`; this section is the shape of it.

There is no `.xcodeproj` in the repo. `app/ios/project.yml` is an XcodeGen spec and the project is generated from it:

```sh
brew install xcodegen && cd app/ios && xcodegen generate && open HawkEye.xcodeproj
```

Do that after adding or moving any Swift file. The target globs `HawkEye/`, so nothing else needs editing.

### Two stages

The app is Connect, then Main. There is no third stage, no onboarding, and no settings.

**Stage 1, Connect.** The wordmark, a quiet "Looking for your home" state, then a list of discovered hubs with name, signal strength, and whether the hub is already paired. Tapping one shows a short verifying state and then you are in.

**Stage 2, Main.** The live interior view, the presence roster under it, and the three incident buttons. An open incident takes over the whole screen, because during a call nothing should compete with the call.

### The Bonjour constraint

**The Connect screen is not a WiFi picker, and cannot be.**

iOS does not let a third-party app enumerate nearby SSIDs. That needs the `NEHotspotHelper` entitlement, which Apple grants only to MFi hotspot vendors on request, and which we do not have.
`NEHotspotNetwork` reports only the network already joined, and only with Location permission.

So discovery is Bonjour: the phone is already on the home WiFi, and `NWBrowser` finds Hawk Eye hubs advertising `_hawkeye._tcp` on it.
This requires both `NSLocalNetworkUsageDescription` and an `NSBonjourServices` entry naming the exact service type; missing either produces no results and no error, which is the most common way this fails silently. Both are in the Info.plist section of `project.yml`.

The Connect screen says the honest thing in its footer rather than implying a WiFi scan. An iOS-literate judge will check.

### The mock flag

The whole-project view of this, across the app, the hub, the agents and the sensor, is `docs/swapping-in-real-parts.md`.
This section is only the app's half.

`app/ios/HawkEye/Config.swift` holds one switch, `useMocks`, and it is the only place the choice is made.
`true` runs the full app with no Pi, no hub, and no network: hubs appear on the Connect screen, presences move through the house at 4 Hz, a detection lands and **raises an alert**, and once a human taps a button a scripted two-way 911 call plays out with ANS verifications, one of them a refusal.
`Config.mockDetectionAfter` fires the detection and nothing else; the incident waits on the button.
`false` runs the identical UI against a real hub.

`Config.mockScenario` picks which incident the script runs, and both are complete.

`.burglary` is the default and is the demo.
A fourth presence enters through the garage with no respiration signature, so it is `unconfirmed` exactly like the curtain over the vent beside it, then acquires respiration and becomes a confirmed person with `expected: false`, then routes garage to hallway to kitchen with its position interpolated between zone centroids so it visibly moves.
That puts the frame this project is built around on screen: the intruder and the resident as two distinct tracked presences, in different rooms, both moving.
Its verification set is its own, an ASSERTED unexpected-presence claim from `agents/intruder`, an ATTRIBUTED occupancy count from `agents/occupancy`, and a DISCARDED claim that the person is armed, from an impostor at a lookalike ANSName.
The CO reading is not reused there: corroboration that does not corroborate anything is noise dressed as rigour.

`.faint` is the collapse: the child goes down in the west bedroom and `still_down_s` climbs and does not reset.
The mock builds the same `Codable` types the live client decodes, so the two paths are behaviourally identical rather than merely similar.

**The demo must never depend on hardware being alive**, so this path is a first-class implementation rather than an afterthought. There is no demo branch inside any view; `AppModel.init()` picks an implementation behind `HubBrowsing` and `HawkEyeClienting` and nothing downstream knows which it got.

### The interior view

`Features/Home/InteriorView.swift`. A top-down procedural floorplan in a SwiftUI `Canvas`, not Three.js, because this is a native client. Same brief: confidence rendered as coherence, three visual states, no numbers floating in space.

`Models/InteriorState.swift` holds `PresenceState`, which is the single place the states are named. Everything downstream switches on it rather than re-deriving the rule.
`Presence.expected` crosses those states as a single orthogonal axis rather than adding a fourth case: an unexpected confirmed person is drawn in `Palette.personUnexpected`, the same violet as the Burglary button, with tracking brackets and a slow sweep that read as followed rather than as hostile, and the roster gives the row a violet headline, tint and border plus the words "Unexpected person" and "Not accounted for".
`nil` means expected, so a frame that omits the field changes nothing.
An unconfirmed perturbation is never unexpected in this sense, because it is not a person yet, and that contrast is the burglary view's whole argument.
The hub decides the state now and the client trusts what it sends; `PresenceState.derive` survives only as the fallback for a frame that omits the field.
The floorplan arrives with the state, in metres, and the view normalises it, so the geometry is the one the hub was enrolled with rather than a second copy that can drift.

### The wire format

**`app/backend` is the authority and the client follows it.**
The types in `app/ios/HawkEye/Models/` are matched field for field against the generated examples in `app/backend/schema/`, which come from the live Pydantic models and so cannot drift from the code.
A harness decodes every one of those files, plus a captured session from a running hub, through the app's own types; `app/ios/README.md` has the detail.

One socket, `WS /v1/stream`, carries every event as an `Envelope` of `{seq, at, incident_id, payload}`.
The payload key differs per kind and is not uniformly `payload`: `state` carries `state`, `incident` carries `phase` and `incident`, `transcript` carries `line`, `instruction` carries `instruction`, `verification` carries `result`, `context` carries `note`, and `hello` carries its fields inline.
`seq` is monotonic and a hole in it is surfaced rather than swallowed.
Timestamps carry microseconds, which `JSONDecoder.iso8601` rejects outright.

### The verification feed

`verification` events are modelled in full and rendered on the incident screen, because the refusal path is the submission and it is worth nothing if the app cannot show it.

A `DISCARDED` claim is a refusal, not a grey log line: a red banner above the feed that stays visible whichever tab is showing, the failed checks named with their reasons, the impostor's ANSName set against the registered one, and the consequence stated in plain English.
The Trust Index shows integrity and identity as numbers and **names the unimplemented dimensions instead of drawing them as zero**, because a 0 that means "not scored" and a 0 that means "scored zero" are different facts.

**The Connect handshake is not ANS verification.**
`GET /v1/hub` reports the ANSName the hub is anchored to and the app refuses to proceed if it differs from what Bonjour advertised.
That is a consistency check. ANS verification is per claim, happens in the mesh, and reaches the app on the `verification` event.
The UI says so and must not start claiming more.

### Standing down

The backend exposes no stand-down route, so the app has no stand-down button.
An incident closes when `master` sends a `resolved` incident event, and the mock does the same at the end of its script.

### First aid

**The client contains no medical text and must not acquire any.**
Every instruction on screen comes from `agents/guidance`, which is the one component reviewed against the safety rules in `agents/CLAUDE.md`. Hardcoding first-aid copy in the app would put it outside the place it gets reviewed.
