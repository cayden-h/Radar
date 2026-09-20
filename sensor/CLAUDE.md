# sensor/

Hawk Eye's sensing layer. Raspberry Pi 4B CSI capture and the small answer it produces.

**Read `docs/PIVOT.md` before this file if you have prior context on this repo.**
On 2026-09-19 this layer was demoted. It used to be the project's primary sensor and it is now its trigger.

Read the root `CLAUDE.md` first for why this exists.

**Procedure lives in `docs/hardware/`.**
This file is the contract, the constraints and the reasoning.
The commands are in `docs/hardware/raspberry-pi-4b.md`, `docs/hardware/router-archer-ax1450.md`, `docs/hardware/macbook-traffic-generator.md` and `docs/hardware/assembly-and-placement.md`.
`docs/hardware/bring-up-checklist.md` is the linear path from unboxed hardware to CSI frames flowing.
If a value here and a value there disagree, this file wins and the guide is the bug.

**The camera and the servo also hang off this Pi.** They are not this file's subject: see `vision/CLAUDE.md`, `shutter/CLAUDE.md`, and the two new guides in `docs/hardware/`.
What this file owes them is the power and USB budget, which is in the hardware section below.

## Job

**Two questions. That is the entire contract.**

- **Did something move, and in which enrolled zone?**
- **How confident are we that it moved, and for how long has it been moving?**

That is it. `agents/presence` consumes those two answers and nothing else.

### What this layer used to do and no longer does

All of it was cut on 2026-09-19. None of it may be described as a current capability.

| Cut | Why |
|---|---|
| Occupancy and headcount | A 1x1 radio has no spatial diversity. Two people within a metre merged. The count actually came from device association, and that survives inside `agents/presence` |
| Body type, adult / child / pet | Depended on respiration rate bands that we could barely resolve |
| Biometrics, breathing rate | The central pre-pivot claim, and the one with the most caveats attached. The camera answers the underlying question better and can be checked afterward |
| Responsiveness, `respiration_lost` | Same |
| Fall detection | Cut earlier the same day, for its own reasons |
| The gas sensor driver | `environment` was merged into `master` and then deleted with the Fire incident type. No gas sensor was ever purchased |

**Motion is what survived, and the reason is worth knowing: motion sensing is the only CSI capability that is environment-independent.**
It needs no baseline, no calibration and no enrollment to say that something changed.
Everything else on that list needed a reference that decays as a room fills with people, which is exactly why none of it survived contact with a judging hall.

Resist the temptation to ship RuView's full capability surface.
17-keypoint pose is impressive and changes nothing about the demo. Room fingerprinting, activity classification, gesture recognition and heart rate are all out of scope, and now so is breathing.

## Hardware

- Raspberry Pi 4B, chip BCM43455c0
- microSD, USB-C power, ethernet adapter, Cat5
- A router to sense against

The Pi connects to the network over **ethernet**, not WiFi.
This is not optional.
`nexmon_csi` puts the WiFi interface into a monitor-adjacent state; you cannot both capture CSI and rely on that interface for connectivity.
Plan on SSH over the Cat5 cable for the entire event.

## Demo network topology

Settled 2026-09-19. Two configurations; the first is the one we film with.

### At the house (primary, and what the demo video uses)

```
home router / modem
   └─ Cat5 ─► demo router WAN
                demo router LAN ─ Cat5 ─► Pi eth0
                demo router 5GHz ────────► traffic generator (phone or laptop)
```

No MacBook. The Internet Sharing chain exists only to give a router a wired uplink where none exists, and at the house the uplink is already ethernet.
Dropping it removes three failure points: macOS Internet Sharing, the USB Ethernet adapter, and the 192.168.2.x subnet collision.

Double NAT is fine. All agent traffic is outbound to Vultr.

**Channel separation matters here.** The Pi monitors exactly one channel, so if the demo router and the household's existing network share it, household traffic contaminates the capture.
Check what the home network is on and take a different non-DFS channel.

**Decide before filming whether the Pi needs internet at all.** If the sensing agents run on a laptop on the same LAN rather than on Vultr, the uplink stops mattering during the take, which is one less thing that can break on camera.

### At a venue (judging table)

We are demoing live at judging, and after the pivot **the sensing trigger is part of it.**

