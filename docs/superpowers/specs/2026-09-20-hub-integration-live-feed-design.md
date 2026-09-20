# Hub integration: one live feed, one backend, three surfaces

Design, 2026-09-20.
Supersedes nothing. Extends `2026-09-19-master-hub-api-design.md`, `2026-09-19-vision-tracking-design.md` and `2026-09-20-motion-gated-shutter-design.md` rather than replacing any of them.

## The problem

Four parts now work in isolation and none of them reach a screen.

The servo moves. Gemini narrates. MongoDB Atlas holds sealed records. The camera tracks people on real footage.
What does not exist is any path from a camera on one machine to a phone, a watch and a browser on another, and any way for a button pressed on one of those three surfaces to be seen by the other two.

`app/backend` already has the right primitive for the second half of that. `HubRuntime.emit()` is a single funnel that sequences an event, persists it, and fans it out to every websocket subscriber.
Anything that goes through it reaches every connected client by construction.
The work is to put the missing producers and the missing controls on that funnel, and to add the one thing it has no concept of at all, which is video.

## Decisions taken before this design

Recorded so they are not relitigated.

1. **Live video reaches the apps as MJPEG from the backend, plus a 1 Hz thumbnail on the existing websocket.** Not WebRTC. Not frames on the event bus.
2. **The demo runs `HAWKEYE_MODE=simulated` with real parts spliced in.** The agent mesh is not on the critical path for this work. `docs/swapping-in-real-parts.md` is the switchboard and gains four new rows.
3. **The Pi stays thin.** Camera and servo only. All compute is on the MacBook.
4. **MongoDB becomes the primary store**, in the write-through shape described in section 6.
5. **Four controls must work identically from any surface**: start incident, add context, shutter open/close, and remember visitor / dismiss notice.

## 1. Topology

```
Pi 4B (WiFi)                            MacBook M2 Pro (WiFi)
  Brio      ──┐                     ┌── app/backend :8787
  SG92R     ──┤   hawkeye-edge  ════╡     vision/ (YOLO, Gemini, mp4)
              │   (Pi dials out)    │
              └─                    └── MJPEG · WS · REST
                                             │
                               phone · watch · browser
```

Every box is on one WiFi network. Which network is configuration, not code.
Venue WiFi is the plan; a phone hotspot is the documented fallback; the Archer AX1450 is a third fallback that has a LAN but no internet, and therefore no Gemini, no Atlas and no call.
The design does not know or care which one it is running on.

**The Pi is not wired.** It is wired-only when `nexmon_csi` holds the radio in monitor mode, and CSI is simulated on this path, so the radio is free to associate normally.
The Pi carries a priority list of SSIDs and comes up on whichever is present.

**The Pi has a display**, which removes two of the three ways venue WiFi breaks.
A captive portal can be clicked through, and an SSID can be joined from the desktop, neither of which a headless box can do.
What a display does not fix is client isolation, and that is therefore the only remaining network unknown.
The check for it is the first step in section 8, and the runbook in section 10 leads with it.

**The Pi dials the Mac, never the reverse.**
One bidirectional websocket, `WS /v1/edge/link`, carries JPEG frames up and shutter grants down.
This means the Pi needs to know exactly two things about the world: a WiFi password, and the name `hawkeye-hub.local`.
It never needs a fixed address of its own, which matters because its DHCP lease moves every time the network changes.
Dial-out is kept even though the Pi now has a display: a display makes the Pi's address discoverable by a human, and this makes it something no machine has to discover at all.

Relaying a signed grant over that link costs nothing.
The grant is signed by `master` and bound to a nonce `shutter` itself issued, so `shutter` verifies it on arrival regardless of how it travelled.
That is a stronger claim than a direct connection would be: the grant crosses an untrusted relay and the servo still refuses anything it cannot verify.

The link authenticates with a shared secret, `HAWKEYE_EDGE_TOKEN`.
Without it, any host on the same WiFi could inject frames into the camera feed, which is the one surface a human is asked to believe.

## 2. The live feed

### Ingest

New module `vision/hawkeye_vision/edge.py`, run on the Pi as `python -m hawkeye_vision.edge`.

