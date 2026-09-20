# app/

The Hawk Eye Apple apps. The resident's side of an incident.

Two targets after the 2026-09-19 pivot:

- **`app/watch/` - the watchOS app. The actor.** It gets the notification and it is where an incident is started
- **`app/ios/` - the iOS app. The record.** Connect, the live camera view, the full transcript, the "what is happening" box, replay

Read the root `CLAUDE.md` first, then `docs/PIVOT.md`.

## Why the watch is the actor

Because of where the phone is.

The pre-pivot design had a resident tapping Burglary or Fire on a phone, which assumed the phone was in their hand.
The scenario this system is actually built for is a person who is asleep, or in another room, or has just walked in on someone.
**A watch is on their wrist in all three cases and a phone is on a table in most of them.**

It also matches the timing budget. The notification lands about three seconds after someone walks in, carrying the camera's first sentence.
A wrist buzz that says "a person in a dark jacket is in your living room" and offers one button is the entire interaction the system needs from a human, and it is the one a person can complete in four seconds while hiding.

The phone is not demoted, it is re-roled. Everything that needs a screen - footage, the full transcript, the household roster, the sealed record - stays there.

## Raising an incident

**One action, on the watch: Start Incident.**

There were three incident types, then two, and there is now one: **Intrusion**.
Fire went with the simulated gas sensor on 2026-09-19 and fall detection went earlier the same day.
With one type there is nothing to choose, which is the right shape for a control someone uses while frightened.

One tap raises the incident to `agents/master`, which classifies, verifies, and routes.

**This is the only path to a phone call.** Hawk Eye never calls 911 on its own. A human tap is what releases `agents/caller` to dial.

### What happens without a tap

A great deal, and this is the part worth being precise about.

`agents/presence` and `agents/intruder` detect, `agents/master` opens the shutter, and `agents/vision` starts describing and recording - **all of it automatically, and none of it a call.**

The resident gets that as a **notice**: "a person is in your living room, and they do not match anyone who lives here", with the camera's own sentence under it and a still frame from the moment the shield opened.

A notice is information a person acts on. It is not a call.

The notice reaches the resident three ways now:

| Sink | When it works | Status |
|---|---|---|
| Watch notification | Whenever the watch is on a wrist. **The primary path** | New with the pivot |
| In-app banner | While the app holds the socket | Built |
| SMS through Twilio | Phone locked, app closed, watch not worn | Built |

There is deliberately still no local notification on the phone.
One would only fire while the app holds the socket, which is exactly the case the resident does not need help with, and on stage it is indistinguishable from a real push.
APNs is a driver behind `NoticeSink`, which already exists.

The trigger rule lives in `app/backend/hawkeye_backend/notices/detector.py` and is deliberately conservative: unaccounted motion only, a hold before it fires, suppressed when the capture path is unhealthy, and once per presence while it is here.
A notice is unrecallable once it is on someone's wrist.

### The notice is answerable, and the pivot makes the answer much better

**This is expected** vouches for that presence for this session and nothing persists.
**Remember this visitor** names the person and optionally binds the device that just joined the network, so the next visit raises nothing at all.
They are separate controls with separate words on purpose: one is a mute button and the other changes what the house believes, and a single control for both would persist strangers because someone wanted a banner to go away.

Before the pivot, answering a notice meant deciding about an unlabelled blob on a floor plan.
**Now the notice carries a photograph.** The resident is looking at the person they are being asked about.
That is the single biggest usability improvement the pivot buys, and it is worth a sentence on stage: the false-positive cost went from "call the police or dismiss a banner you cannot evaluate" to "oh, that is my brother".

The roster is reached through the notice and through a read-only Household list in the iOS header.
There is still no settings screen, and that rule still holds: adding someone happens by approving a real detection, which is also the only moment the system has a device to bind.

**The device identifier is a phone on the Wi-Fi, because CSI cannot recognise a person and must never claim to.**
iOS randomises the Wi-Fi address per network and then keeps it stable for that network, which is what makes a guest recognisable on a later visit.
A guest who never joins the Wi-Fi can be named and approved but will never be auto-recognised from the network, and the Household list says so rather than leaving the line blank.

**Face enrollment is a separate, optional thing and is not the same claim.** `agents/vision` compares against faces the household enrolled on their own hardware, and the only two answers are "matches an enrolled resident" and "does not". See `vision/CLAUDE.md` for what that does and does not mean.

