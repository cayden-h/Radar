# sensor/

Hawk Eye's sensing layer. Raspberry Pi 4B CSI capture and the interior state it produces.
Everything upstream of the agent mesh in `agents/`.

Read the root `CLAUDE.md` first for why this exists.

**Procedure lives in `docs/hardware/`.**
This file is the contract, the constraints and the reasoning.
The commands are in `docs/hardware/raspberry-pi-4b.md`, `docs/hardware/router-archer-ax1450.md`, `docs/hardware/macbook-traffic-generator.md` and `docs/hardware/assembly-and-placement.md`.
`docs/hardware/bring-up-checklist.md` is the linear path from unboxed hardware to CSI frames flowing.
If a value here and a value there disagree, this file wins and the guide is the bug.


## Job

Turn WiFi Channel State Information from the home router into a small, stable structured answer to four questions, one per consuming CSI agent:

- **Occupancy.** Whether presences exist and roughly where. **Not an exact headcount**: a 1x1 radio has no spatial diversity, two people within about a metre merge into one, and a still person beside a moving one is near-invisible. Report "at least N" with a confidence; take the actual headcount from device association against the roster instead. Limits and the reasoning are under `agents/people`.
- **Body type.** Is each presence an adult, a child, or a pet.
- **Biometrics.** Is each presence breathing, and at what rate.
- **Collapse.** Did someone go down, and are they still down.

Plus one question that is not a simple lookup: **is any of these presences unexpected.** That is `agents/intruder`, and it reasons over the occupancy output rather than reading CSI separately.

A fifth agent, `environment`, does not read CSI at all.
It reads a gas sensor behind a driver interface on the Pi's GPIO.
On this build no gas sensor was purchased, so the only implementation of that driver is simulated and every reading it emits carries `source: "demo-trigger"`.
See the modality limits below.

That is the whole contract.
Resist the temptation to ship RuView's full capability surface.
17-keypoint pose is impressive and changes nothing about the demo; skip it.
Room fingerprinting, activity classification, and gesture recognition are likewise out of scope.

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

We are demoing live at judging, but **not the sensing pipeline.**

The reason is not the calibration step, which no longer exists. It is that counting and localization need a baseline at all, and a hall cannot supply a usable one: the baseline decays as the room fills because bodies are reflectors, and occupancy assumes a bounded space that an open hall does not have. The band is also saturated and everything is moving.

Motion and breathing need no baseline. That is exactly why they survive a judging table and the rest does not.

At the venue the agents run live from Vultr and the CSI is replayed from the session captured at the house. See `agents/CLAUDE.md`.

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
| Bandwidth | 80MHz | Most subcarriers, best resolution for breathing and heart rate. |
| Mode | 802.11ac, ax disabled | See requirement 2. |
| Band steering | Off | Keeps the generator on the monitored band. |

If through-wall performance is poor at 5GHz, fall back to 2.4GHz ch 1 at 20MHz. Worse resolution, better penetration. Test both at the house.

## Traffic generator

**CSI is computed per received frame.** The chip measures the channel from an actual transmission crossing the air. No frames, no measurements, no matter how good the model is.

A router with nothing connected still beacons, but only about ten times a second:

| | Signal | Sample rate needed |
|---|---|---|
| Breathing | 0.1-0.5 Hz | ~10 Hz, marginal |
| Fall transient | 0.5-1s event | 10 Hz too coarse to characterize |
| Heart rate | 0.7-2 Hz, buried under breathing harmonics | 20-50 Hz and up |

10 Hz is the floor and it is not enough for collapse or heart rate. Target 100+ Hz.

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
- Supported OS kernels are **4.19, 5.4, and 5.10**. Upstream notes recent kernels no longer require the modified `brcmfmac` driver, with separate guidance for newer setups.
- Extracts CSI from OFDM-modulated 802.11a/g/n/ac frames, per frame, **up to 80 MHz bandwidth**.

### The risk, stated plainly

This is the single most likely thing to consume a night and produce nothing.
The failure mode is not a clean error.
It is a firmware patch that builds, installs, and then yields all-zero or garbage CSI, with the cause buried in a kernel/firmware version mismatch.

Mitigations, in order:

