# docs/hardware/

Hawk Eye hardware guides.
Written for someone with no prior context who has to make the CSI capture path work, possibly at 2am.

Read `sensor/CLAUDE.md` for why the capture path is shaped this way.
These guides are the how.
Where a guide and `sensor/CLAUDE.md` disagree, `sensor/CLAUDE.md` wins and the guide is the bug.

## No further hardware is being purchased

This is settled.
The list below is the complete list.
Do not plan around an ESP32, a gas sensor, an SDR, a second Pi, a second camera, or a different router.
If something on this list does not work, the answer is the fallback ladder in `sensor/CLAUDE.md`, not a shopping trip.

## Bill of materials

Everything here is already owned.

- Raspberry Pi 4B kit: Pi 4B, USB ethernet adapter, Cat5 cable, microSD card, USB-C 5V/3A power supply
- TP-Link Archer AX1450 dual-band Wi-Fi 6 router, bought for this project
- **Logitech USB webcam**, on the Pi. The primary sensor after the 2026-09-19 pivot
- **TowerPro SG92R micro servo**, carrying the camera shield, on the Pi's GPIO
- A separate 5V supply for the servo. **Not the Pi's 5V rail**; see the servo guide
- The MacBook, used as the traffic generator and as the dev machine

**If the router ends up with Wi-Fi but no uplink**, read "What actually needs internet, and what
survives without it" in [assembly-and-placement.md](assembly-and-placement.md) before assuming the
demo is dead. The sensing path, the app, and the SMS all survive it. The 911 call does not.

There is no gas sensor and there is no longer anything that wants one.
The Fire incident type and the simulated gas reading were both cut in the 2026-09-19 pivot. See `docs/PIVOT.md`.

## What each item is for

| Item | Role in the system | Guide | The way it fails quietly |
|---|---|---|---|
| Raspberry Pi 4B | Runs `nexmon_csi` on its BCM43455c0 chip and is the only thing in the project that actually measures CSI | [raspberry-pi-4b.md](raspberry-pi-4b.md) | The firmware patch builds and installs cleanly, then emits all-zero or garbage CSI because the kernel version is outside 4.19 / 5.4 / 5.10. Nothing errors. |
| USB ethernet adapter and Cat5 | The Pi's only network path while capturing | [raspberry-pi-4b.md](raspberry-pi-4b.md), [assembly-and-placement.md](assembly-and-placement.md) | You plan to SSH over Wi-Fi, start the capture, and lose the Pi. `nexmon_csi` holds wlan0 in monitor mode so there is no station interface. |
| microSD card | The whole working system lives here | [raspberry-pi-4b.md](raspberry-pi-4b.md) | It corrupts at 4am and there is no `dd` image. Image the card the moment CSI flows. |
| USB-C 5V/3A supply | Pi power | [assembly-and-placement.md](assembly-and-placement.md) | Powered from a router or laptop USB port instead, the Pi browns out under load and corrupts the SD card rather than rebooting visibly. |
| TP-Link Archer AX1450 | The transmitter whose channel the Pi measures | [router-archer-ax1450.md](router-archer-ax1450.md) | Auto channel or band steering is left on. The generator wanders off the monitored channel, or the router hops mid-take, and the capture is empty while every component reports healthy. |
| The MacBook | Traffic generator, plus dev machine and venue Internet Sharing host | [macbook-traffic-generator.md](macbook-traffic-generator.md) | Nobody starts the ping. CSI updates only on beacons at roughly 10 Hz, which is too coarse for a short motion transient and for heart rate, and the pipeline reports healthy the whole time. |
| Logitech USB webcam | The primary sensor. `vision/` reads it, and only while `shutter/` attests the shield is clear | [logitech-camera.md](logitech-camera.md) | Auto-exposure is left on, so the narration contradicts itself between frames on a live call. Or the shield does not fully cover the lens and the privacy claim is quietly false. |
| TowerPro SG92R servo | Moves the shield off the lens, and only on a verified grant | [servo-sg92r.md](servo-sg92r.md) | Powered from the Pi's 5V rail. It stalls at over 700mA, the Pi browns out, and the failure presents as the camera or the CSI capture dying for no stated reason. |
| Physical placement | Determines whether people are in the measured path at all | [assembly-and-placement.md](assembly-and-placement.md) | Router and Pi end up side by side on one table. The capture goes flat and looks exactly like a failed firmware patch, so you spend the night debugging the wrong thing. |

