# Bring-up checklist

One linear path from unboxed hardware to "CSI frames are flowing and `agents/occupancy` sees a person."

Work top to bottom.
Do not skip ahead.
Every step has a verification command and the output you should see.
If a step fails, the matching guide has a troubleshooting table.

Before you start, note the time and agree a timebox with the team.
`sensor/CLAUDE.md` is explicit: if CSI is not flowing by that deadline, drop to the fallback ladder and do not look back.

Timebox agreed: `TBD - decide and record here.`

**Status, 2026-09-19: CSI confirmed flowing end to end** (real, varying, non-zero payloads at 30-70 packets/sec), disk image and a first replay session captured. Full recorded values and the corrected build path (kernel reality changed from what this checklist originally assumed) are in `sensor/CLAUDE.md` and `docs/hardware/raspberry-pi-4b.md`. The steps below are left as the procedure for redoing this from scratch; read the "Kernel reality, corrected 2026-09-19" note in `sensor/CLAUDE.md` before Phase 2, since it changes what "the kernel check" below should expect.

---

## Phase 0: before touching anything

- [ ] Read `sensor/CLAUDE.md`, at least "The risk, stated plainly" and "Fallback ladder".
- [ ] Read the geometry rule in [assembly-and-placement.md](assembly-and-placement.md). It is the failure that wastes the most time.
- [ ] Confirm the bill of materials is all present: Pi 4B, USB ethernet adapter, Cat5, microSD, 5V/3A USB-C supply, Archer AX1450 and its supply, the MacBook.

  No further hardware is being purchased. If something is missing, the answer is the fallback ladder, not a store.

---

## Phase 1: the router

Do this first. The Pi's capture parameters have to match the router's channel exactly.

- [ ] Router powered from its own supply, antennas vertical and fanned out.
- [ ] WAN port wired to the uplink (house: Cat5 to the home router/modem).
- [ ] Reach the admin UI.

  ```sh
  open http://192.168.0.1
  ```
  Expect: the TP-Link setup or login page. Set and record the admin password.

- [ ] Scan the air and pick a 5GHz channel from 36 / 40 / 44 / 48 that the household network is not using.

  ```sh
  # macOS; if the airport binary is missing, use Wireless Diagnostics > Window > Scan
  /System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s
  ```
  Expect: a list of nearby networks and their channels. Record your choice.

  Chosen channel: **40** (80MHz), recorded 2026-09-19.
  Note: `airport -s` has been removed entirely from recent macOS versions — go straight to Wireless Diagnostics > Window > Scan.

- [ ] Apply every row of the configuration table in [router-archer-ax1450.md](router-archer-ax1450.md): fixed channel, 80MHz width, `802.11a/n/ac mixed`, band steering off, separate SSIDs per band, WPS off, guest network off.
- [ ] Join the MacBook to the **5GHz** SSID explicitly, by name.
- [ ] Verify the association. This is the acceptance test for the whole router config.

  ```sh
  system_profiler SPAirPortDataType | grep -A 12 "Current Network"
  ```
  Expect: your 5GHz SSID, `Channel` matching what you chose with a `,80` width, and `PHY Mode: 802.11ac`.

  If `PHY Mode` says `802.11ax`, stop and fix the Mode dropdown. `nexmon_csi` extracts nothing from HE frames.

- [ ] Gateway answers.

  ```sh
  ping -c 3 192.168.0.1
  ```
  Expect: three replies, low single-digit milliseconds.

- [ ] Confirm the LAN subnet is not 192.168.2.x. Factory default 192.168.0.x is correct.

---

## Phase 2: flash and boot the Pi

- [ ] Pick **Raspberry Pi OS (Legacy, 32-bit), Lite**. `TBD - decide and record here` re: 4.19/5.4/5.10 is **outdated** — current Imager catalogs no longer serve those kernels at all. See "Kernel reality, corrected 2026-09-19" in `sensor/CLAUDE.md`. Take whatever `Legacy, 32-bit` actually gives you and use the `Makefile.rpi` build path in `raspberry-pi-4b.md` Step 4.
- [ ] Flash with Raspberry Pi Imager. Newer versions use tabbed dialogs (Hostname/Localization/User/Wifi/Remote access) rather than one settings sheet — SSH lives under **Remote access**. Set hostname, enable SSH, set username and password, and **leave the Wifi tab's SSID field empty**.
- [ ] Insert the card. The Pi 4B's onboard Ethernet port works directly — no USB adapter needed for the Pi itself (only the bring-up laptop needs one, if it lacks a built-in Ethernet port, for Internet Sharing). Cat5 from the Pi to a router LAN port, or directly to the laptop's adapter if you have no wired uplink at all — see the no-uplink note below.
- [ ] Power the Pi from the kit's 5V/3A wall supply. Never from a router or laptop USB port.
- [ ] Pi is reachable over the wire.

  ```sh
  ping -c 3 radar-pi.local
  ssh radar@radar-pi.local
  ```
  Expect: replies, then a shell prompt. If mDNS fails, find the lease in Advanced > Network > DHCP Server > DHCP Client List (or, over an Internet-Sharing bridge, `arp -a | grep 192.168.2` on the Mac).

  Set up an SSH key immediately after first login — see `raspberry-pi-4b.md` Step 2 — the rest of this checklist has you SSHing in constantly.

