# Vouching for a person on the camera

Written 2026-09-20. Built the same day.

## What it is

The resident taps a box on the live camera feed in the iOS app, types a name, and that person stops being counted as unaccounted for.
It lasts as long as the tracker holds them, plus a minute.
Nothing persists.

## What it is not, and why the name matters

It is not authentication, and the word does not appear anywhere in the code.

Nothing verifies a credential.
`vision` cannot say who anybody is, and the root `CLAUDE.md` honesty rule forbids it acquiring a face database.
What is recorded is that a human looked at a picture and vouched for the person in it.

Calling it authentication would put the one unbacked claim in a project whose entire argument is that it never makes any.
The vocabulary already existed in `app/CLAUDE.md`: *"This is expected vouches for that presence for this session and nothing persists."*
This is that control, pointed at a camera box rather than a radio presence.

## Where each piece lives

The hub owns the ledger.

`models/camera.py` already states the rule that settles this: a `track_id` is a rendering detail arriving at camera frame rate, not a claim.
The hub is the only process that ever sees one, because `agents/vision` posts boxes there and nowhere else.
So bookkeeping keyed to a track id belongs in the hub, next to the boxes.

- `app/backend/hawkeye_backend/edge/vouch.py` - `VouchLedger`. Pure, clock-injected, holds the grace window.
- `app/backend/hawkeye_backend/models/camera.py` - `PersonVouch`, `VouchRequest`, `TracksSnapshot`.
- `GET /v1/camera/tracks` - boxes plus vouch state. Polled, never pushed.
- `POST /v1/camera/vouch`, `DELETE /v1/camera/vouch/{track_id}`.
- `app/ios/HawkEye/Models/CameraTracks.swift` - the wire types and the letterbox geometry.
- `app/ios/HawkEye/Features/Home/TrackOverlay.swift` - the tappable boxes and the naming sheet.

## Three decisions worth keeping

**Polled, not pushed.**
`POST /camera/tracks` already argues that geometry must stay off the event stream, because boxes arrive at camera rate and would bury an incident under several hundred messages a minute.
A phone looking at the camera polls a few times a second; nothing else pays for it.

**The phone draws its own boxes; nothing else changes.**
`annotate.py` keeps burning boxes into the MJPEG for the browser and the watch.
The phone is the one surface where a box is a control rather than a picture, so it asks for the raw frame (`?raw=true`) and draws SwiftUI shapes over it.
Without the raw flag every person gets two rectangles, slightly out of step, because the burned-in one was measured on an older frame.

**The subtraction happens where the hub already subtracts.**
`HubRuntime.emit` computes `unaccounted_count(people, known_devices_present)` to decide whether a notice fires.
A vouched person is an accounted-for body in exactly the sense a resident's associated phone is, so held vouches are added to the same term.
One place decides what "accounted for" means, and a vouch cannot drift away from what a device does.

## The holes, named

**Recycled track ids.**
BoT-SORT can hand a different person an id inside the grace window, and that person inherits the vouch.
This is why the window is 60 seconds and not an hour.
A vouch is a human pointing at a box, keyed to a tracker id, and never an identity claim.

**Two namespaces meet in the sum.**
`people` counts radio presences; a vouch is keyed to a camera track.
One fixed camera sees one room, so in the demo geometry a vouched person and a resolved presence are the same body.
This is not a general identity mapping and must not be treated as one if a second camera ever appears.
It can only ever lower an alarm - `unaccounted_count` floors at zero - so an over-count suppresses a banner and can never manufacture one.

**Only held vouches count.**
A vouch inside its grace window belongs to somebody who has left frame.
Suppressing a notice on the strength of a person who may no longer be in the room is the direction this must never fail in.

## Tested

- `app/backend/tests/test_camera_vouch.py` - the ledger's whole lifecycle against an injected clock, plus the endpoints.
- `app/backend/tests/test_notice_runtime.py` - the consequence: a vouch suppresses the notice, a lapsed one does not, a revoked one does not, and an over-count cannot raise one.
- `app/ios/HawkEyeTests/TrackGeometryTests.swift` - the letterbox arithmetic, which is the piece that fails quietly.

## Not done

The vouch does not reach `agents/master`, so it does not change `classify()`.
Today it suppresses the notice and labels the box.
Forwarding it would let `master` seal "the resident vouched for Jordan at 21:04" into the replay record alongside `intruder`'s raw verdict, which is the version an investigator should see.
