# Working with no wired uplink

Written 2026-09-19, from a bring-up session where neither the school nor the working space had an ethernet wall jack.
Everything available was wireless.

This file records what was decided in that situation and why.
It supplements `docs/hardware/assembly-and-placement.md`; it does not replace it.
Where this file and `sensor/CLAUDE.md` disagree, `sensor/CLAUDE.md` wins and this file is the bug.

## The one sentence that resolves most of the confusion

**The demo router never needs an internet uplink, and its WAN port stays empty for the entire project.**

The router is a transmitter, not a gateway.
Its only job is to put 802.11ac frames into the air on a fixed channel so the Pi has something to measure.
A flashlight does not need to be connected to anything in order to shine.

macOS will show a "no internet" warning on `Radar-5G` permanently.
That warning is accurate and irrelevant.
Do not spend time on it, and do not let anyone on the team spend time on it either.

The only thing in the project that ever needed internet is the Pi, once, to install `nexmon_csi`.
That is handled in phase 1 below, with the router unplugged.

## Router configuration as actually set

This matches the table in `sensor/CLAUDE.md`.
Recorded here because it was entered by hand during this session and should be re-verified after any firmware update or factory reset.

| Setting | Value |
|---|---|
| Operation mode | Router, standard |
| WAN | Empty, nothing connected |
| Smart Connect | Off |
| 2.4GHz SSID | `Radar` |
| 5GHz SSID | `Radar-5G` |
| 5GHz channel | Fixed, one of 36 / 40 / 44 / 48, auto off |
| 5GHz bandwidth | 80MHz, not auto |
| 5GHz mode | `802.11a/n/ac mixed` |
| 2.4GHz channel | 1, fixed |
| 2.4GHz bandwidth | 20MHz |
| LAN IP | `192.168.0.1`, DHCP on, pool starts `192.168.0.2` |

Notes on that table:

- **Smart Connect off is not optional.** It is band steering, and with it on the traffic generator wanders to the band the Pi is not watching. Nothing errors. The capture just goes flat.
- **The 5GHz mode dropdown is the one that silently reverts.** On TP-Link firmware it can return to an ax-inclusive default when other settings change. `nexmon_csi` extracts nothing from ax frames, so re-check this value every time you change anything else on that page.
- **The 2.4GHz band stays enabled** even though the plan is to sense at 5GHz. It costs nothing with band steering off, and it preserves the documented fallback to 2.4GHz ch 1 at 20MHz if through-wall performance at 5GHz is poor.
- **The LAN subnet must never be `192.168.2.x`.** It collides with the macOS Internet Sharing NAT range used in phase 1. `192.168.0.1` is fine, leave it.

Configure the router over the cable on a **LAN** port, not over Wi-Fi.
Saving wireless settings restarts the radios, and if you are on Wi-Fi at the time you drop your own admin session mid-save, which can leave settings half applied.

## Phase 1: installing software on the Pi

This is the only phase that needs internet, and the router is not involved in it at all.

```
phone hotspot or campus Wi-Fi
   └─► MacBook Wi-Fi
          └─ macOS Internet Sharing ─► USB ethernet adapter ─ Cat5 ─► Pi eth0
```

Cat5 runs directly from the MacBook's USB ethernet adapter into the Pi.
The router is unplugged or ignored.

1. System Settings, General, Sharing, Internet Sharing.
2. Share your connection from: Wi-Fi.
3. To computers using: the USB ethernet adapter.
4. Turn it on.

The Pi lands on `192.168.2.x` and reaches the internet through the Mac.
Find it with `arp -a | grep 192.168.2`.

Do every `apt` install and every `git clone` in this phase, including the full `nexmon_csi` build.
After this phase the Pi does not need internet again for the rest of the project.

Captive-portal campus Wi-Fi cannot be shared by macOS Internet Sharing.
If the campus network has a portal, tether a phone over USB and share that instead.

## Phase 2: capture, with only the short cable

