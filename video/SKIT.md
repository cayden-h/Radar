# Hawk Eye - the skit

The Devpost / demo video.
Target runtime 2:45.
One continuous narrative, no narrator, no title cards until the end.

The whole piece is built so that the last twenty seconds re-frame everything before them.
Everything up to the closing beat is Hawk Eye working.
The closing beat is what happens without it.

---

## The spine

A house. An intruder. A resident hiding in a closet who never says a word out loud.
Hawk Eye is the only thing in the house that can speak.

---

## Beat sheet

| # | t | Where | What happens |
|---|---|---|---|
| 1 | 0:00 | Front door, interior | Door opens. Motion trips. |
| 2 | 0:08 | Camera feed | Shutter rotates off the lens. Recording starts. |
| 3 | 0:16 | Overlay | Agent mesh motion graphic. The mesh decides. |
| 4 | 0:26 | Camera feed | Box on the person. "Unauthorized person. Notifying resident." |
| 5 | 0:34 | Closet | Watch buzzes. Resident reads it. Holds Start Incident. |
| 6 | 0:50 | Camera feed | Intruder searching the room. Moves toward the hallway. |
| 7 | 1:02 | Hallway camera | Handoff. Still tracked, still described. |
| 8 | 1:12 | Dispatch centre | Operator takes the call. Short exchange with the agent. |
| 9 | 1:32 | Closet | Resident reads the live transcript on the phone. Types context. |
| 10 | 1:46 | Camera feed | Intruder taking items. Intercut with the closet. |
| 11 | 1:58 | Dispatch centre | Operator relays to dispatch. Units rolling. |
| 12 | 2:10 | Exterior into interior | Police arrive. Arrest. |
| 13 | 2:24 | Archival | Real 911 call. The resident who could not do any of this. |
| 14 | 2:42 | Black | Logo. One line. Out. |

---

## Shot by shot

### 1. The door - 0:00 to 0:08

Cold open. No logo, no music yet.

Interior wide on a front door, held static, ambient room tone only.
The handle turns. The door opens eight inches. A figure steps in and closes it behind him.

Cut to a screen-only insert: the CSI waveform going flat, flat, flat, then spiking.
One line of UI under it.

```
motion  ·  living room  ·  0.31s
no registered device accounts for this
```

Hold two seconds. Music enters here, one low sustained note.

**Why this order.** The sensor sees him before any camera does. That is the whole premise and it has eight seconds to land.

---

### 2. The shutter - 0:08 to 0:16

Macro, on the lens. Fill the frame with it.

Start on the shield covering the glass. The servo whines. The shield rotates ninety degrees and clears.
Light hits the lens. Cut, on the motion, to the camera's own view coming up from black.

Overlay as the view resolves:

```
REC  ·  living room  ·  cam-01
```

**This is the hero shot of the entire project.** Shoot it four or five ways and pick in the edit.
Macro, backlit, shallow depth of field. The shield should read as a physical object, not a UI element.

Do not cut away from the shutter until it has finished moving. The audience needs to believe there was no image a second ago.

---

### 3. The mesh - 0:16 to 0:26

Motion graphic over a dimmed, still-running camera feed.

Nodes light in order, one hop at a time, each with its ANSName. Lines draw between them as each claim is verified.

```
presence.hawkeye.<domain>   motion, living room
        ↓  verified
intruder.hawkeye.<domain>   no device accounts for it
        ↓  verified
master.hawkeye.<domain>     grant issued
        ↓  verified
shutter.hawkeye.<domain>    open, position attested
        ↓
vision.hawkeye.<domain>     narrating
```

Each arrow gets a small green check as it draws. Total 0.9 seconds of draw time per hop, which is close to honest against the real timing budget.

**One of the hops must visibly fail later.** Not here. See the refusal note at the bottom.

---

### 4. The identification - 0:26 to 0:34

Back to full camera feed. The box draws around him, tracking as he moves.

