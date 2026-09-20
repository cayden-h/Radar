# Vision: live camera, measured tracking, and low-light handling

Date: 2026-09-19
Status: approved, not yet implemented
Owns: `vision/`, `agents/agents/vision/`, the display layer in `app/ios/` and `app/web/replay/`
Tasks: T02 (vision half), T15, T16, T17, T20, and it unblocks T50

## Why this exists

`vision/CLAUDE.md` describes a camera path where Gemini Live is the only thing that looks at pixels.
That makes `vision.people_visible` a generated number, which is weak on its own and leaves T50's safety producer with nothing to corroborate against.

This design adds a local detector and tracker as a second, independent view of the same frames.
It also replaces the originally requested night vision with the capability the hardware can actually support.

## Hardware finding: there is no night vision path

The camera is a Logitech Brio 101, USB `046d:094d`, confirmed enumerated on the MacBook.

The Brio 101 has no IR sensor, unlike the original Brio 4K which carried one for Windows Hello.
No IR illuminator is owned, and the root `CLAUDE.md` states no further hardware is being purchased.

Therefore there is no path to infrared or near-infrared imaging, and x-ray imaging is not a thing any camera does.
Claiming either would violate the honesty rule in the root `CLAUDE.md`, in front of the one judge best equipped to catch it.

What replaces it is two separate, real capabilities: a measured low-light capture mode, and a client-side display enhancement.
Neither is ever called night vision in code, in docs, or on stage.
`docs/swapping-in-real-parts.md` gains a line recording this finding so it is not re-proposed at 4am.

## Where the work runs

The Brio is plugged into the MacBook right now, so inference runs on the M2 Pro.

The environment is already provisioned: `torch 2.9.0` with MPS available, `ultralytics 8.3.222`, `opencv 4.12.0`, Python 3.13.2.

MediaPipe was rejected.
Its wheels lag on Python 3.13, and its strength is pose landmarks on one close subject rather than multi-person tracking with stable identities across a room.

RF-DETR and Co-DETR were rejected on time rather than merit.
RF-DETR is a separate Roboflow package and Co-DETR is MMDetection, and neither has a healthy MPS path, so the cost is hours spent debugging CUDA assumptions rather than building agents.

The chosen stack is YOLO11m for detection and BoT-SORT with ReID for tracking, both native to the installed ultralytics version.
On an M2 Pro at 640px this runs at roughly 20 to 30 fps, well above the 1 fps claim rate, and ReID keeps track identities stable through occlusion.
Moving to the Pi later is a change of weights string to YOLO11n and nothing else structural.

## Module layout

```
vision/
  capture.py     FrameSource ABC -> MacCamera | PiV4L2 | FileFixture
  lighting.py    mean luminance, three-state classifier with hysteresis
  profiles.py    capture settings per lighting state
  enhance.py     greyscale + CLAHE, applied only before detection in low light
  track.py       YOLO11m + BoT-SORT/ReID, emits Track records
  record.py      ffmpeg segment writer, per-segment SHA-256
  gate.py        shutter attestation: signature, nonce, freshness
  claims.py      builds vision.* claims with per-field source labels
```

`FrameSource` is the seam.
`MacCamera` is today, `PiV4L2` is the demo, and `FileFixture` is what every test runs against.
This follows the pattern `docs/swapping-in-real-parts.md` applies to every other simulated part.

The camera device is opened exactly once.
One reader thread pulls frames and fans out to three consumers at different rates: the tracker at roughly 15 fps, the Gemini sampler at 1 fps, and the recorder continuously.
Two processes opening the device is the failure the camera guide already warns about, and it will happen the first time someone runs the recorder separately.

## Lighting detection

Mean luminance is computed on the Y channel of a downscaled frame.
It classifies into three states.

| State | Behaviour |
|---|---|
| `day` | Fixed exposure, colour frames, standard detection confidence |
| `low` | Longer exposure, gain raised, capture drops to roughly 8 fps, greyscale plus CLAHE applied before detection, detection confidence threshold raised |
| `too_dark` | No detection and no narration. `Unknown(reason="frame_too_dark")` |

Transitions use hysteresis plus a dwell requirement of roughly three seconds.
Without it a passing shadow or a car headlight flaps the pipeline in the middle of an incident.

Thresholds live in config rather than as constants, because they must be calibrated at the demo location and the value that works in one room is wrong in another.

The `too_dark` state does double duty.
It is also the guard that catches a jammed shield attesting `open`, which `vision/CLAUDE.md` already assigns to this agent, because `position_basis` is always `commanded` and the servo is open loop.