### The value proposition, restated

It is not that the system dials for you. It is that when you do tap, the dispatcher is told what a camera is looking at right now, by an agent that can prove where the description came from - and that the camera could not have been watching a minute earlier.

## The watchOS app

New with the pivot. SwiftUI, watchOS 11, paired to the iOS app over WatchConnectivity.

**It is a phone-paired companion, not standalone.** The phone holds the socket to the hub and relays; the watch never speaks to the backend directly.
That is a deliberate trade: a standalone watch app would survive the phone being out of range, and it would also need Bonjour discovery, its own WebSocket, and its own connection state machine on a platform with an aggressive background policy.
On a weekend, paired is the boring working path. Say so if asked; it is a deployment property, not an architectural one.

### Four screens, and that is all

1. **Idle.** Armed or not, and when the shield last moved. One line
2. **Notice.** The still frame, the camera's sentence, and three controls: **Start Incident**, **This is expected**, **Remember this visitor**
3. **Incident live.** The current narration as it updates, an elapsed timer, and the transcript as scrolling text. One control: **Take over**
4. **Transcribe.** Mic open, the resident's speech going to the operator. This is whisper mode on the wrist

### Rules the watch inherits from the phone

These are not new decisions, they are the existing ones applied to a smaller screen. Full reasoning is further down this file.

- **Hold to confirm on anything consequential.** 1.5 seconds. A wrist is the easiest surface in the world to press by accident
- **The watch never plays call audio.** Same reason the phone does not by default: audio gives away a hiding person's position, and call audio cannot be silenced below a floor. Haptics only
- **The agent never talks over a human.** Barge-in on the watch mic yields immediately
- **Announce every transition.** A mode change the resident did not notice is the failure mode

### What the watch must never do

- Show medical or safety instruction text it generated. All guidance comes from `agents/caller/guidance.py`, relayed. The watch is a display
- Hold state the phone does not have. If they disagree, the phone wins and the watch says it is reconnecting
- Offer a second way to end the call. One is enough and two is a misfire

## During the call

This screen is the product. Give it everything.

### Live transcript

Real-time transcription of the conversation between `agents/caller` and the 911 operator, shown to the **user**.

The operator does not see this. It exists so the resident is not left in silence while a synthetic voice speaks on their behalf, which would be unbearable.
Being able to watch what is being said about you, as it is said, is the thing that makes an agent calling 911 tolerable rather than frightening.

### "What is happening" box

A free-text input where the user adds context mid-incident.

The agents know what the radio can see. They do not know that the intruder had a knife, that the child is asthmatic, or that the smoke is coming from the laundry.
Whatever the user types goes to `master` and becomes available to `caller` for the rest of the call.

Keep it a single always-visible field. Someone in an emergency will not find a disclosure triangle.

**Treat this field as untrusted input, because it is.**
It is the one path in the whole system where free-form natural language written by a human reaches `master` and then `caller`, which is OWASP ASI01, agent goal hijack, in its most direct form.
The phone is a device that can be stolen, and a resident under duress is a real scenario for an intrusion product.

Three rules, none of them expensive:

- What the user types is **context, never instruction**. It can add facts a dispatcher should hear. It cannot change what `master` verifies, what `caller` is willing to say, or where a response is sent.
- It is attributed as user-supplied when `caller` speaks it, in the same way a sensing claim is attributed to its agent. "The resident reports the smoke is coming from the laundry" is honest; stating it as a system observation is not.
- It is sealed into `agents/replay` alongside everything else, with its source marked.

The parallel is exact: `caller` must not widen what it trusts because an operator asked, and it must not widen what it trusts because the resident typed. See `docs/threat-landscape.md`.


### Joining the call

The call runs on a server-side bridge and **the phone is not a leg of it by default.** Full reasoning in `agents/CLAUDE.md`.
The reason is concrete: on iOS, call audio cannot be silenced below a floor, and a speaking phone gives away someone hiding during an intrusion.

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

After takeover the agent stops speaking on the call and keeps feeding facts to this screen instead: the current narration, the room, how many people the camera can see, and the live frame. The resident is the voice; the app is the teleprompter.

### Choosing a mode, and what may choose it for you

Settled 2026-09-19.

**The rule: automation may only ever move toward quieter. Going louder requires a human hand.**