1. **Flash a known-good OS image pinned to a supported kernel before doing anything else.** Do not `apt full-upgrade` afterward. A kernel bump silently breaks the firmware patch.
2. **Image the working microSD the moment CSI flows.** `dd` it to a file on someone's laptop. If the card corrupts at 4am, that image is the difference between a demo and no demo.
3. **Timebox it.** If CSI is not flowing by the deadline the team sets, drop to the fallback ladder below and do not look back.

### Fallback ladder

Descend only when the level above is timeboxed out.

1. `nexmon_csi` on the Pi, live CSI from the router. The real thing.
2. **Recorded CSI replay.** Capture a real session early, while the patch is working, and replay it through the same pipeline. The downstream agents cannot tell the difference. **Do this even if level 1 is healthy.**

   Note that the demo is a recorded video shot at the house, so level 1 only has to work once, on camera, rather than on demand in front of judges. That materially lowers the risk this path carries.
3. **RuView's simulated data.** `docker pull ruvnet/wifi-densepose:latest` runs the pipeline on synthetic CSI. Honest fallback, but say so on stage rather than implying live hardware.
ESP32-S3 nodes were RuView's primary supported path and much lower risk than nexmon, but no hardware is being purchased, so they are off the table. Levels 1 through 3 are the whole ladder.

Whichever level we land on, **the agent layer must not know which one it is.** `sensor/` exposes one interface; what is behind it is our problem.

## Output contract

The only thing the agent layer may consume.
Keep it small and keep it stable, because the agents get built against it before it produces real numbers.

One field group per consuming agent, so a failure in one sensing capability does not take the others down:

```json
{
  "site_id": "...",
  "captured_at": "2026-09-20T04:12:33Z",
  "sensor_identity": "<ANS name of this device>",
  "calibration": { "baseline_age_s": 412, "healthy": true },

  "occupancy": [
    { "presence_id": "p1", "zone": "kitchen", "confidence": 0.82, "moving": true }
  ],

  "classification": [
    { "presence_id": "p1", "class": "adult", "confidence": 0.71, "expected": true,
      "basis": "respiration_rate" }
  ],

  "biometrics": [
    { "presence_id": "p1", "breathing_bpm": 14, "heart_bpm": 78,
      "is_person": true, "person_confidence": 0.88, "confidence": 0.64 }
  ],

  "collapse": [
    { "presence_id": "p1", "event": "fall", "at": "2026-09-20T04:12:29Z",
      "still_down_s": 47, "confidence": 0.77 }
  ],

  "environment": { "co_ppm": 210, "source": "demo-trigger", "confidence": 0.9 }
}
```

`presence_id` is the join key across the CSI groups. `occupancy` and `classification` are consumed by `agents/people` and `agents/intruder` together.
`environment` has no presence, because a gas reading is a property of the building.
Every consumer must tolerate a missing group, an empty array, and a low confidence.

Notes on the fields:

- `presence_id` is stable **within a session only**. We are not doing person re-identification; RuView flags that as experimental and data-gated, and claiming it is a lie we cannot defend under questioning.
- `zone` is coarse and room-level. Do not promise coordinates.
- `class` is one of `adult`, `child`, `pet`, `unknown`, and is decided from **respiration rate**, not signal amplitude. See the rate table and its stated overlap below. Anything finer than these four classes is not defensible.
- `expected` is what `agents/intruder` reasons over. It is not a recognition result; it is an inference from context such as entry point, time of day, and whether the count exceeds what residents reported. Never present it as identifying a person.
- `breathing_bpm` in 6-30, `heart_bpm` in 40-120, matching RuView's stated ranges. Outside those ranges, report nothing rather than a number.
- `is_person` is the personhood verdict and comes from **respiration periodicity, never from heart rate**. It is the field that separates a human from a fan, a curtain, or a cart. Absence of respiration is not proof of absence of a person; cross-check `collapse` before concluding anything.
- `basis` on a classification records what the class decision was made from. `respiration_rate` is the defensible one. See the rate table above for the class boundaries and their overlap.
- `confidence` must be real and must be propagated all the way to the operator's ear. An agent escalating on a 0.3 presence is a different story than one escalating on 0.9, and the honesty is a feature.
- `collapse.event` is one of `fall`, `slump`, `none`. `still_down_s` is what distinguishes an emergency from someone sitting down hard; a fall followed by standing up is not an event worth reporting.
- `environment.source` must name the real hardware, or the literal string `demo-trigger` when it is faked. This field exists so nobody can accidentally present a simulated reading as a measured one.
- `calibration.healthy` going false must propagate and must suppress escalation. A stale baseline produces confident nonsense, which is the worst possible output for this use case.

