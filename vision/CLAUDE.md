# vision/

The camera agent. The primary sensor after the 2026-09-19 pivot.

It runs on the Pi, owns the Logitech USB camera, and does two things at once:

1. **Narrates.** A Gemini Live session, open for the duration of the incident, producing a running description of what is in the room. This is what the caller agent says to 911
2. **Records.** Continuous mp4 segments to local disk. This is what goes into the sealed record and what gets emailed to the police

Those two paths share a camera and nothing else. **The recording must never depend on the network**, because the thing worth having when the WiFi drops mid-incident is the footage.

Read the root `CLAUDE.md` and `docs/PIVOT.md` first.

## The rule that governs everything here

**`vision` produces no claim unless it holds a current attestation from `shutter` saying the shield is clear.**

Not a config flag. Not a boolean it sets itself. A signed attestation from a separate agent, fetched and verified, with a timestamp it checks.

Without it, `vision` returns an `Unknown` with reason `shield_closed`, which is a fact a dispatcher would want and which the existing `Agent.blind()` helper already models.

### What the attestation actually is

`shutter` is built, so this is settled rather than pending. `shutter.open` returns it as an opaque JSON string
alongside the position:

```json
{"position": "open", "commanded_angle": 90, "position_basis": "commanded",
 "nonce": "shut-...", "at": "2026-09-19T03:00:00.000000+00:00"}
```

Three things to build T16 against:

- **`position_basis` is always `"commanded"`.** The SG92R is open-loop and there is no position feedback, so
  this says what the servo was *told*, never where the shield is. A jammed shield attests `open`. **`vision`
  is the thing that catches that**, via the luminance guard - a shield still covering the lens produces a dark
  frame, and `frame_too_dark` is the correct claim, not a description of a dimly lit room
- **`nonce` identifies the grant that caused the movement.** It is how a claim gets tied back to the specific
  authorization that uncovered the camera, all the way into the sealed record
- **`at` is what "current" is measured against.** A stale attestation is `shield_closed`, and the staleness
  test is one of the three T16 owes

## The two paths

```
                    Logitech USB camera (V4L2, /dev/video0)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
            frame sampler                  segment writer
         ~1 fps, JPEG, resized          H.264, 10s segments,
                    │                    continuous, to disk
                    ▼                           │
         Gemini Live (WebSocket)                ▼
         one session per incident       incident/<id>/seg-NNNN.mp4
                    │                    + per-segment SHA-256
                    ▼                           │
           narration text                       ▼
                    │                    replay agent seals them
                    ▼                    into the hash chain
         signed claims to master
```

### Why one frame per second

Gemini samples video at roughly 1 fps regardless of how you hand it over.
A "video upload" is not richer than frames; it only hides the sampling.

So we sample explicitly at 1 fps, which means:

- We control the rate rather than discovering it
- We can say honestly what the narration is: **a sequence of observations, not continuous tracking**
- The Pi 4B is not asked to encode and upload more than it can

Say this out loud in the pitch. It is a limit, not a flaw, and pretending otherwise is the kind of claim the judge grading us is best equipped to catch.

### Why the Live API rather than clip uploads

The Live API holds context across the incident, which is what makes the narration useful rather than repetitive.
"The person has moved into the hallway, still carrying the bag" requires remembering the bag.
Per-clip uploads do not remember anything, so every description restarts from nothing and the caller agent ends up telling the operator the same sentence four times.

The cost is a persistent WebSocket and an API key that must be live during the demo.
The mitigation is that the **recording path is completely independent**, so a Live session that fails costs narration and costs nothing else.

### Why the segments exist separately

Three consumers, one artifact:

- The resident watches them in the iOS app
- `replay` hashes each one into the chain as it closes, so the video is covered by the same tamper evidence as everything else
- `replay` attaches them to the police email via Resend

Ten-second segments rather than one long file, because a file still being written cannot be hashed, and an incident that ends abruptly should not lose everything.

## The claims it makes

Every claim is scoped to the one room the camera sees, and carries that scope as a field.

| Field | Meaning |
|---|---|
| `vision.people_visible` | How many distinct people are in frame. Integer, and it is a count of what the camera sees, not of the building |
| `vision.description` | The narration sentence. Free text, generated, and labelled as generated |
| `vision.matches_resident` | `no_match`, `match:<enrolled_id>`, or `undetermined`. See the limits |
| `vision.carrying` | What the person appears to be holding, when the model says so. Often empty |
| `vision.room` | Which room. Fixed, from the camera's enrollment, never inferred |
| `vision.shield_attested_at` | The timestamp on the shutter attestation this claim is standing on |

## Limits, and they are the important part of this file

**1. There is no face recognition against any database.**
We have no database and no lawful basis for one.
`vision.matches_resident` compares against faces the household enrolled themselves, on their own hardware, and nothing else.
`no_match` means "not one of the people who live here". It does not mean "a known offender" and it does not mean "a stranger to the world".
Any pitch sentence that implies otherwise is a fabrication. Do not write one.

**2. The model describes; it does not identify.**
Build, clothing, what they are carrying, what they are doing. These are things a witness would say and are exactly as reliable as a witness.
The 911 script treats them that way: "the camera is describing a person in a dark jacket", not "the intruder is wearing a dark jacket".

**3. One fixed camera sees one room.**
It cannot say the house is empty. It cannot say where someone went after they left frame.
When someone leaves frame, the claim is `people_visible: 0` for that room, and `master` must not turn that into an absence claim about the building.

**4. Roughly one observation per second.**
Fast motion between samples is not seen. A person crossing the frame in under a second may produce one frame or none.

**5. The narration is generated text.**
It is labelled `source: generated` in the claim, and the replay console renders it differently from measured fields, the same way the old gas reading was labelled.
An operator being read a sentence a language model wrote deserves to have that fact in the record.

## Failure modes and what each one must look like

None of these may present as a confident description.

| Failure | Required behaviour |
|---|---|
| Shield closed or attestation stale | `Unknown(field="vision.description", reason="shield_closed")`. No frames sampled |
| Camera unplugged or `/dev/video0` missing | Unhealthy observation, `reason="no_camera"`. Recording path also reports down |
| Gemini Live session drops | Narration stops, claims go to `Unknown(reason="narrator_unreachable")`. **Recording continues.** This is the whole reason the paths are separate |
| Dark frame, camera working | The model will cheerfully describe a dark room. Check mean luminance before sampling and emit `reason="frame_too_dark"` below threshold. This is the failure that looks like success |
| Disk full | Recording stops, and it must be loud. A sealed record missing its video is worse than a visible failure |

## Hardware

`docs/hardware/logitech-camera.md` is the guide. The parts that matter here:

- The camera and the servo both hang off the Pi. Check the USB current budget before the demo, not during it
- Fix the exposure and white balance. Auto-exposure hunting between frames produces descriptions that contradict each other one second apart
- Geometry is the opposite of the CSI geometry. CSI wants the router and Pi on opposite sides with people in between; the camera wants to face the entry point. The camera's mount is independent of the Pi's placement. Do not let one constraint silently break the other

## Tests this agent owes

- A stub attestation that is absent, stale, and valid, and a claim only in the third case
- A stub frame source producing a dark frame, and `frame_too_dark` rather than a description
- Segment writer rotating at the boundary and producing a hashable, closed file
- Gemini Live dropped mid-incident, and the recording path unaffected
- Claims carry `source: generated` and the room scope, always