```
unauthorized person  ·  living room
dark jacket, hood up, carrying a bag
notifying resident
```

The description on screen has to match what the audience can see in frame.
If he is wearing a brown jacket, the box says brown jacket.
A mismatch here is the one thing in this video a technical judge will catch instantly.

---

### 5. The wrist - 0:34 to 0:50

Cut hard to dark. Closet interior, coats, a sliver of light under the door.

The resident is on the floor. The watch lights their face.
Close on the watch. The notification carries the sentence the camera produced, not a generic alert.

They look at it. They look at the closet door. They press and hold.

Ring fills. Haptic. Screen changes to the incident state.

No dialogue. No whispering. They do not speak in this entire film.

**The hold is the thesis of the project and it should be the longest single shot so far.** Let it breathe. Four seconds on the hold alone.

---

### 6. Searching - 0:50 to 1:02

Camera feed. He works the room. Drawers, a shelf, a bag on the table.
The box stays on him. The description line updates as he does things.

He moves out of frame toward the hallway. The box goes to a dashed outline and the line reads:

```
subject leaving frame  ·  living room
```

---

### 7. The hallway - 1:02 to 1:12

Cut to the second angle. He walks in. Box picks him up again.

```
REC  ·  hallway  ·  cam-02
unauthorized person  ·  same subject
```

**See the hardware note below.** There is one camera. This shot needs a decision before it is shot.

---

### 8. The operator - 1:12 to 1:32

Dispatch centre. A headset, a screen, hands. Do not show a face straight on.

The agent speaks first, and everything it says is something it just verified.

```
OPERATOR    9-1-1, what's the address of your emergency?

AGENT       This is an automated emergency call placed on behalf of
            a resident at [address]. The resident is sheltering and
            cannot speak. There is one unidentified person inside
            the home. I am watching a live camera feed.

OPERATOR    Are they still in the house?

AGENT       Yes. Male, dark jacket, hood up, carrying a bag.
            He is in the hallway, moving toward the back of the house.
            That is as of four seconds ago.

OPERATOR    Is the resident safe?

AGENT       The resident is in a closet on the second floor and has
            not moved since the incident started.
```

Cut on "has not moved."

**"That is as of four seconds ago" is the line that sells the track.** The agent is telling the operator how fresh its information is, because it only says what it can currently verify. Keep it.

---

### 9. The transcript - 1:32 to 1:46

Closet again. The phone, angled down, brightness low, the resident's hand shielding it.

The transcript is scrolling live. Operator lines on one side, agent lines on the other.

They type into the context box. Show the keystrokes, show it send.

```
he might have a knife, I heard the kitchen drawer
```

Cut to the operator's screen. The same sentence lands there, tagged.

```
FROM RESIDENT · 1 sec ago
```

**This is the second boundary.** The resident is participating in a 911 call without making a sound. That is a real capability and it needs its own fourteen seconds.

---

### 10 and 11. Taking things, and the relay - 1:46 to 2:10

Intercut, tightening. Three cuts each, getting shorter.

Camera feed: he is pulling things into the bag.
Closet: the resident, not moving, watching the transcript.
Camera feed: he stops. Looks up. Toward the stairs.
Closet: they see him stop, on the phone, in their hand.

Over the top of it, the operator relaying:

```
OPERATOR    Units en route, be advised, one male inside,
            dark jacket, last seen hallway moving rear.
            Juvenile occupant sheltering second floor closet,
            not able to speak. Live camera on scene.
```

Music drops out entirely on "not able to speak."

---

### 12. Arrival - 2:10 to 2:24

Exterior. Headlights across the front of the house. No sirens, they run silent on a burglary in progress.

Interior, from the camera feed, still recording: officers enter frame. He goes down. Cuffs.

The last thing the camera feed shows is the box on him turning from red to grey and the line changing.

```
subject detained  ·  0:00:00 remaining
```

Then the shutter closes. Macro again, the shield rotating back over the lens, mirroring shot 2.