### The biometrics field is the money field

It separates three states that look identical to an occupancy counter:

- moving
- still but breathing
- neither

"Unresponsive occupant in the main bedroom" is the single most valuable sentence this system can say to a dispatcher, and it comes from here.
If occupancy works and one other capability works, make it this one.

## What CSI can and cannot sense

Get this right. The track owner is an RF-literate judge and overclaiming here costs more than underclaiming.

**CSI can sense:** motion, presence, coarse position, posture change, and periodic chest-wall displacement, which is where breathing and heart rate come from.
It responds to anything that changes the multipath environment, including bodies, moisture, and air density.

**CSI cannot sense gas composition.**
Not oxygen, not carbon monoxide, not smoke as a chemical.
There is a genuine oxygen absorption band near 60 GHz, which is why 802.11ad operates there, but the BCM43455c0 is a 2.4/5 GHz radio and that physics is simply not available to us.
Do not build an "oxygen sensing" claim on this hardware.

This is why `agents/master` reads a separate physical sensor.

## Air quality: simulated, and labeled as such

Carbon monoxide, not oxygen. See the modality limits above for why CSI cannot do this at all.

**No gas sensor is being purchased.** `agents/master` ships with a simulated reading.

Build the interface as though a sensor were behind it:

- A driver boundary with one implementation, `demo-trigger`, and room for a real one.
- `environment.source` always names what produced the number. The literal string `demo-trigger` when simulated. This field exists so a simulated reading cannot be presented as measured by accident.
- Plausible values and plausible dynamics. CO that jumps from 0 to 800 ppm in one sample is obviously synthetic; ramp it.

If someone does end up with hardware, the real path is an MQ-7 (CO) or MH-Z19 (CO2).
The MQ-7 is analog and the Pi has no ADC, so it needs an MCP3008 in between.
Write that down in a comment at the driver boundary so the next person does not have to rediscover it.

The claim we make on stage is about extensibility, not measurement:
the agent, its ANS identity, and the contract are real; the sensor is not; swapping one in changes nothing above the driver.

## Fire, honestly

We are not building a validated fire detector in 36 hours and should not claim to.

Take fire as an external input, from the gas sensor `agents/master` reads or a demo trigger, and let CSI answer the question that actually matters: **who is still inside, where, and are they breathing.**

Firefighters already know the house is on fire when they are dispatched.
Nobody knows how many people are in the back bedroom.
That is the gap we fill, and it is a better story than a worse smoke detector.

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

For a system whose entire purpose is "is someone still inside and are they breathing," silently deleting the motionless person is the worst bug available to us.

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
| Breathing | **No.** Periodicity in a 0.1-0.5 Hz band. Needs seconds of data, not a reference. |
| Fall / collapse | Mostly no. It is a motion transient. |
| Counting people | **Yes.** |
| Room-level localization | **Yes.** |

So the collapse and respiration readers inside `agents/people` are close to calibration-free.
Its presence reader is the one part of the system that genuinely needs the baseline.

This is also why the venue demo is movement-only: motion sensing is environment-independent, which is the whole reason it survives a crowded hall.

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

This falls under the honesty rule in the root `CLAUDE.md`, same category as the simulated gas sensor.

The room model in the app is **drawn by us**. We film in one house; measure it once and hardcode it.
That is fine. What is not fine is letting the visual imply the system discovered the layout.

The answer if a judge asks whether it maps their house:

"Room labels come from a one-time setup walk. You walk to each room and tag it. The geometry is drawn once. The system learns which RF signature means kitchen, not where the kitchen's walls are."