It opens the Brio through the existing `FrameSource`, encodes with the existing `encode_jpeg` from `narrate.py`, and pushes frames up the link.
It runs no model and holds no Gemini session. A Pi 4B cannot run YOLO11m at any useful rate, and this module exists precisely so it never has to.

### Fan-out

New module `app/backend/hawkeye_backend/edge/camera.py`. `LiveCamera` holds the most recent frame and its arrival time, and serves three consumers at three rates.

| Surface | Transport | Rate |
|---|---|---|
| iOS, web console | `GET /v1/camera/live`, `multipart/x-mixed-replace` | full |
| Watch | `FrameEvent` on `WS /v1/stream` | 1 Hz |
| Anything | `GET /v1/camera/still`, one JPEG | on demand |

`FrameEvent` is a new member of the envelope union in `models/events.py`, carrying a small base64 JPEG.
The watch therefore needs no new transport: `PhoneWatchRelay` already forwards envelopes, and `Notice.stillFrame` already proves a JPEG survives that path.

A slow MJPEG consumer is dropped rather than allowed to back up the camera, on the same reasoning `EventBus` already applies to slow websocket subscribers.

## 3. Vision moves to the Mac

`vision/` gains exactly one new `FrameSource`: `RelayFrameSource`, reading the backend's camera relay over localhost.

Everything below that seam is unchanged and keeps its current tests: YOLO11m with BoT-SORT ReID, three-state lighting with hysteresis, occupancy, rotating mp4 segments hashed as they close, and `narrate.py`'s Gemini Live session.
This is the whole reason the `FrameSource` seam exists, and using it is cheaper than any alternative.

It runs as its own process on the Mac, not inside the web server.
A model inference loop has no business on the event loop that owes a wrist three seconds.

It posts results back to the backend:

- `POST /v1/vision/narration`, one Gemini line
- `POST /v1/vision/occupancy`, person present or absent, which is what closes the shutter again

Gemini lives with the vision process, next to the frames it describes.

### Narration is its own event, not a transcript line

`TranscriptLine` is documented as one line of the caller-to-911 conversation and must not be reused here.
Narration is a different claim from a different source making a weaker statement, and collapsing the two would let a camera observation be rendered as something an operator was told.

So `NarrationEvent` is a new member of the envelope union, carrying the text, a `room` scope, `Provenance`, and the observation window it covers.

The window field is load-bearing rather than decorative.
Gemini samples at roughly one frame per second, so narration is a sequence of observations and not continuous tracking, and the root `CLAUDE.md` requires that limit to be carried in the data rather than only stated in a comment.
`room` is present for the same reason: one fixed camera sees one room, and a scoped claim must not be presentable as an unscoped one by accident.

`caller` may later quote a narration line to an operator. When it does, that becomes a `TranscriptLine` whose `claim_ids` point back at the narration it repeats, which is the existing mechanism for exactly this and needs nothing new.

## 4. Cross-app controls

The property being built is that a control does the same thing from any surface, and the other two see it happen.
That falls out of routing every control through `HubRuntime.emit()`.

| Control | Endpoint | State |
|---|---|---|
| Start incident | `POST /v1/incident` | exists |
| Add context | `POST /v1/incident/{id}/context` | exists |
| Remember visitor | `POST /v1/household/remember` | exists |
| Dismiss notice | `POST /v1/notice/{id}/dismiss` | **new** |
| Shutter open / close | `POST /v1/shutter` | **new** |

Dismiss is new because today `HawkEyeClienting.dismissNotice` is local to the phone, so a notice cleared on one surface stays up on the others.
It becomes a server-side fact with a `NoticeEvent` carrying a dismissed state.

Shutter is new and is the hero control.
It asks `master` for a grant, the grant travels down the edge link, the Pi forwards it to the local shutter agent, the servo moves, and the attested position travels back up.
The backend emits a new `ShieldEvent` carrying that attestation, so all three surfaces show the shield state and, importantly, show a refusal when the grant does not verify.

`app/ios/HawkEye/Models/Shield.swift` already exists untracked and is the client half of this.

## 5. The web console becomes the third surface

New `app/web/live/`, served alongside `/replay`.

An `<img>` pointed at `/v1/camera/live`, a `WS /v1/stream` subscription for narration, notices, verifications and shield state, and the four controls from section 4.