The geometry requirement is that a transmitter and the Pi are on **opposite sides** of the sensed space, with people in between.
It is not a requirement that the Pi be the device cabled to the router.

The kit's Cat5 is short, so the Pi is cabled to the MacBook and the router goes across the room on its own.

```
[ router ]        ← across the room →        [ MacBook ─ short Cat5 ─ Pi ]
 wall outlet only                              phone on USB for internet
```

- The router needs a **wall outlet and nothing else**.
- The MacBook's Wi-Fi joins `Radar-5G` and generates traffic across the room.
- The router's replies cross the room to reach the Pi, and those are the frames the Pi measures.
- The Cat5 carries no CSI. It exists only so you can SSH into the Pi and see results.

### Why the Pi is cabled at all

`nexmon_csi` holds `wlan0` in a monitor-mode state, so the Pi has no working Wi-Fi client interface while capturing.
The measurement arrives through the Pi's antenna, out of the air.
The cable is the keyboard and screen, not the sensor.

The camera analogy is the one to use when explaining this to anyone: the picture comes in through the lens, and the cable to the laptop is only how you see it.

### Addressing over the direct cable

With no internet in the chain, skip Internet Sharing in phase 2 and set both ends statically.
It is fewer moving parts and it does not depend on a DHCP server existing.

| End | Address | Mask |
|---|---|---|
| MacBook USB ethernet adapter | `10.0.0.1` | `255.255.255.0` |
| Pi `eth0` | `10.0.0.2` | `255.255.255.0` |

Leave the router field blank on the Mac side.
Then `ssh pi@10.0.0.2`.

`ssh pi@raspberrypi.local` over mDNS usually works with both ends on automatic, but static is more reliable at 3am.

### Preferred variant, if a longer cable appears

A 25 or 50 foot Cat5 costs about ten dollars and removes this constraint permanently.
The no-further-hardware rule in `docs/hardware/README.md` is aimed at sensors and radios, not at a cable that unblocks the geometry.

With a long cable, revert to the layout in `sensor/CLAUDE.md`: Pi on a router LAN port, MacBook on `Radar-5G`, router and Pi on opposite sides.
That is the better arrangement for the house shoot, where real distance and an intervening wall are the point.

## Internet on the MacBook while working

The MacBook has one Wi-Fi radio, and campus Wi-Fi and `Radar-5G` both want it.
This is the conflict behind most of the friction in this session.

**USB-tether the phone.** It moves internet onto the USB port and frees the radio.

1. iPhone: Settings, Personal Hotspot, on, then choose USB. Android: Settings, Hotspot and tethering, USB tethering.
2. System Settings, Network, the "..." menu, Set Service Order.
3. Drag the phone's interface **above** Wi-Fi.

Step 3 matters.
Without it macOS may try to route internet through the internet-less `Radar-5G`, and everything feels broken for reasons that have nothing to do with the capture.

With the tether in place you have, simultaneously: internet, SSH to the Pi, `rsync` for pushing scripts, router admin, and a working traffic generator.

If tethering is blocked by the carrier plan, the fallback is to switch the Mac's Wi-Fi between campus and `Radar-5G` as needed.
Annoying, nothing is actually blocked by it.
Bluetooth PAN also frees the Wi-Fi radio and is fine for git, too slow for `apt`.

## Traffic generator: ping the Pi, not the gateway

**This is a correction to the command in `sensor/CLAUDE.md` and `docs/hardware/macbook-traffic-generator.md`.**

Those files give the generator as `sudo ping -i 0.01 <gateway>`.
During this session, ICMP to the router's LAN address `192.168.0.1` timed out while the admin page loaded normally over HTTP, which suggests the firmware filters ICMP to the gateway.

That matters because a traffic generator that silently emits nothing is one of the documented quiet failures.
Every component reports healthy and the capture is empty.

Use the Pi as the target instead:

```sh
sudo ping -i 0.01 <pi-ip>
```

