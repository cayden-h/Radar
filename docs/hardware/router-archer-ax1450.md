# TP-Link Archer AX1450

The router is not a network appliance in this project.
It is the **transmitter half of the instrument**.

The Pi measures how the radio channel between a transmitter and itself is perturbed by bodies.
Every setting below exists to make that channel stable, measurable, and on a band the Pi is actually watching.

Read `sensor/CLAUDE.md` for the reasoning.
This guide is the button-by-button version.

## Why this router and not a mesh system

From `sensor/CLAUDE.md`, in priority order, what the router must be able to do:

1. Fixed channel, auto-channel off. A channel change mid-run invalidates the baseline instantly.
2. Force 802.11ac. `nexmon_csi` extracts CSI from 802.11a/g/n/ac frames only. HE (Wi-Fi 6) and EHT (Wi-Fi 7) frames yield nothing at all.
3. Fixed bandwidth.
4. Separate 2.4 and 5GHz SSIDs with band steering off, so the traffic generator cannot wander to the band the Pi is not watching.

Mesh systems (Deco, Orbi, Nest) are rejected.
They force band steering and auto channel and cannot be pinned down.

The AX1450 was chosen because TP-Link's 5GHz mode dropdown offers `802.11a/n/ac mixed`, which excludes ax outright.
That single dropdown is the whole reason this box is here.

One thing to know before you plan anything around it: **stock TP-Link Archer firmware does not expose SSH.**
You cannot generate traffic from the router itself.
Traffic must come from a client device. See [macbook-traffic-generator.md](macbook-traffic-generator.md).

## First-time setup

### Physical

1. Power the router from its own supply.
2. Wire its **WAN** port to the uplink. At the house, that is a Cat5 to the home router or modem. At a venue, that is a Cat5 to the MacBook's USB ethernet adapter running Internet Sharing.
3. Wire a **LAN** port to the Pi's USB ethernet adapter with the Cat5.
4. Leave the antennas vertical and do not bunch them together.

Placement is not arbitrary and it is the thing most likely to silently ruin a capture.
Read [assembly-and-placement.md](assembly-and-placement.md) before you decide where this box sits.

### Admin access

From the MacBook, associated to the router's Wi-Fi or plugged into a LAN port:

```
http://tplinkwifi.net
```

or

```
http://192.168.0.1
```

192.168.0.1 is the AX1450's factory LAN address.
This matters for us: `sensor/CLAUDE.md` uses `192.168.0.1` as the ping target for the traffic generator, and 192.168.0.x does **not** collide with macOS Internet Sharing's 192.168.2.x NAT range.
Leave the LAN subnet alone unless you have a specific reason.

On first access the router asks you to set an admin password.

Admin password: `TBD - decide and record here.`
Pick one, write it down, and tell the team.
Do not use the Tether app for this. Every setting below is web-UI only and the app hides half of them.

Skip or dismiss any firmware auto-update prompt.
A firmware update mid-event is an unforced risk.

## The configuration table

This is the table from `sensor/CLAUDE.md`, with the menu path for each setting.

Menu paths are given for the AX1450's web UI under **Advanced**.
TP-Link moves these between firmware revisions.
If a path does not match what you see, the setting still exists somewhere under Wireless; find it rather than skipping it.

| Setting | Value | Menu path | Why it matters to CSI |
|---|---|---|---|
| 5GHz channel | ch 36, 40, 44, or 48 | Advanced > Wireless > Wireless Settings > 5GHz > Channel | UNII-1, non-DFS. A DFS channel (52-144) can radar-detect and hop mid-take, which silently ends the capture. |
| Auto channel | Off (pick the channel explicitly) | Same dropdown. Choosing a number rather than "Auto" is what turns it off. | A channel change mid-run invalidates the baseline instantly and the Pi is left monitoring an empty channel. |
| Channel width | 80MHz | Advanced > Wireless > Wireless Settings > 5GHz > Channel Width | Most subcarriers, best resolution for breathing and heart rate. `nexmon_csi` supports up to 80MHz, so this is the maximum useful value. |
| Mode | `802.11a/n/ac mixed`, ax disabled | Advanced > Wireless > Wireless Settings > 5GHz > Mode | `nexmon_csi` extracts CSI from 802.11a/g/n/ac frames only. An ax association produces HE frames, which yield nothing. This is the single most important dropdown on the box. |
| Band steering / Smart Connect | Off | Advanced > Wireless > Wireless Settings, or Advanced > Wireless > Smart Connect depending on firmware | Keeps the traffic generator on the monitored band. With it on, the MacBook silently moves to 2.4GHz and the 5GHz capture goes quiet. |
| SSIDs | Separate 2.4GHz and 5GHz SSIDs, clearly named | Advanced > Wireless > Wireless Settings, one tab per band | You need to be able to force a client onto a specific band by name. Identical SSIDs make that impossible. |
| OFDMA / MU-MIMO | Off if the toggle exists | Advanced > Wireless > Wireless Settings > 5GHz, or Advanced > Wireless > OFDMA | Wi-Fi 6 features. Unverified whether the AX1450 exposes these toggles independently of Mode. Turning Mode to `a/n/ac mixed` should already stop ax frames; treat these as belt and braces. |
| WPS | Off | Advanced > Wireless > WPS | Not CSI-relevant. It is one less thing changing the radio state during a take. |
| Guest network | Off | Advanced > Wireless > Guest Network | A second BSS on the same radio is extra traffic and extra state for no benefit. |