## Claims contract

`vision/CLAUDE.md` is amended.
`people_visible` moves from generated to measured, and `vision.tracks[]` is added.

| Field | Source |
|---|---|
| `vision.people_visible` | measured, count of active tracks |
| `vision.tracks[]` | measured: `id`, `bbox`, `first_seen`, `last_seen`, `frames_held` |
| `vision.lighting` | measured |
| `vision.mean_luminance` | measured |
| `vision.description` | generated |
| `vision.carrying` | generated |
| `vision.matches_resident` | generated, limits unchanged |
| `vision.room` | enrollment, fixed, never inferred |
| `vision.shield_attested_at` | from the shutter attestation the claim stands on |

Bounding boxes are stored normalised to 0..1 so a client can scale them to any view size, and each track record carries the frame timestamp so an overlay can align to the video.

Two independent views of the same frames is what unlocks T50.
A narration describing a person for which no track ever existed is a corroboration failure, and that is a postable unsafe-behaviour observation to the Trust Index.

## Display layer

The recorded mp4 segments stay exactly as the sensor produced them.
`replay` hashes those segments into the chain and Resend emails them to a police department, so brightening, denoising or tinting footage before it reaches law enforcement is altering evidence rather than a cosmetic choice.

Enhancement is therefore a view transform applied at display time, on the client, and it provably cannot reach the recorded file because it happens after the file.

- iOS and watchOS apply CLAHE, gamma lift, and temporal frame averaging via CoreImage or Metal.
- The replay console at `/replay` does the same in WebGL.
- The Pi and the Mac ship raw frames and spend no cycles on enhancement.
- The UI badges the view as enhanced for viewing, and the raw frame is one tap away.

The overlay draws each track's bounding box and its stable track ID over the live view in the iOS app and the replay console.
This makes `vision.people_visible` visibly a measured number rather than an assertion, and it is the clearest on-stage evidence that a real tracker is running.

Green night-vision colourisation is optional and is a UI skin only.
It may be shipped only if it is unmistakably a skin and is never presented as a different sensor.

## Failure modes

These extend the table already in `vision/CLAUDE.md` and do not replace it.

| Failure | Required behaviour |
|---|---|
| Shield closed or attestation stale | `Unknown(field="vision.description", reason="shield_closed")`, no frames sampled |
| Camera absent | Unhealthy observation, `reason="no_camera"`, recording path also reports down |
| Gemini Live drops | Narration stops, `Unknown(reason="narrator_unreachable")`, recording continues |
| Frame below the `too_dark` threshold | `reason="frame_too_dark"`, no description |
| Detector fails to load or MPS is unavailable | Tracking claims become `Unknown(reason="tracker_unavailable")`. Narration and recording both continue, because the tracker is a corroborating view and not a gate |
| Disk full | Recording stops loudly |

## Tests

All tests run against fixtures with no hardware attached.

- A bright mp4 and a dark mp4, producing a description and `frame_too_dark` respectively.
- A synthetic luminance ramp, asserting hysteresis does not flap at the boundary.
- A two-person fixture with a crossing occlusion, asserting track identities survive.
- A stub attestation that is absent, stale, and valid, with a claim only in the third case.
- A Gemini session killed mid-fixture, asserting narration stops and recording is unaffected.
- A forced detector load failure, asserting `tracker_unavailable` and that narration and recording both continue.
- Every claim carries its per-field source label and the room scope.

## Order of work

Phase A is the camera path standalone, runnable as a script against the live Brio with no agents, no network and no Gemini.

1. `FrameSource` and `MacCamera`, proving frames flow from the Brio.
2. `lighting.py` and `profiles.py` with the hysteresis tests.
3. `track.py`, YOLO11m plus BoT-SORT with ReID, emitting `Track` records.
4. `record.py`, the segment writer and per-segment hashes. This closes T15.

Phase B is the agent wiring.

5. Scaffold `agents/agents/vision/`, completing the open half of T02.
6. `gate.py`, the attestation check. This closes T16.
7. The Gemini Live session and generated claims. This closes T17.
8. `master` wiring and the claim flow. This feeds T20.

The display layer lands alongside Phase B, once `vision.tracks[]` is flowing through `app/backend/` to the clients.

## Out of scope

- Face recognition against any database. The limits in `vision/CLAUDE.md` stand unchanged.
- Pose estimation and activity classification. `vision.description` remains the generated account of what a person is doing.
- Any second camera or any claim about a room the camera does not see.