The asymmetry is the whole justification. Guess wrong toward silence and the resident taps once to get audio back. Guess wrong toward audio and **the phone makes noise while someone is hiding.** Those are not comparable failures, so the inference is trusted in one direction only.

#### Silent is the default; the text box is a correction

With one incident type there is no type to infer from, so **Intrusion defaults to silent** and that is deterministic.
That is the safe direction: an intrusion is by definition a situation where noise may be unsafe.

What the "what is happening" box adds is the case where silence is wrong:

- Typed "I'm outside, I got out"
- Typed "they left, I'm alone now"

Phrases along those lines pull the call toward audio. Phrases like *can't talk, he's here, hiding, quiet, don't make noise* hold it in silence.

**The inference is still trusted in one direction only**, and the direction flipped with the default: silence needs no evidence, and audio does.

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
| Start Incident (phone or watch) | **Hold 1.5s** | An accidental tap calls 911. A pocket-dial to emergency services is a real harm, not an inconvenience, and a wrist is easier to press by accident than a pocket |
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
| **Intrusion** | **Silent.** No audio, no haptics, dimmed, whisper or typed only |
| Intrusion, resident confirmed out of the building | Audio on, and only after they say so |

The "what is happening" box doubles as typed takeover in silent mode: what the resident types is read aloud by `caller`, attributed as the resident's report rather than a system observation. See the untrusted-input rules above; typing is context, never instruction.


### Instructions from the agents

`agents/caller` pushes updates and instructions as the call progresses. It is the same agent that is on the phone to the dispatcher, which is what keeps the operator and the resident from being told different things.

Two sources, and the UI should not distinguish them because the user does not care:

- **Relayed from the operator.** When the dispatcher says something that matters, the user is told. "Units dispatched." "Two minutes out." "Unlock the front door if you can do it safely." Match on meaning rather than exact strings; a dispatcher will not say the phrase you hardcoded.
- **Safety instructions.** Get out and stay out, stay low, do not confront anyone, wait for responders.

There is no patient-care protocol, and the absence is deliberate: neither incident type is one where staying to help is correct guidance. CPR and the recovery position went with the cut incident type on 2026-09-19.
See the safety rules in `agents/CLAUDE.md` before writing any of this path. A bad safety instruction is a real-world harm, not a demo bug.

Something must reach the resident when the app is backgrounded, because they will not be staring at the screen.
**That is an SMS, not a push.** See the notices paragraph under "Raising an incident": APNs is a sink behind `NoticeSink` and is not implemented, and a local notification was considered and rejected because it only fires while the app holds the socket, which is exactly the case this requirement is about.

## What this app is not

- **Not a dashboard.** No settings, no accounts, no onboarding, no history browser. One resident, hardcoded.
  The history browser exists, and it is deliberately somewhere else: the replay console at **`/replay`**, served by `app/backend` from `app/web/replay/`.
  Two human surfaces, opposite tradeoffs. This one is held by a frightened person during the worst ten minutes of their year and shows only what they must act on now.
  That one is read at a desk afterward by a detective, and shows everything, hash-chained, with a scrubber and an export.
  Do not migrate features from there to here.
- **Not the operator's view.** There is no console for the 911 operator. The operator is a person on a phone and we cannot ship software into a PSAP.
- **Not where the architecture is explained.** That is the demo video's job. See `media/CLAUDE.md`.

## The 3D view

The interior map is the app's centerpiece: where people are in the house, live.

Pure Three.js / react-three-fiber, procedural, driven by the `sensor/` contract.
Do not round-trip dynamic primitives through Blender; Blender is the cinematic layer only.

**The floor plan is authored, not sensed.** The system does not map walls and cannot; walls are the static baseline it subtracts to see people. See `sensor/CLAUDE.md`.
We film in one house, so measure it once and hardcode the room model. Presences are placed into **labeled zones** that come from a one-time enrollment walk, not into recovered geometry.

Do not let the visual imply the layout was discovered. Honesty rule, entry four in the root `CLAUDE.md`.
If it reads as a live map of an unknown house, add a line of UI that says the plan was set up once.

Render confidence as coherence rather than as a number floating in space. A presence at 0.4 should look uncertain.
That is honest and it also looks better.

**The interior view changed shape with the pivot, and it got simpler.**

The radio no longer distinguishes a person from a curtain, so the floor plan no longer pretends to. It shows one thing: **where motion is**, as a soft region rather than a dot, because a dot implies a located body and the radio does not locate bodies.