This page is what makes the claim demonstrable rather than asserted.
Press Start Incident in a browser and watch it land on a wrist.

## 6. MongoDB as the primary store

`store.py:287` currently carries a docstring arguing against exactly this, on the grounds that Atlas has no room inside the 0.3 second motion claim.
That reasoning is sound and the shape below is what honours both it and the decision to make Mongo primary.
The docstring is rewritten rather than left contradicting the code, because a judge can read it.

`MongoStore` implements the existing `Store` protocol and wraps `InMemoryStore` as a hot cache.

- **Reads** are served from memory. No Atlas round trip on the incident path.
- **Writes** land in memory immediately and reach Atlas through a background queue.
- **Startup** hydrates memory from Atlas, so state genuinely outlives the process.

Atlas is the source of truth. Memory is the cache in front of it.
Every method maps onto one collection keyed by `incident_id`, with `events` capped at the same size as the in-memory buffer, which is what the existing docstring already specified.

A queue that cannot drain is surfaced, not swallowed. `GET /v1/hub` reports the write backlog, on the same principle as the replay archive's `ArchiveStatus`: a service that claims to be persisting and is not is the exact failure this project is built against.

## 7. Honest degradation

From the project's honesty rule: a frozen frame reads as a live empty room, which is the most dangerous possible lie for this system to tell.

When the edge link drops, every camera surface says **camera unreachable** and shows the age of the last frame.
It does not show the last frame as if it were current.

`CameraStatus` is added to `GET /v1/hub` and pushed on the stream, carrying: linked or not, last frame age, and frames-per-second over the last ten seconds.

The same applies to the other three real parts. Gemini unreachable means narration stops and says so, rather than repeating its last line. Atlas unreachable means the backlog is reported. The shutter unreachable means the shield state reads unknown, never open and never closed.

## 8. Build order

Ordered so the riskiest unknown dies first.

1. **Prove the hop.** The Pi dials the Mac, one frame lands, `curl /v1/camera/still` returns a JPEG. Nothing else is built until this works, and it fails loudly by naming which hop is down.
2. **MJPEG egress and the web live page.** First moving picture on a screen that is not the Mac's.
3. **Vision on the Mac** through `RelayFrameSource`; narration on the stream and on all three surfaces.
4. **The shutter grant** down the link, the attestation back up, the refusal path rendered.
5. **The four cross-app controls**, on all three surfaces.
6. **Mongo as the primary store.**

Each step is independently demoable. Steps 1 through 4 are the demo; steps 5 and 6 are the submission.

## 9. Testing

- **Backend.** A fake edge-link client drives ingest; assert frames fan out, assert the MJPEG boundary format, assert a slow consumer is dropped rather than blocking the camera.
- **Cross-app.** One test per control asserting that a request produces exactly one envelope and that every subscriber receives it. This is the property the whole design exists for and it deserves a direct test rather than an inferred one.
- **Vision.** The existing suite is unchanged. `RelayFrameSource` gets its own tests against a fixture server.
- **Degradation.** A test that kills the link and asserts the surface reports unreachable rather than serving a stale frame. This is the honesty rule with a test behind it.
- **Store.** The existing `Store` protocol tests run against `MongoStore` unchanged, which is what the protocol is for. Plus a test that a write survives a simulated restart.

## 10. Documentation

- `docs/swapping-in-real-parts.md` gains four rows: camera, Gemini, servo, Atlas. Each names its seam, how to flip it, how to tell the flip worked, and which half-flipped state looks like something else.
- A network runbook covering the three cases, with the client-isolation test as its first step.
- Root `CLAUDE.md` gains the topology diagram from section 1.

## Scope

Six build steps is more than one implementation plan should carry.
The natural split is steps 1 through 4, which are the demo and share the edge link as their subject, and steps 5 and 6, which are the cross-app controls and the store and depend on nothing in each other.
Each half gets its own plan.

## What this does not do

- It does not build the live agent mesh path. `LiveMasterClient` still targets an HTTP surface `agents/master` does not serve, and closing that is separate work.
- It does not do face recognition, and nothing in it changes the four limits in the root `CLAUDE.md`.
- It does not add a recorded fallback for a failed demo. That is recommended and out of scope here.