**Roadmap:** Apple RoomPlan. On LiDAR iPhones it returns a parametric model with walls, doors and windows; scan once at setup and feed it into the Three.js view. A real floor plan from a sensor designed to produce one, paired with RF for the part RF is good at.

## Breathing is the personhood test

A perturbation showing quasi-periodic modulation in a physiological band is a living body.
A fan, a curtain, a rolling cart, a door swinging: none of them produce that signature.

Three properties make this load-bearing rather than a nice extra:

1. **Calibration-free.** Periodicity does not depend on knowing what empty looks like.
2. **Discriminates human from non-human motion**, which nothing else in the stack does.
3. **Works on a person who is not moving**, which is the exact case motion detection fails and the exact case that matters most.

**Use respiration, not heart rate, for this decision.**
Chest wall displacement from breathing is roughly 5-12mm. From a heartbeat it is a few tenths of a millimeter: more than an order of magnitude smaller, usually buried under respiration harmonics, and generally requiring the subject to be close and still.
RuView lists 40-120 BPM for heart rate. Treat it as a stretch goal and as a good number to say on the 911 call. Respiration at 0.1-0.5 Hz carries the personhood decision.

Consequence for the agent layer: **the respiration reader in `agents/people` is the arbiter of what counts as a person**, not merely another reporting channel.
A presence with a respiration signature is human. One without is furniture, noise, or a pet.

Clinical thresholds, the long-lie definition, and the statistics behind all of this are in `docs/research/agent-briefs.md`.
Tagging a presence with a person's name is a separate question with a separate answer: `docs/research/identity.md`. Short version - never from the body, only from device association, and the label never overrides a physical observation.

**Range, per capability:** motion and collapse reach 5-10 m line of sight and about 5 m through one drywall wall; respiration is the short pole at 2-4 m, best under 3. Heart rate is under 2 m and often under 1.
Sensitivity runs along the line between router and Pi, not in a radius around the Pi.
Full table, wall-penetration limits and the twenty-minute range test are in `docs/hardware/assembly-and-placement.md`.
**Respiration sets the demo geometry**, because it is the shortest-range thing the demo depends on.

**To extend range, do not buy an extender.** The MacBook traffic generator is already a second transmitter at a second location; placing it at the far end of the space is the free version of what an extender would do, without the retransmit jitter. Ranked options in `docs/hardware/assembly-and-placement.md`.

### Fresnel position: the failure that looks like broken firmware

Respiration shows up in **amplitude**, not phase. The Pi receives the direct path from the router plus a reflection off the chest; as the chest moves the two slide between constructive and destructive interference.

Phase would be the cleaner signal, but removing carrier and sampling offsets normally needs conjugate multiplication across two antennas that share an oscillator. **The BCM43455c0 is 1x1.** That trick is unavailable, so work in amplitude, which is immune to those offsets entirely.

The consequence is that **sensitivity depends on where the person is lying.**

- On a Fresnel boundary, millimetres of chest motion produce a large amplitude swing. Ideal.
- At a zone centre the response is second-order and nearly flat. **A blind spot.**

Boundaries fall every λ/2 of path change, which is 30mm at 5GHz. So there are real positions in a room where a perfectly healthy person reads as not breathing.

**When staging the fall, test two or three positions before concluding anything is broken.** If breathing looks absent, move the subject a few inches first. Combine across subcarriers rather than trusting one, since different subcarriers peak at different positions.

### Respiration rate grounds the class split

This replaces the earlier hand-wave that mass and height perturb CSI differently, which was thin and would not survive a question from an RF-literate judge.

| Class | Resting respiration, BPM |
|---|---|
| Adult | 12-20 |
| Child | 20-30 |
| Infant | 30-60 |
| Dog / cat | 15-30+ |

Physically grounded and defensible.
It will **not** cleanly separate a dog from a child, and the overlap must be stated rather than hidden. "Adult versus small and fast-breathing" is the honest resolution.

**Limits to state plainly:**

- Overlapping respiration signals from several people close together cannot be separated. This is why counting still fails in a crowded hall.
- Vital signs work at shorter range than motion detection.
- A person holding their breath, or breathing very shallowly, degrades toward invisible. Cross-check against `collapse` rather than treating absence of respiration as absence of a person.

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