SSID names, set 2026-09-19: `Radar` (2.4GHz), `Radar-5g` (5GHz).

**The over-the-air MAC for each SSID is not the MAC printed on the router's label.** The AX1450 uses a distinct MAC per radio/band; ours was off by one in the last octet between the label and the actual `Radar-5g` BSSID seen in a scan. Anything that needs the router's real MAC (`makecsiparams -m`, for instance) must get it from a WiFi scan, not the label — see `docs/hardware/raspberry-pi-4b.md` Step 5.

Wi-Fi password: set at configuration time, not recorded here (this file is git-tracked — ask the team directly).
Use WPA2-PSK if there is a choice.
WPA3 is fine for connectivity but is one more variable on a box whose only job is to emit predictable 802.11ac frames.

### Channel selection is a decision, not a default

`sensor/CLAUDE.md` is explicit about this at the house: the Pi monitors exactly one channel, so if the demo router and the household's existing network share it, household traffic contaminates the capture.

Before you pick:

```sh
# From the MacBook, list what is already on the air
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s
```

If that binary is absent on your macOS version, use the Wireless Diagnostics scan window: hold Option, click the Wi-Fi menu, choose Open Wireless Diagnostics, then Window > Scan.

Take whichever of 36, 40, 44, 48 has the least sitting on it, and one the household network is not on.

Recorded 2026-09-19: **channel 40**, 80MHz.
This number has to match `makecsiparams -c <channel>/80` on the Pi exactly.
A mismatch there produces packets with zero payloads, which is the hardest failure in the project to diagnose.

Note that `airport -s` is gone on recent macOS versions (removed from the system entirely, not just relocated) — go straight to the Wireless Diagnostics scan window described below, or `sudo wdutil info` for just the currently-associated network.

### If 5GHz does not penetrate

`sensor/CLAUDE.md` allows one fallback: 2.4GHz channel 1 at 20MHz.
Worse resolution, better wall penetration.
Test both at the house, before filming, not during.

If you take it, every downstream number changes: `makecsiparams -c 1/20`, and the traffic generator must associate to the 2.4GHz SSID.

## Network layout: getting everyone on one reachable network

Four devices, one LAN.

| Device | How it connects | Address |
|---|---|---|
| Pi | Cat5 to a router LAN port, via its USB ethernet adapter | DHCP. Reserve it. |
| MacBook | 5GHz Wi-Fi to the router | DHCP |
| iPhone | 5GHz Wi-Fi to the router | DHCP |
| Router | Gateway | 192.168.0.1 |

### DHCP and the reservation

Leave the DHCP server on with defaults.
Do reserve the Pi's address, so SSH targets do not move when something reboots.

Advanced > Network > DHCP Server.
Find the Pi in the client list by its hostname, then add a DHCP reservation for its ethernet-adapter MAC.

Pi reserved address: `TBD - decide and record here.`
How to determine it: after the Pi's first boot, read its lease from Advanced > Network > DHCP Server > DHCP Client List, then reserve that same address.

Note that the MAC in the client list is the **USB ethernet adapter's** MAC, not the Pi's onboard MAC.
Reserving the wrong one produces a Pi that is reachable until it is not.

### The subnet constraint

**The router LAN subnet must not be 192.168.2.x.**
It collides with macOS Internet Sharing's NAT range, which is only used on the venue path, but a collision configured at the house will not show up until you are at the venue.

The factory default of 192.168.0.x is already correct.
Leave it.

### Double NAT is fine

At the house, the demo router's WAN plugs into the home router, which gives two layers of NAT.
This does not matter.
All agent traffic is outbound to Vultr.

## House versus venue

### At the house, which is what the demo video uses