This is the better target regardless of the ICMP question.
The MacBook is on Wi-Fi and the Pi is on the far end, so every request and every reply crosses the monitored channel over the air, which is exactly the traffic the Pi needs to see.
The Pi answers ICMP reliably, and the visible reply stream is itself the confirmation that the generator is alive.

**Before trusting any capture, confirm the generator is actually producing replies.**
Do not infer it from the fact that the command is running.

## Verify placement before debugging software

Once frames are flowing, have someone walk between the router and the Pi and confirm the signal moves.
If it does not, move the two further apart before assuming the firmware patch failed.

A flat capture from bad geometry is indistinguishable from a flat capture from a failed `nexmon_csi` build.
This is the single most expensive confusion available in this project.

Distance does not need to be dramatic.
A few metres with a person walking between the two points is a valid test.
The failure case is the two devices side by side on one table, where nothing can ever pass between them.

## Demo scope, settled in this session

These follow from `sensor/CLAUDE.md` and the honesty rule in the root `CLAUDE.md`.
They are recorded here because they were re-litigated during this session and should not be re-litigated again.

### The headcount does not come from CSI

A 1x1 radio resolves presence, not an exact number of people.
Two people within about a metre merge into one, and a still person beside a moving one is nearly invisible.

The count shown on screen and spoken on the call comes from **device association against the known roster**.
The radio answers which room, and whether that presence is breathing.

Never stand in front of a room and say CSI is counting the people in it.

### A venue cannot run occupancy or localization live

Not because of calibration, which no longer exists as a step.
Because counting and localization need a baseline at all, and a hall cannot supply a usable one:

- The baseline decays as the hall fills, because bodies are reflectors.
- Occupancy assumes a bounded space, and an open hall is not one.
- The band is saturated and everything is moving.

Knowing the judging-table geometry in advance does not fix this.
The geometry was never the sensed part; the floor plan is drawn by hand and room labels come from a one-time enrollment walk.
What a hall breaks is the RF baseline, which decays while you are using it.

At the venue, the agents run live from Vultr and the CSI is replayed from the session captured at the house.

### What does survive a judging table

Motion needs no baseline.
That is exactly why it survives and the rest does not.

The live bit is a **raw signal view**: a live amplitude trace across subcarriers, flat while nobody moves, visibly kicking when a judge's hand crosses the path between the two points.

Build it as its own screen, separate from the room map.
It claims only that the radio is receiving and that a body in the path changes what it receives.
No baseline, no room model, no count, no through-wall claim.

Do not wire the hand wave into the room map.
Putting a presence on a map is a localization claim, and that is the claim the hall breaks.

### Optional stretch: one bounded zone

If there is spare time, a single bounded zone between the two taped points, answering only "something is in the path" or "nothing is", is defensible at a table.
It requires a baseline captured minutes before presenting, in place, with the crowd already present, and re-captured between judging slots.

Never put a number on it.
Never present it as the room map from the video; those are different claims and the jump is visible.

Budget an hour at most.
The thing actually being graded on Sunday is `caller` refusing a drifted certificate and `agent.webmesh.ai` confirming our agents live, not the sensing.

### The live-demo rule still applies

From the root `CLAUDE.md` working agreements: anything demoed live needs a recorded fallback by Saturday night.
The house replay is the guaranteed path.
The decision about which to run is made at the table, based on whether the baseline held.

## Open items

- Fold the ping-target correction into `sensor/CLAUDE.md` and `docs/hardware/macbook-traffic-generator.md`, or confirm the ICMP filtering was a local routing artifact and drop it.
- Confirm the chosen 5GHz channel is clear of the campus and household networks. `sudo wdutil info` for the current network, Wireless Diagnostics then Window then Scan for a full picture.
- Reserve the Pi's address in the router's DHCP table once its MAC is known, so the SSH target stops moving between reboots.
- Set up an SSH key to the Pi early, before the dev loop starts costing a password per iteration.