What sits next to it is the thing that actually answers the question: **the camera feed.**

Three states, and they are about the shield rather than about a body:

- **Shield closed.** The camera is physically covered. Say so, and say it as a good thing rather than as an error. This is the resting state and it is the product's whole privacy argument, visible
- **Shield opening.** The grant verified and the servo is moving. A second of animation, and it is worth animating well, because this is the moment the system decides to look
- **Shield open, camera live.** The feed, the narration under it as it arrives, and a timestamp

**The fourth state is the one that wins the judging conversation: shield refused.**
When `shutter` declines a grant, the view says the camera stayed covered and says why, in the resident's language: "something asked to open your camera and could not prove it was allowed to."

Make that screen good. It is the visual form of the entire submission, and it is the only place a non-technical person can see a cryptographic refusal as a thing that protected them.

**The single most important frame in this project is now literal: the camera feed, with the narration beneath it, and the closed shield in the corner of the same screen a minute earlier.**

Target Best UI/UX Hack while you are here. It is stackable and this view is the strongest candidate on the team.

## Platform note

Native iOS is justified by live transcription, the interior view, and an audio path the app controls precisely enough to keep a phone silent while someone is hiding. A home-screen web app does all three badly.

**Push notifications are not part of that justification, because we did not ship them.** They were the original argument and it did not survive contact: APNs needs a paid developer account and a push server, a local notification only fires while the app already holds the socket, and what actually reaches a locked phone with the app closed is an SMS, which needs no iOS capability at all. Stated here rather than left as a claim nobody checked, since a reader who takes this paragraph at face value and then greps for `UNUserNotificationCenter` finds nothing.

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

**Stage 2, Main.** The live interior view, the presence roster under it, and the two incident buttons. An open incident takes over the whole screen, because during a call nothing should compete with the call.

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

`Config.mockScenario` had two values before the pivot and now has one, `.intrusion`, because there is one incident type.

The script it runs is the demo:

1. Motion appears in the living room and no registered device is associated with it
2. `intruder` returns unaccounted, and the shield animates open on screen about 800ms later, with the grant's verification shown alongside it
3. The camera panel goes live and the first narration line lands about three seconds in
4. A notice fires, carrying that line and a still frame
5. The incident waits on a human. `Config.mockDetectionAfter` fires everything above and stops there; nothing dials until a button is held

Its verification set is its own: an ASSERTED unaccounted-motion claim from `agents/intruder`, an ASSERTED shutter attestation from `agents/shutter`, an ATTRIBUTED description from `agents/vision`, and a DISCARDED claim that the person is armed, from an impostor at a lookalike ANSName.

**The mock must also be able to run the refusal**, because the refusal is the submission.
`Config.mockShutterRefuses` makes `master`'s grant fail verification, and the app must then show the fourth interior state: shield closed, camera never opened, and a plain-English explanation of what was refused.
That path has no camera feed at all, and the UI must be good with nothing to show. Getting that screen right is worth more than any other screen in the app.

The mock builds the same `Codable` types the live client decodes, so the two paths are behaviourally identical rather than merely similar.

**The demo must never depend on hardware being alive**, so this path is a first-class implementation rather than an afterthought. There is no demo branch inside any view; `AppModel.init()` picks an implementation behind `HubBrowsing` and `HawkEyeClienting` and nothing downstream knows which it got.

### The interior view

`Features/Home/InteriorView.swift`. A top-down procedural floorplan in a SwiftUI `Canvas`, not Three.js, because this is a native client. Same brief: confidence rendered as coherence, three visual states, no numbers floating in space.

`Models/InteriorState.swift` holds the motion region and the shield state, which are the two things the view draws.

**The pivot deleted `PresenceState`'s three-way person classification**, because the radio no longer makes that distinction. What replaced it is a shield state - `closed`, `opening`, `open`, `refused` - and the camera panel beside the plan.

`refused` is the state worth building carefully. It has no feed, it has no motion resolution beyond a region, and it has to communicate that the system protected the resident rather than that it broke.
An unconfirmed perturbation is never rendered as a person, which was true before the pivot and is now structural: the view has no way to draw one.

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
Every instruction on screen comes from `agents/caller`, specifically `agents/caller/guidance.py`, which is the one component reviewed against the safety rules in `agents/CLAUDE.md`. Hardcoding first-aid copy in the app would put it outside the place it gets reviewed.