```
home router / modem
   └─ Cat5 ─► AX1450 WAN
                AX1450 LAN ─ Cat5 ─► Pi eth0
                AX1450 5GHz ────────► MacBook (traffic generator)
                AX1450 5GHz ────────► iPhone (the app)
```

No Internet Sharing in this chain.
The uplink is already ethernet, so the MacBook is free to be the traffic generator.
Dropping Internet Sharing here removes three failure points: macOS Internet Sharing itself, the USB Ethernet adapter in the uplink role, and the 192.168.2.x subnet collision.

One decision to make before filming: whether the Pi needs internet at all.
If the sensing agents run on a laptop on the same LAN rather than on Vultr, the uplink stops mattering during the take, which is one less thing that can break on camera.

### At a venue, judging table

We are demoing live at judging, but **not the sensing pipeline**.
The agents run from Vultr and the CSI is replayed from the session captured at the house.

The Pi and router still come along, for a prop and for one honest live bit: movement response.
No calibration, no baseline, no through-wall claim.
A judge waves a hand and the signal moves.
Motion sensing needs no baseline, which is exactly why it survives a hall that counting and localization cannot.

If the Pi is powered up at the venue at all, this is the chain:

```
venue Wi-Fi or phone hotspot
   └─► MacBook (macOS Internet Sharing: Wi-Fi source ─► USB Ethernet)
          └─ Cat5 ─► AX1450 WAN
                       AX1450 LAN ─ Cat5 ─► Pi eth0
                       AX1450 5GHz ────────► traffic generator
```

Two constraints that only bite here:

- Router LAN subnet must not be 192.168.2.x. Verified above.
- **Captive-portal venue Wi-Fi cannot be shared.** The fallback is USB tethering a phone to the MacBook and sharing that.

Expect the 5GHz band at a venue to be saturated.
That is fine for the movement bit and is one of the reasons counting and localization stay in the video.

## Verification

Run all of these before you consider the router done.

```sh
# 1. The MacBook is on 5GHz, on the channel you chose, at 80MHz
system_profiler SPAirPortDataType | grep -A 12 "Current Network"
# look for: Channel, and a PHY Mode that is 802.11ac and not 802.11ax
```

The PHY Mode line is the acceptance test for the whole router configuration.
If it says `802.11ax`, the Mode dropdown did not take and the Pi will capture nothing usable.
Go back and fix it before doing anything else.

```sh
# 2. The gateway answers
ping -c 3 192.168.0.1

# 3. The Pi is reachable over the wire
ssh hawkeye@<pi address>

# 4. The Pi can see the router's channel
# on the Pi, before monitor mode is enabled:
sudo iw dev wlan0 scan | grep -A 5 "HawkEye-5G"
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| MacBook reports PHY Mode 802.11ax | Mode dropdown is not set to `a/n/ac mixed`, or the change did not save | Reset the Mode, save, reboot the router, re-check. This is non-negotiable. |
| MacBook keeps landing on 2.4GHz | Band steering / Smart Connect still on, or the SSIDs are identical | Turn steering off, give the bands distinct SSIDs, forget the network on the Mac and rejoin the 5GHz one explicitly |
| Capture is contaminated by traffic nobody is generating | The demo router shares a channel with the household network | Scan, move to a different non-DFS UNII-1 channel, update `makecsiparams` to match |
| The channel changed on its own mid-session | Auto channel is still selected, or the channel is DFS and radar was detected | Pin an explicit channel in 36/40/44/48 |
| Pi is reachable, then is not, after a reboot | No DHCP reservation, or the reservation is on the wrong MAC | Reserve the USB ethernet adapter's MAC |
| Internet Sharing works but the Pi has no route | 192.168.2.x collision | Confirm the router LAN is 192.168.0.x |
| Venue Wi-Fi will not share | Captive portal | USB tether a phone to the MacBook and share that instead |
| You wanted to run the traffic generator on the router | Stock TP-Link firmware has no SSH | Not possible. Generate from a client. |
| `makecsiparams -m <label MAC>` produces packets with zero flow, no error anywhere | The router's per-band radio MAC differs from the MAC printed on its label | Get the real MAC from a WiFi scan (monitor mode off) instead of the label. See `docs/hardware/raspberry-pi-4b.md` Step 5. |
| macOS Internet Sharing shows "on" but the shared adapter never gets an IP, `log show` mentions `BRDGADD: failed Resource busy` | Known macOS flake in the sharing bridge setup | Toggle Internet Sharing off, physically unplug/replug the USB-Ethernet adapter, toggle back on. Reboot the Mac if that doesn't clear it. |