**Close the shutter on camera.** The system stops watching when the reason stops. That is the privacy argument, made physically, in two seconds, with no words.

---

### 13. The call that actually happened - 2:24 to 2:42

Full black. No image at all for the first four seconds.

The archival 911 call comes up. Heavy audio grain, phone-line band-limited, a loudness meter or a waveform as the only thing on screen.

The segment to use is 1:10 to 1:36 of the source. It is the moment the resident stops answering.

```
OPERATOR    Can you describe what this person was?
CALLER      He had a black hat on, a brown jacket, I think.
OPERATOR    So you think it was a male?
CALLER      Yeah.
OPERATOR    You think you saw a male with a dark hood and a jacket?
OPERATOR    Hello. Don't hang up.
OPERATOR    Hello. Where are you at?
OPERATOR    She saw a male inside. Now she's not answering me.
```

Then hold the silence. The real silence, from the source, is twenty-five seconds long.
Use four of them. Four is unbearable already.

**Read the sourcing note below before cutting this in.**

---

### 14. Out - 2:42 to 2:45

White text on black, one line, no logo animation.

```
Hawk Eye
a house that watches only when it has a reason to,
and can prove to 911 that it had one
```

Cut to black.

---

## Three things to decide before shooting

### The archival call cannot ship as-is

`docs/research/footage.md`, rule 4: never use real incident footage showing identifiable victims.
The source is a real 911 call from a thirteen year old girl, named in the audio, while people are in her house.
That is precisely the case the rule exists for, and it is a dignity problem before it is a licensing problem.

The beat is right. The tape is not.

**Recreate it.** Perform the same call, same words, in our own voices, and run it through the same grain and band-limiting so it sits in the same sonic world.
Nothing about the beat weakens. The silence lands identically. The words are the words of a real call, which is why they work, and we can say on stage that we re-performed it out of respect rather than stripping it for effect.

The reference audio and a full transcript are staged at `video/audio/` so the performance can match the real cadence.

If the group would rather keep real audio, the alternative is a public domain PSAP release with no identifiable minor, sourced under the same rules as the rest of the B-roll. That takes sourcing time we may not have.

### There is one camera

Shot 7 implies `cam-02` in the hallway. We own one Logitech webcam and are buying nothing else.

Recommended: shoot both rooms with the same camera, moved between setups, and label them honestly as two positions of one camera across two takes.
The vision claims are already scoped by room and carry the room as a field, so the labels stay true.

Rejected: showing two simultaneous feeds. That is a capability claim the hardware does not support, and it is the kind of thing the judge grading us is best equipped to catch.

### The refusal has to be in here somewhere

`CLAUDE.md` is explicit that the refusal path matters more than the happy path, and right now this cut is all happy path.

Recommended placement is a ten second insert between shot 3 and shot 4, cutting away from the house entirely.
A second grant arrives at `shutter` from an agent that is not `master`. The shutter does not move. One line:

```
grant rejected  ·  signature does not match master.hawkeye.<domain>
shutter position: closed
```

Then back to the house, where the real grant already worked.

That costs ten seconds and buys the entire track argument. Budget for 2:55 total rather than trying to fit it in the existing time.

---

## Production notes

- **No dialogue from the resident, anywhere.** Not a whisper, not a breath take. The day they speak is the day the premise breaks.
- **Every UI element on screen must be the real app.** Mock data is fine, mock screenshots are not. `app/ios/HawkEye/Config.swift` runs the whole app with no hardware; use it.
- **Every timing shown on screen must match the budget in `CLAUDE.md`.** Motion at 0.0, grant at 0.8, shutter attested at 1.2, first narration at about 3.0.
- **The descriptions on screen must match wardrobe.** Pick the intruder's jacket first and write the UI copy against it.
- **Shoot the shutter macro first**, while everyone is fresh and the light is controlled. It is the shot the project lives on.
- **Record a fallback of every live element by Saturday night.** Standing rule.