This changed with the pivot and it changed in our favour.
Everything that could not survive a judging hall - counting, localization, respiration - needed a baseline, and a hall cannot supply a usable one: the baseline decays as the room fills because bodies are reflectors, and occupancy assumes a bounded space that an open hall does not have.

**Motion needs no baseline at all**, which is exactly why it is the one capability that survives a crowded room we did not calibrate in, and why it is now the only one we have.
So the venue demo can run the real trigger: someone moves near the router, `presence` fires, `intruder` finds no device, and the shield opens on the table.

Zone labelling still needs the enrollment walk and does not survive the hall, so at the venue the zone is fixed to one and the demo says so.
The agents run live from Vultr. See `agents/CLAUDE.md`.

The Pi and router still come along, for a prop and for one honest live bit: **movement response.** No calibration, no baseline, no through-wall claim. A judge waves a hand and the signal moves.

The chain below is what the Pi needs if it is powered up at the venue at all.



```
venue Wi-Fi or phone hotspot
   └─► MacBook (macOS Internet Sharing: Wi-Fi source ─► USB Ethernet)
          └─ Cat5 ─► demo router WAN
                       demo router LAN ─ Cat5 ─► Pi eth0
                       demo router 5GHz ────────► traffic generator
```

Constraints that apply to this path:

- **Router LAN subnet must not be 192.168.2.x.** It collides with macOS Internet Sharing's NAT range.
- **Captive-portal venue Wi-Fi cannot be shared.** Fallback is USB tethering a phone and sharing that.

### Constraints that apply to both

- **Pi power: the kit's 5V/3A wall supply, always.** The Pi 4B's USB-C is power-only. Never power the Pi from a router USB port; it browns out and corrupts the SD card.
- **The Pi's network path is wired eth0, not Wi-Fi.** `nexmon_csi` holds wlan0 in monitor mode, so there is no station interface while sensing. This is what the Cat5 cable is for.

## The router

Not in the original kit. Bought for this.

Requirements, in priority order:

1. **Fixed channel, auto-channel off.** A channel change mid-run invalidates the calibration baseline instantly.
2. **Ability to force 802.11ac.** `nexmon_csi` extracts CSI from 802.11a/g/n/ac frames only. HE (WiFi 6) and EHT (WiFi 7) frames yield nothing.
3. **Fixed bandwidth.**
4. **Separate 2.4 and 5GHz SSIDs, band steering off.** Otherwise the traffic generator wanders to the band the Pi is not watching.

**Reject all mesh systems** (Deco, Orbi, Nest). They force band steering and auto channel and cannot be pinned down.

Prefer WiFi 6 over WiFi 7 hardware. TP-Link's 5GHz mode dropdown offers `802.11a/n/ac mixed`, which excludes ax outright. On WiFi 7 boxes you are hoping an equivalent toggle exists.

### Configuration, first boot

| Setting | Value | Why |
|---|---|---|
| Channel | 5GHz ch 36/40/44/48 | UNII-1, non-DFS. A DFS channel (52-144) can radar-detect and hop mid-take. |
| Auto channel | Off | See above. |
| Bandwidth | 80MHz | Most subcarriers, best motion resolution. Kept at 80 even though motion does not need it, because the recorded sessions are worth more at full width. |
| Mode | 802.11ac, ax disabled | See requirement 2. |
| Band steering | Off | Keeps the generator on the monitored band. |

If through-wall performance is poor at 5GHz, fall back to 2.4GHz ch 1 at 20MHz. Worse resolution, better penetration. Test both at the house.

## Traffic generator

**CSI is computed per received frame.** The chip measures the channel from an actual transmission crossing the air. No frames, no measurements, no matter how good the model is.

A router with nothing connected still beacons, but only about ten times a second:

| | Signal | Sample rate needed |
|---|---|---|
| Motion transient | 0.5-1s event | 10 Hz is too coarse to characterize |
| Motion detection, coarse | continuous | 10 Hz works, badly |

10 Hz is the floor and it is not enough to characterize a short transient, which after the pivot is the only thing we care about. Target 100+ Hz.

The pivot lowers the stakes here and does not remove them: a slow capture costs latency in the motion-to-wrist budget, and that budget is the demo.

### No hardware needed: use the MacBook

The MacBook only existed in the chain to do Internet Sharing at a venue. At the house the router's WAN goes straight to home internet, so the MacBook is free.

Put it on the router's Wi-Fi and point it at the gateway:

```sh
sudo ping -i 0.01 192.168.0.1     # 100 packets/sec
```

Every request and every reply is a frame crossing the monitored channel.
Fractional `-i` below 0.2s requires root on macOS, hence `sudo`.

A laptop beats a phone here: phone Wi-Fi power-save injects jitter that shows up as noise in the CSI. If only a phone is available, disable power saving and keep the screen awake.

**Correction, 2026-09-19:** earlier guidance said to generate traffic from the router over SSH. That assumed OpenWrt on a GL.iNet. **Stock TP-Link Archer firmware does not expose SSH**, so with the AX1450 the traffic must come from a client device.

### Geometry matters

The Pi measures the channel between **whoever transmitted** and itself.

Put the **router and the Pi on opposite sides of the space being sensed**, with people in between. Ping is useful here because both ends transmit, so you get two links rather than one.

The generator must be on the **same band and channel** the Pi monitors. This is why band steering has to be off.

## Capture path: nexmon_csi

Committed path as of 2026-09-18.
Upstream: https://github.com/seemoo-lab/nexmon_csi

Verified facts:

- BCM43455c0 firmware `7_45_189` covers Raspberry Pi 3B+/4B/5. Our Pi is in scope.
- Upstream's kernel-pinned patch supports **4.19, 5.4, and 5.10**, but **this is not the path we used.** See "Kernel reality, corrected 2026-09-19" below.
- Extracts CSI from OFDM-modulated 802.11a/g/n/ac frames, per frame, **up to 80 MHz bandwidth**.

### Kernel reality, corrected 2026-09-19

**Settled during live bring-up. This supersedes the kernel-pinning plan below; do not chase a 5.10 image.**

Raspberry Pi Imager's "Legacy, 32-bit" catalog entry no longer serves Bullseye/5.10. It now serves Bookworm with kernel `6.12.109+rpt-rpi-v8` (64-bit kernel, 32-bit/`armhf` userspace when you pick the 32-bit variant). Bullseye 32-bit was EOL'd May 2023 and isn't worth chasing down from an archive.

`nexmon_csi` has a second, actively-maintained build path for exactly this: `Makefile.rpi`, which uses `update-alternatives` for firmware switching instead of a kernel-version-bound driver patch, and works across recent kernels including 6.12. Verified working end-to-end on our exact chip/firmware (`bcm43455c0`, `7_45_189`) on a Pi 4B. Use `make -f Makefile.rpi install-firmware` (not `make install-firmware`), and see `docs/hardware/raspberry-pi-4b.md` for the full corrected step list, including two gaps the upstream discussion doesn't mention:

- The bundled ARM cross-compiler still needs `libisl.so.10`/`libmpfr.so.4`, which Bookworm no longer ships (same problem as the old path). Symlink the newer installed versions (`libisl.so.23`, `libmpfr.so.6`) to the old SONAMEs; this is a compiler ABI shim, not a runtime downgrade, and it works.
- The `bcm43-tools`' Python 2.7 dependency needs Debian's archived Stretch repo, and that repo's Release file is unsigned (8 years EOL). `apt-get update` will hard-fail on it unless the source line is marked `[trusted=yes]` - `--allow-unauthenticated` at install time is not sufficient by itself, because apt refuses to even index an unsigned repo's package list without it.

One practical consequence: because this path isn't kernel-version-bound, `apt-get full-upgrade` is safe here, unlike the old plan. No need to `apt-mark hold` the kernel packages.

### The risk, stated plainly

This was the single most likely thing to consume a night and produce nothing. **Resolved 2026-09-19: real, varying, non-zero CSI confirmed flowing** (see the recorded values below). The failure mode to still watch for, if this is ever redone: a firmware patch that builds, installs, and then yields all-zero or garbage CSI, with the cause buried in a kernel/firmware/MAC-filter mismatch.

Mitigations, in order:

1. **Flash a known-good OS image before doing anything else**, and use the `Makefile.rpi` path above rather than assuming a specific kernel. Verify with `uname -r` regardless - knowing what's actually on the card is still the point, even though this path tolerates more kernel variance.
2. **Image the working microSD the moment CSI flows.** `dd` it to a file on someone's laptop, and copy that file off the laptop too. If the card corrupts at 4am, that image is the difference between a demo and no demo. **Done 2026-09-19**, see recorded values below.
3. **Timebox it.** If CSI is not flowing by the deadline the team sets, drop to the fallback ladder below and do not look back.

