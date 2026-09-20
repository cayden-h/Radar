# Hawk Eye, watchOS

The actor.
It gets the notification, it is where an incident is started, and it holds nothing.
Read `app/CLAUDE.md` for what the watch is for, and the root `CLAUDE.md` for the project.

## Why it is here and not in `app/watch/`

`app/CLAUDE.md` names `app/watch/` as the watch app, and that is still the right way to talk about it.
On disk it is a second target in the same XcodeGen project as the phone, for one reason: it shares `HawkEye/Models/`, `HawkEye/Shared/` and `HawkEye/DesignSystem/` by source path.

One project generating two targets means there is exactly one definition of every wire type and one copy of the palette.
Two sibling directories with their own projects means either duplicated model files or a Swift package, and `app/ios/README.md` already explains why there is no package here.

## Building and running

```sh
cd app/ios
xcodegen generate
xcodebuild -project HawkEye.xcodeproj -scheme HawkEyeWatch \
  -destination 'platform=watchOS Simulator,name=Apple Watch Series 12 (46mm)' build
```

The watchOS simulator runtime is a separate download from Xcode itself.
If `xcrun simctl list runtimes` shows no watchOS entry, run `xcodebuild -downloadPlatform watchOS` once.

Re-run `xcodegen generate` after adding, removing or moving a Swift file.

## The mock link

`WatchConfig.useMockLink` is the watch's half of `Config.useMocks`.

```swift
static let useMockLink = true
```

`true` runs all three screens off `MockWatchFeed` with no phone and no hub at all.
`false` runs the identical UI off snapshots relayed from the phone.

It exists because pairing a watch simulator to a phone simulator is fiddly and sometimes simply refuses, and the demo must never depend on that working.
The mock publishes the same `WatchSnapshot` the phone publishes, so no view can tell the difference and there is no demo branch anywhere in a view.

The script is the timing budget from the root `CLAUDE.md`: shield closed, grant at six seconds, servo clears the lens, and the camera's first sentence lands about two seconds later.

## Three screens

`app/CLAUDE.md` describes four.
The live-incident screen is deliberately not one of them here: the call, the transcript and the takeover control are the phone's, and a wrist that offers a second way to end a call is a misfire waiting to happen.
The watch says an incident is open and points at the phone.

1. **Idle.** Armed, where the shield is, and when it last moved
2. **Notice.** The still frame, the camera's sentence, and two controls
3. **Saved.** What the hub did with the answer the resident gave

`WatchRouter` decides which, as a pure function of the snapshot and the clock.
It is tested in `HawkEyeTests` on the iOS runtime, because the rule is platform-neutral and the watch runtime is a large download that a CI box may not have.

## Two controls, not three

**Start Incident** is held for 1.5 seconds, because an accidental press calls 911.
**This is expected** is a single tap, because its worst case is a banner going away.

**Remember this visitor** is deliberately absent. It names a person, naming needs a keyboard, and it changes what the house believes rather than muting one session.
The Saved screen says to use the phone for it rather than leaving the resident wondering where it went.

## What the watch may claim

- It says **Armed** only when the phone is actually holding the hub. A watch that says armed while disconnected is claiming something is watching when nothing is
- It says **Recorded** only after the hub has acknowledged, never optimistically on send
- A notice with no narration is **not shown at all**. The camera's sentence is the entire point of the notification, and a buzz that says nothing specific trains the resident to ignore the next one
- Anything drawn from `SimulatedCameraFrame` carries `simulated` in the data and the view draws a marker off that flag

## The notification

The notice arrives as a **local notification raised by the watch**, not a push.
The phone relays the notice over WatchConnectivity and `NoticeNotifier` posts it here.

That means no APNs, no push server and no paid developer account.
The root `CLAUDE.md` and `app/CLAUDE.md` both say push was considered and not shipped, and that is still true: nothing in this app talks to Apple's push service.

Two looks, and both are ours:

- **Short look.** The system banner, carrying the title and the camera's sentence
- **Long look.** `NoticeNotificationView`, registered as a `WKNotificationScene` against `NoticeNotifier.category`. The still frame, the sentence, and the `SIMULATED` marker drawn off the data flag

**The long look has no action buttons, deliberately.**
A one-tap Start Incident on a notification would bypass the 1.5 second hold, and the hold exists because a wrist is trivially easy to press by accident.
Tapping the notification opens the app, where both controls live with the right protection on each.
"This is expected" would be legitimate as an action, since a single tap is already how it works in the app, and it is the only one worth adding.

### Where the still frame comes from

The long look runs in the app process on watchOS, so it reads the frame out of `NoticeNotifier.frames`, keyed by notice id.
Nothing is re-encoded into the notification payload, which matters: a real APNs payload is capped at 4KB and a usable JPEG will not fit.

`UNNotificationAttachment` is the fallback, for a notification this process did not raise itself.
If neither is available the view says the shield stayed closed and there is no picture, which is the honest answer rather than a grey rectangle.

### Seeing one

Authorization is requested at launch and **has to be granted by hand** the first time.
`xcrun simctl privacy` has no `notifications` service, so there is no way to grant it from a script; tap Allow on the watch.

After that, launching the app is enough: the mock feed raises the notice about eight seconds in and the notification follows.
Notifications are presented even while the app is open, because watchOS otherwise suppresses a notification whose app is in the foreground and the long look would never be reachable.

To fire one by hand:

```sh
xcrun simctl push <watch-udid> tech.cayden.hawkeye.app.watchkitapp notice.apns
```

with `"category": "hawkeye.notice"` in the payload so the custom long look is used, and `"notice_id"` matching a notice the app has already seen if you want the frame to appear.

## Haptics

The notice buzzes. Nothing else does.

That is the whole reason the watch is the notification surface: it wakes someone who is asleep or in another room.
The hold confirmation is silent by contrast, because the resident is already looking at the screen by then, and an intrusion is exactly the situation where noise may be unsafe.
No call audio is ever played on the watch, per `app/CLAUDE.md`.