- [ ] **The kernel check.** Confirmed 2026-09-19: `6.12.109+rpt-rpi-v8`, **not** 4.19/5.4/5.10 — that's expected now, not a failure. See the status note at the top of this file.

  ```sh
  uname -r
  dpkg --print-architecture
  ```
  Confirm it's `armhf` userspace regardless of kernel version; that's what the rest of the build assumes.

  **No wired uplink available? See `docs/hardware/bring-up-checklist.md`'s companion note and `sensor/CLAUDE.md`** — a MacBook can bridge venue/campus WiFi to the Pi over Internet Sharing for the install phase only, then the router never needs a WAN connection at all for actual capture. Known Internet Sharing flake: toggle shows "on" but the bridge never gets an IP (`log show --predicate 'process == "InternetSharing"'` shows `BRDGADD: failed Resource busy`) — fix by unplugging/replugging the USB-Ethernet adapter, then re-toggling.

- [ ] Chip is the expected one.

  ```sh
  ls /lib/firmware/brcm/ | grep 43455
  ```
  Expect: `brcmfmac43455-sdio.bin` and related files.

- [ ] Reserve the Pi's DHCP address on the router, against the **USB ethernet adapter's** MAC.

  Reserved address: `TBD - decide and record here.`

---

## Phase 3: place the hardware

Do this before building, so the first CSI you ever see comes from a geometry that can produce a signal.

- [ ] Router on one side of the sensed space, Pi on the opposite side, both at roughly torso height.
- [ ] Nothing large and metal, and no mirror, directly between them.
- [ ] No fan running in the sensed space.
- [ ] Cat5 seated at both ends, Pi on its own wall supply.
- [ ] Walk the physical sanity pass at the end of [assembly-and-placement.md](assembly-and-placement.md).

---

## Phase 4: build nexmon_csi

**Corrected 2026-09-19: use the `Makefile.rpi` path, not the kernel-pinned steps this phase originally had.** Full corrected procedure — dependencies, the Python 2.7/Stretch-archive step, the `libisl`/`libmpfr` symlink fix, the build itself, and `nexutil` — is in `docs/hardware/raspberry-pi-4b.md` Step 4. Follow that directly rather than this file; duplicating it here would just drift out of sync.