### Recorded values, from the 2026-09-19 bring-up session

- OS: Raspberry Pi OS Bookworm, 32-bit (`armhf`) userspace, kernel `6.12.109+rpt-rpi-v8`.
- Hostname / user: `radar-pi` / `radar`. SSH key-based (`~/.ssh/id_ed25519_radar_pi` on the bring-up Mac, alias `radar-pi`).
- Router SSIDs: `Radar` (2.4GHz), `Radar-5g` (5GHz). Channel 40, 80MHz.
- **The router's over-the-air radio MAC is not the MAC printed on its label.** The AX1450 uses a different MAC per band/radio; the label MAC was off by one in the last octet from the actual `Radar-5g` BSSID. Get the real one from a scan (`iw dev wlan0 scan`) with monitor mode off, not from the label, or `makecsiparams -m` silently filters on a device that's never transmitting and yields zero packets with no error.
- `makecsiparams` path: `~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams` (built from source in that dir, not on `PATH` by default).
- Filtering `-m` on the traffic-generator device's own MAC (rather than the router's) gave a more reliable capture rate in practice - the router didn't reliably reply to ICMP directed at its own gateway address, but the generator's outgoing request frames are transmitted regardless of whether anything replies.
- Achieved rate: roughly 30-70 packets/sec with a laptop pinging at `-i 0.01` on the same 5GHz band, well above the 10Hz beacon-only floor. Short of the 100+/sec target; not yet root-caused, plausibly 802.11 frame aggregation reducing distinct-frame count below the raw ping rate.
- Disk image and a CSI replay pcap exist, stored off the bring-up laptop's primary disk per the checklist's own warning about this being the step people skip.

### Fallback ladder

Descend only when the level above is timeboxed out.

1. `nexmon_csi` on the Pi, live CSI from the router. The real thing. **Achieved 2026-09-19.**
2. **Recorded CSI replay.** Capture a real session early, while the patch is working, and replay it through the same pipeline. The downstream agents cannot tell the difference. **Do this even if level 1 is healthy.** A first session was captured 2026-09-19; capture a longer one during the house shoot, covering a person entering an empty room, which is the only shape the pivot needs.

   Note that the demo is a recorded video shot at the house, so level 1 only has to work once, on camera, rather than on demand in front of judges. That materially lowers the risk this path carries.
3. **RuView's simulated data.** `docker pull ruvnet/wifi-densepose:latest` runs the pipeline on synthetic CSI. Honest fallback, but say so on stage rather than implying live hardware.
ESP32-S3 nodes were RuView's primary supported path and much lower risk than nexmon, but no hardware is being purchased, so they are off the table. Levels 1 through 3 are the whole ladder.

Whichever level we land on, **the agent layer must not know which one it is.** `sensor/` exposes one interface; what is behind it is our problem.

## Output contract

The only thing the agent layer may consume.
Keep it small and keep it stable.

**After the pivot it is much smaller, and that is the point.** A contract this size is hard to overclaim against.

```json
{
  "site_id": "...",
  "captured_at": "2026-09-20T04:12:33Z",
  "sensor_identity": "<ANS name of this device>",
  "health": { "frames_per_s": 46.2, "healthy": true },

  "motion": {
    "detected": true,
    "zone": "living_room",
    "confidence": 0.84,
    "continuous_for_s": 3.1
  }
}
```

Four rules about this object:

1. **`motion.detected` is not a claim that a person is present.** It never was. A curtain, a fan and a pet all produce it. Downstream, `agents/presence` passes it through as motion and `agents/master` must not promote it into a person claim. The camera is what decides personhood now
2. **`zone` comes from the enrollment walk**, never from inference. See the rooms section below
3. **`health` is a first-class field, not diagnostics.** The failure mode that costs us the demo is a capture path that is alive and producing nothing, and a frame rate in the output is what makes that visible. See the ingest section
4. **There is no confidence-free path.** A detection without a confidence is a bug, not a default

### What health actually has to catch

**A beacon-only capture looks exactly like a working one.**
Without a traffic generator the channel updates at roughly 10 Hz off beacons alone, every component reports healthy, and motion detection degrades quietly rather than failing.
`frames_per_s` in the output is the cheapest possible guard against spending an hour debugging the wrong layer.