## Do this in this order

Do not reorder these.
Steps 1 and 2 exist so that step 4 has something to measure, and step 4 is the one that eats the night.

1. Read `sensor/CLAUDE.md` end to end. Especially the "The risk, stated plainly" and "Fallback ladder" sections, because those decide when you stop.
2. Set up the router: [router-archer-ax1450.md](router-archer-ax1450.md). Fixed channel, 80MHz, 802.11ac forced, band steering off. Do this first because the Pi's capture parameters have to match the router's channel exactly.
3. Flash and boot the Pi: [raspberry-pi-4b.md](raspberry-pi-4b.md), through first boot and the `uname -r` check. Stop and verify the kernel version before building anything.
4. Place the hardware: [assembly-and-placement.md](assembly-and-placement.md). Do this before building the firmware patch, so that the first CSI you ever see is from a geometry that can actually produce a signal.
5. Build and install `nexmon_csi`: back to [raspberry-pi-4b.md](raspberry-pi-4b.md).
6. Start the traffic generator: [macbook-traffic-generator.md](macbook-traffic-generator.md). Without this the next step will look like a failure.
7. Verify CSI is flowing and image the microSD card immediately: [bring-up-checklist.md](bring-up-checklist.md).
8. **Wire and calibrate the servo**: [servo-sg92r.md](servo-sg92r.md). Power it from its own supply before you do anything else, because a brownout here looks like a fault in steps 3 to 7 and will send you back to the start.
9. **Mount and configure the camera**: [logitech-camera.md](logitech-camera.md). Fix the exposure, and verify the closed shield actually produces a black frame.

Steps 8 and 9 are new with the 2026-09-19 pivot and they come last on purpose: the camera path can be developed against a fixture video file on a laptop, so it is not blocked on any of the above.

The single linear version of all of this, with a checkbox and a verification command per step, is [bring-up-checklist.md](bring-up-checklist.md).
Use that one while you are actually doing the work, and the per-item guides when a step fails.

## Files in this folder

- [README.md](README.md) - this index
- [raspberry-pi-4b.md](raspberry-pi-4b.md) - the Pi, the OS image, `nexmon_csi`, monitor mode, and CSI verification
- [router-archer-ax1450.md](router-archer-ax1450.md) - router configuration, menu path by menu path
- [macbook-traffic-generator.md](macbook-traffic-generator.md) - why the ping matters and how to run and verify it
- [assembly-and-placement.md](assembly-and-placement.md) - wiring, geometry, mounting, and power
- [bring-up-checklist.md](bring-up-checklist.md) - one linear checklist from unboxed to CSI flowing
- [servo-sg92r.md](servo-sg92r.md) - the camera shield servo, its power, and the way it browns out a Pi
- [logitech-camera.md](logitech-camera.md) - the camera, exposure, the two capture paths, and the black-frame check
- [no-uplink-setup.md](no-uplink-setup.md) - what to do when there is no ethernet wall jack, and the demo scope decisions that follow

## A physics note that belongs on every page

CSI measures how a radio channel is perturbed.
It can sense motion, presence, coarse position, posture change, and chest-wall displacement.
It cannot sense gas composition, at any price, on this hardware.
Oxygen absorption is a roughly 60 GHz phenomenon and the BCM43455c0 is a 2.4/5 GHz radio.

**After the 2026-09-19 pivot we use exactly one of the things it can do: motion.**
Everything else is the camera's job now. If a guide in this folder still implies otherwise, that guide is the bug.
Never write or say anything that implies otherwise.
