# docs/hardware/

Hawk Eye hardware guides.
Written for someone with no prior context who has to make the CSI capture path work, possibly at 2am.

Read `sensor/CLAUDE.md` for why the capture path is shaped this way.
These guides are the how.
Where a guide and `sensor/CLAUDE.md` disagree, `sensor/CLAUDE.md` wins and the guide is the bug.

## No further hardware is being purchased

This is settled.
The list below is the complete list.
Do not plan around an ESP32, a gas sensor, an SDR, a second Pi, or a different router.
If something on this list does not work, the answer is the fallback ladder in `sensor/CLAUDE.md`, not a shopping trip.

## Bill of materials

Everything here is already owned.

- Raspberry Pi 4B kit: Pi 4B, USB ethernet adapter, Cat5 cable, microSD card, USB-C 5V/3A power supply
- TP-Link Archer AX1450 dual-band Wi-Fi 6 router, bought for this project
- The MacBook, used as the traffic generator and as the dev machine

**If the router ends up with Wi-Fi but no uplink**, read "What actually needs internet, and what
survives without it" in [assembly-and-placement.md](assembly-and-placement.md) before assuming the
demo is dead. The sensing path, the app, and the SMS all survive it. The 911 call does not.

There is no gas sensor.
`agents/environment` ships a simulated reading labeled `demo-trigger` in the data itself.
See `sensor/CLAUDE.md`.

## What each item is for

| Item | Role in the system | Guide | The way it fails quietly |
|---|---|---|---|
| Raspberry Pi 4B | Runs `nexmon_csi` on its BCM43455c0 chip and is the only thing in the project that actually measures CSI | [raspberry-pi-4b.md](raspberry-pi-4b.md) | The firmware patch builds and installs cleanly, then emits all-zero or garbage CSI because the kernel version is outside 4.19 / 5.4 / 5.10. Nothing errors. |
| USB ethernet adapter and Cat5 | The Pi's only network path while capturing | [raspberry-pi-4b.md](raspberry-pi-4b.md), [assembly-and-placement.md](assembly-and-placement.md) | You plan to SSH over Wi-Fi, start the capture, and lose the Pi. `nexmon_csi` holds wlan0 in monitor mode so there is no station interface. |
| microSD card | The whole working system lives here | [raspberry-pi-4b.md](raspberry-pi-4b.md) | It corrupts at 4am and there is no `dd` image. Image the card the moment CSI flows. |
| USB-C 5V/3A supply | Pi power | [assembly-and-placement.md](assembly-and-placement.md) | Powered from a router or laptop USB port instead, the Pi browns out under load and corrupts the SD card rather than rebooting visibly. |
| TP-Link Archer AX1450 | The transmitter whose channel the Pi measures | [router-archer-ax1450.md](router-archer-ax1450.md) | Auto channel or band steering is left on. The generator wanders off the monitored channel, or the router hops mid-take, and the capture is empty while every component reports healthy. |
| The MacBook | Traffic generator, plus dev machine and venue Internet Sharing host | [macbook-traffic-generator.md](macbook-traffic-generator.md) | Nobody starts the ping. CSI updates only on beacons at roughly 10 Hz, which is too coarse for collapse and heart rate, and the pipeline reports healthy the whole time. |
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

The single linear version of all of this, with a checkbox and a verification command per step, is [bring-up-checklist.md](bring-up-checklist.md).
Use that one while you are actually doing the work, and the per-item guides when a step fails.

## Files in this folder

- [README.md](README.md) - this index
- [raspberry-pi-4b.md](raspberry-pi-4b.md) - the Pi, the OS image, `nexmon_csi`, monitor mode, and CSI verification
- [router-archer-ax1450.md](router-archer-ax1450.md) - router configuration, menu path by menu path
- [macbook-traffic-generator.md](macbook-traffic-generator.md) - why the ping matters and how to run and verify it
- [assembly-and-placement.md](assembly-and-placement.md) - wiring, geometry, mounting, and power
- [bring-up-checklist.md](bring-up-checklist.md) - one linear checklist from unboxed to CSI flowing

## A physics note that belongs on every page

CSI measures how a radio channel is perturbed.
It can sense motion, presence, coarse position, posture change, and chest-wall displacement.
It cannot sense gas composition, at any price, on this hardware.
Oxygen absorption is a roughly 60 GHz phenomenon and the BCM43455c0 is a 2.4/5 GHz radio.
Never write or say anything that implies otherwise.