The 2026-09-19 bring-up recorded 30-70 frames/sec against a 100+ target. Root-causing that gap is still open, and it matters more now than it did: motion is all we have left.

## What CSI can and cannot sense

Get this right. The track owner is an RF-literate judge and overclaiming here costs more than underclaiming.

**CSI can sense:** motion, presence, coarse position, posture change, and periodic chest-wall displacement, which is where breathing and heart rate come from.
It responds to anything that changes the multipath environment, including bodies, moisture, and air density.

**We use exactly one of those**, and the honest framing is that the others were within reach of the physics and out of reach of the hardware, the room, and the weekend.
That is a better sentence than claiming them, and it is true.

**CSI cannot sense gas composition.**
Not oxygen, not carbon monoxide, not smoke as a chemical.
There is a genuine oxygen absorption band near 60 GHz, which is why 802.11ad operates there, but the BCM43455c0 is a 2.4/5 GHz radio and that physics is simply not available to us.

**CSI cannot identify a person.**
Gait-based identification needs per-person enrollment in the same room it was trained in and a subject who is walking. We do not claim it and never did.
Identity, after the pivot, comes from two places: device association against the household roster, and the camera.

## Calibration, and why most of it is avoidable

Settled 2026-09-19. Read this before building any baseline logic.

"Calibration" gets used for two different things here, and only one of them needs an empty room.

### Phase and hardware sanitization: continuous, no baseline

Every packet arrives carrying carrier frequency offset, sampling frequency offset, and AGC scaling, which show up as a random phase offset per frame.
This is removed per-packet by fitting across subcarriers, with Hampel filtering on top.

Environment-independent. Runs continuously. Cold start is fine. Nothing to prepare.

### Static background estimation: this is the one that needs a reference

The room's own multipath, from walls and furniture, dominates the signal. People are a small perturbation on top of it.
To say "three people," the system has to know what zero looks like.

**The failure mode to design around: anything present during calibration becomes invisible.**
Calibrate with someone in the room and they are absorbed into the definition of empty. From then on they do not exist.
This is the same way adaptive background subtraction loses stationary targets in radar and vision.

It matters less after the pivot than it did, because a motionless person is now the camera's problem rather than the radio's, and motion is what we are looking for in the first place.
It still matters: a baseline captured while someone is already in the room raises the threshold for everyone who walks in afterward.

### Build a rolling baseline, not a calibration step

Use a rolling percentile baseline with a **deliberately slow adaptation rate, minutes rather than seconds.**

- Furniture moves and thermal drift get tracked out.
- A person who stays still for the length of an incident does **not** get absorbed.
- Cold start works and self-improves. No 30-second ritual before filming.

**The adaptation constant is the single most important number in this layer.**
Too fast and the system forgets an unconscious person, which is precisely the scenario this project exists for.
Do not let it get tuned at 4am by whoever is nearest the keyboard. Write down the value and why.

### What actually needs a baseline

| Capability | Needs empty-room baseline |
|---|---|
| Motion detection | **No.** Variance over a sliding window. Furniture has zero variance; people do not. |
| Zone labelling | **Yes.** From the enrollment walk |
| Counting people | **Yes.** Cut |
| Room-level localization | **Yes.** Cut |

**Everything that survived the pivot is in the first row.**
That is not a coincidence: the capabilities that needed a reference are the ones that could not be relied on, and cutting them removed the calibration problem along with them.

Zone labelling is the one remaining thing that wants a baseline, and it degrades gracefully - a wrong zone label is a wrong word in a notification, not a wrong finding.

## Rooms: the system does not map walls

Settled 2026-09-19. It cannot, and the reason is structural rather than a hardware gap.

**Walls are the baseline.** The whole chain estimates the static environment and removes it; people are the deviation from it.
You cannot then ask the system to show you the walls, because they are the constant you divided out to see the person.

On top of that:

- **No angle-of-arrival.** The BCM43455c0 is 1x1. One antenna gives no bearing, and without bearing there is no geometry to recover.
- **No synthetic aperture.** Router and Pi are both static. The through-wall imaging work (MIT WiTrack, RF-Capture) used custom FMCW radios with antenna arrays, or moved the receiver.
- **One link is one projection.** A single TX-RX pair collapses the room along one axis.

### Zones come from an enrollment walk