Do it inside `tmux` (start one now if you haven't: `tmux new -s bringup`) — the build is long enough that a dropped SSH session mid-compile means starting over.

Start this, then do Phase 5 while it compiles.

- [ ] Confirmed path once built, 2026-09-19: `~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams`.
- [ ] Confirm the patch actually loaded before moving on: `dmesg | grep -i 'Firmware:'` should show today's build date and `(nexmon.org/csi: <hash>)`, not the stock BCM firmware date.
- [ ] Reboot once, so the patched firmware (now the default via `update-alternatives`) is what loads. **Runtime state — NetworkManager unmanaged, monitor mode, extractor config — does not survive the reboot and must be redone after it**; the firmware install itself does persist.

---

## Phase 5: traffic generator

**If the bring-up laptop is busy bridging internet to the Pi (Internet Sharing, no wired uplink available — see the note in Phase 2), it can't also be the traffic generator.** A single WiFi radio can't be associated to the venue/campus network and the router's `Radar-5g` network at the same time. Use a **second device** for this role in that case; otherwise the one laptop can do both.

- [ ] Generator device is on the **5GHz** SSID (`Radar-5g`) with `PHY Mode: 802.11ac` (verified in Phase 1).
- [ ] Start the generator.

  ```sh
  sudo ping -i 0.01 192.168.0.1
  ```
  (Drop `caffeinate` if not on macOS, or it's not relevant to your setup — the point is just a sustained high-rate ping.) Expect: a continuous stream of requests. If it errors on the interval, you forgot `sudo` (fractional `-i` below 0.2s needs root).

  **The router may not reliably reply to ICMP aimed at its own gateway address** — we saw exactly this on 2026-09-19. That's fine; what matters for CSI is the router's *own* outgoing frames if you filter `-m` on it, or the generator's *outgoing request frames* if you filter `-m` on the generator instead — see the `-m` guidance in `raspberry-pi-4b.md` Step 5. We got a more reliable capture filtering on the generator's own MAC.

- [ ] Confirm the rate on the generator side: interrupt after ~20 seconds and read the summary.

  Expect: transmitted divided by elapsed seconds close to 100. This is the generator's own send rate, not the CSI packet rate the Pi sees — those can differ (see Phase 6).

- [ ] Restart it and leave it running for the rest of the bring-up.

  The script at `sensor/tools/trafficgen.sh` in [macbook-traffic-generator.md](macbook-traffic-generator.md) does start, stop, and status.

  **If the generator device rejoins the WiFi network mid-session (sleep/wake, moving out of range and back), recheck its MAC address** before assuming a capture failure — some OSes assign a new random/private MAC per network join, which silently breaks a `-m` filter configured for the old one.

---

## Phase 6: capture

- [ ] Generate the CSI parameters on the Pi, with the channel you chose and 80MHz width.

  ```sh
  makecsiparams -c <CHANNEL>/80 -C 1 -N 1 -m <ROUTER_MAC> -b 0x88
  ```
  Expect: one base64 blob. Save it.

  Router MAC: `TBD - decide and record here.` Read it off the router label, or `arp -n 192.168.0.1` from the MacBook.

- [ ] Configure the extractor and bring up monitor mode, in this order, over the **Cat5 SSH session**.

  ```sh
  sudo su
  nexutil -Iwlan0 -s500 -b -l34 -v<YOUR_BASE64_BLOB>
  pkill wpa_supplicant
  ifconfig wlan0 up
  iw phy `iw dev wlan0 info | gawk '/wiphy/ {printf "phy" $2}'` interface add mon0 type monitor
  ifconfig mon0 up
  ```
  Expect: no errors. If your SSH session dies here, you were on Wi-Fi. Power-cycle and reconnect over the wire.

- [ ] Monitor interface exists.

  ```sh
  iw dev
  ```
  Expect: `mon0` listed with `type monitor`.

- [ ] **CSI frames are arriving.**

  ```sh
  sudo tcpdump -i wlan0 dst port 5500
  ```
  Expect: a continuous stream of UDP packets to port 5500.

- [ ] **The rate is high enough.**

  ```sh
  sudo timeout 10 tcpdump -i wlan0 dst port 5500 -w /dev/null 2>&1 | tail -3
  ```
  Expect: `packets captured` divided by 10 is 100 or more.

  Roughly 10/sec means beacons only and the generator is not reaching the monitored channel.
  0/sec means the extractor is misconfigured or the channel is wrong.

- [ ] **The payloads are not all zeros.**

  ```sh
  sudo tcpdump -i wlan0 dst port 5500 -X -c 5
  ```
  Expect: varied bytes after the header. All `00` means a kernel/firmware mismatch or a channel mismatch, not a traffic problem.

- [ ] **The signal responds to a person.** Have someone walk between the router and the Pi while you watch the payloads.

  Expect: visibly different bytes between frames.
  If the rate is healthy and nothing ever changes, suspect the geometry before the firmware.

---

## Phase 7: save the working state, immediately

Do this the moment Phase 6 passes. Not after one more thing.

- [ ] Shut the Pi down cleanly, pull the card, image it on the bring-up laptop.

  ```sh
  diskutil list
  diskutil unmountDisk /dev/diskN
  sudo dd if=/dev/rdiskN of=/Users/<you>/radar-backups/radar-pi-working-$(date +%Y%m%d-%H%M).img bs=4m status=progress
  ```
  Expect: an image file roughly the size of the card. **Use the fully-expanded path, not `~`** — in `zsh`, `of=~/path` can silently fail to expand and `dd` errors "No such file or directory" against a directory that genuinely exists. Also run this in a real interactive terminal, not backgrounded — `sudo` needs a TTY for the password.

  Done 2026-09-19: `radar-pi-working-20260919-1454.img`, 15.6GB, ~3 minutes at ~86MB/s.

- [ ] Copy that image somewhere that is not only the laptop that made it.
- [ ] Capture a CSI session for replay. Do this even though live CSI is healthy.

  ```sh
  sudo tcpdump -i wlan0 dst port 5500 -w ~/csi-session-$(date +%Y%m%d-%H%M).pcap
  ```
  Expect: a growing pcap. Let it run through a representative sequence, including a fall.

  A first 60-second session was captured 2026-09-19 (`csi-session-20260919-1510.pcap`, ~4300 packets) to prove the pipeline end to end — **not yet the representative sequence with a staged fall this step calls for.** Capture that one during the actual house shoot.

- [ ] Pull the pcap off the Pi and store it with the disk image.

  ```sh
  scp radar-pi:~/csi-session-*.pcap ~/radar-backups/
  ```
  The venue demo runs on this file. It is not a backup, it is Sunday's primary input.

- [ ] Record in this file: the image filename, the kernel version, the channel, the router MAC, the base64 blob, and the `makecsiparams` path. All of it, in one place.

  Done, 2026-09-19 — see the full recorded-values table in `sensor/CLAUDE.md` ("Recorded values, from the 2026-09-19 bring-up session"). Summary: kernel `6.12.109+rpt-rpi-v8` (armhf), channel 40/80MHz, router's real `Radar-5g` BSSID `58:d8:12:3c:f5:63` (not the label MAC), `makecsiparams` at `~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams`.

---

## Phase 8: the agent sees a person

- [ ] The `sensor/` layer is producing the output contract in `sensor/CLAUDE.md`, with a populated `occupancy` array.
- [ ] `agents/occupancy` is consuming it and reporting at least one presence with a `zone` and a `confidence`.
- [ ] `calibration.healthy` is `true` and `baseline_age_s` is climbing sensibly.

  Remember that `occupancy` is the one tier 1 agent that genuinely needs a baseline, and the baseline is a rolling percentile with deliberately slow adaptation, not a calibration ritual.
  If a motionless person disappears after a few minutes, the adaptation constant is too fast. That is the worst bug available to this project.

- [ ] Walk out of the space and confirm the presence count drops. Walk back in and confirm it comes back.

---

## Definition of done

All of these are true at the same time:

1. The Pi is running the `nexmon_csi` patch via the `Makefile.rpi` path — kernel doesn't need to be 4.19/5.4/5.10, that plan is superseded (see `sensor/CLAUDE.md`). **Know what kernel is actually on the card** (`uname -r`) rather than assuming.
2. The generator device is associated at `PHY Mode: 802.11ac` on the fixed channel the router is pinned to.
3. The traffic generator is running and the Pi is seeing CSI packets on port 5500 well above the 10Hz beacon-only floor. **Target 100+/sec; our own achieved rate was 30-70/sec**, which was sufficient to confirm the pipeline works — don't block on hitting 100 if there's no time left to chase it.
4. Payloads are non-zero. **A raw byte-diff "does it respond to a person" test is not valid evidence either way** — per-packet phase noise swamps it; that needs proper per-subcarrier CSI parsing, which is downstream `sensor/` software, not a hardware check.
5. A `dd` image of the working microSD exists on at least two machines.
6. A recorded CSI session pcap exists, covering a representative sequence, stored with the image.
7. `agents/occupancy` reports a presence when someone is in the space and stops reporting one when they leave.
8. The channel, kernel version, router MAC, base64 blob, and image filename are all written down in these files rather than in someone's scrollback.

Item 5 and item 6 are the ones people skip and the ones that save the weekend.

**Items 1-6 confirmed 2026-09-19.** Item 7 depends on `agents/occupancy` existing, which it doesn't yet — that's the next risk item, not a hardware one.

---

## If you are stuck

Work the troubleshooting table in the relevant guide first:

- Pi, kernel, build, monitor mode, zero payloads: [raspberry-pi-4b.md](raspberry-pi-4b.md)
- Band, channel, steering, subnet: [router-archer-ax1450.md](router-archer-ax1450.md)
- Packet rate, throttling, Internet Sharing: [macbook-traffic-generator.md](macbook-traffic-generator.md)
- Flat signal with a healthy packet rate: [assembly-and-placement.md](assembly-and-placement.md)

If none of those fixes it and the timebox has expired, **the fallback ladder is in `sensor/CLAUDE.md`.**

Descend one level only when the level above is timeboxed out:

1. `nexmon_csi` on the Pi, live CSI from the router. **Achieved 2026-09-19**, via `Makefile.rpi` rather than the originally-planned kernel-pinned patch.
2. Recorded CSI replay through the same pipeline. The downstream agents cannot tell the difference. Capture this while level 1 is working, not after it breaks. A first session exists (`csi-session-20260919-1510.pcap`); capture a proper representative one at the house shoot.
3. RuView's simulated data: `docker pull ruvnet/wifi-densepose:latest`. Honest fallback, but say so on stage rather than implying live hardware.

Whichever level you land on, the agent layer must not know which one it is.
`sensor/` exposes one interface and what is behind it is our problem.

And keep the honesty rule in view.
The agent, its ANS identity, its certificate, its card, and its contract are always real.
Simulated inputs are labeled in the data itself, and said out loud on stage before anyone asks.