We do not need geometry. We need **labels**. The system never has to know the kitchen's dimensions, only that a given RF signature means kitchen.

```
walk to kitchen  -> record ~30s -> tag "kitchen"
walk to bedroom  -> record ~30s -> tag "bedroom"
walk to hallway  -> record ~30s -> tag "hallway"
```

Standard WiFi fingerprinting, at room level, which is exactly the granularity the contract promises and no finer.

**The walk does double duty:** it seeds the rolling baseline while someone is moving around anyway. One setup procedure, two problems solved. Do it before filming.

It is also an ordinary product experience. People already name rooms when setting up smart bulbs.

### The floor plan is authored, not sensed

This falls under the honesty rule in the root `CLAUDE.md`, where it is now the fourth entry.

The room model in the app is **drawn by us**. We film in one house; measure it once and hardcode it.
That is fine. What is not fine is letting the visual imply the system discovered the layout.

The answer if a judge asks whether it maps their house:

"Room labels come from a one-time setup walk. You walk to each room and tag it. The geometry is drawn once. The system learns which RF signature means kitchen, not where the kitchen's walls are."

**Roadmap:** Apple RoomPlan. On LiDAR iPhones it returns a parametric model with walls, doors and windows; scan once at setup and feed it into the Three.js view. A real floor plan from a sensor designed to produce one, paired with RF for the part RF is good at.

## Breathing, and why this section is a stub

This file used to carry sixty lines on respiration: the personhood test, Fresnel-zone positioning, the rate bands that grounded the adult / child / pet split, and how a lost signature became the headline claim.

**All of it was cut on 2026-09-19.** The reasoning is in `docs/PIVOT.md`.

The short version, because someone will ask and the answer is a good one:
we could resolve a breathing signature, and we could not resolve it reliably enough for a dispatcher to act on.
Shallow breathing, a held breath, an unlucky Fresnel position and a person just outside range all produced the same reading, which is no reading.
A claim that needs four caveats before it can be used is the wrong central claim, and we replaced it with one a human can check: footage.

Do not reintroduce respiration as a "bonus" capability.
It was cut for what it could not support, not for lack of time, and a half-supported vital sign on a 911 call is worse than none.

## Privacy posture

Worth saying out loud in the pitch, because it inverts the expected objection.

No camera. No microphone. No video or audio ever captured.
The system reads a signal already passing through the house.

That is also precisely why the verification in `agents/caller` matters.
A system that sees through walls without a camera is not less sensitive than a camera; in some ways it is more, because there is nothing to unplug and no lens to cover.
The privacy argument is only honest if identity verification is real.

We should declare `dataEgressPolicy: LOCAL_ONLY` on the agent cards, because it is true: inference runs here, on the Pi.
That is the strongest safety-dimension claim Hawk Eye can make honestly to the Trust Index, and it costs nothing because we were going to do it anyway. See `ans/CLAUDE.md`.

## The ingest path is this project's real attack surface

Say this before a judge finds it.

`nexmon_csi` produces raw binary frames from a patched firmware blob, parsed by our code, on a Pi sitting on the home network.
That is untrusted input crossing a parsing boundary, which is OWASP ASI05, unexpected code execution, and a hackathon parser is not a hardened one.
The track owner's stated concern is agent sandbox breakout, and this is where ours would start.

Three things contain it, and two of them are already true for unrelated reasons:

1. **The WiFi interface is in monitor mode while capturing, so there is no station interface.** The Pi's only network path is the wired Cat5. That is a real containment property, and it is the same constraint that makes the cable non-optional in the first place.
2. **Sensing agents hold sensing-agent credentials only.** Compromising the parser does not yield `agents/caller`'s certificate, and `master` will not escalate on a single source regardless of what that source says.
3. Validate frame lengths and field bounds before indexing. Cheap, and it is the actual fix.

What we do **not** have is TEE attestation of the sensing runtime.
The Trust Index scores exactly that under `safetySignals.enclaveAttestation`, so the gap has a name in the spec's own vocabulary.
Scoring zero there and explaining why is stronger than pretending the axis does not exist.

Full reasoning in `docs/threat-landscape.md`.

## Upstream hygiene

RuView is MIT.
Keep our modifications separable and attributed.
When you take a file, note where it came from.
Judges ask what you built, and "we forked a repo" and "we built an identity layer on top of a forked sensing stack" are very different answers.
