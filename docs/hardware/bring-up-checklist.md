# Bring-up checklist

One linear path from unboxed hardware to "CSI frames are flowing and `agents/people` sees a person."

Work top to bottom.
Do not skip ahead.
Every step has a verification command and the output you should see.
If a step fails, the matching guide has a troubleshooting table.

Before you start, note the time and agree a timebox with the team.
`sensor/CLAUDE.md` is explicit: if CSI is not flowing by that deadline, drop to the fallback ladder and do not look back.

Timebox agreed: `TBD - decide and record here.`

---

## Phase 0: before touching anything

- [ ] Read `sensor/CLAUDE.md`, at least "The risk, stated plainly" and "Fallback ladder".
- [ ] Read the geometry rule in [assembly-and-placement.md](assembly-and-placement.md). It is the failure that wastes the most time.
- [ ] Confirm the bill of materials is all present: Pi 4B, USB ethernet adapter, Cat5, microSD, 5V/3A USB-C supply, Archer AX1450 and its supply, the MacBook.

  No further hardware is being purchased. If something is missing, the answer is the fallback ladder, not a store.

- [ ] Note what is deliberately **not** on that list: a monitor, a keyboard, a mouse, and an HDMI cable.

  The Pi runs headless for the entire project and none of those are needed.
  The MacBook is the Pi's screen, over SSH on the Cat5.
  Phase 2 sets that up, and it has to be set up before first boot rather than after.

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

  Chosen channel: `TBD - decide and record here.`

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

## Phase 2: flash and boot the Pi, headless

There is no monitor, no keyboard, and no mouse on the Pi at any point in this project.
Everything below is either done on the MacBook or over SSH from the MacBook.
The credentials have to be written onto the card **before** first boot, because there is no screen on which to type them afterwards.

### Flash the card

- [ ] Identify a Raspberry Pi OS **Legacy, 32-bit** image whose kernel is 4.19, 5.4, or 5.10. Record the exact filename in [raspberry-pi-4b.md](raspberry-pi-4b.md).

  Imager hides these under "Raspberry Pi OS (other)".
  A release name is not evidence. Only `uname -r` on first boot is.

- [ ] In Raspberry Pi Imager, choose Device: Raspberry Pi 4, then the image above, then the microSD card.
- [ ] **Before writing**, open the settings editor (the gear icon, or "Edit Settings" on the "use OS customisation?" prompt) and set every row of this table.

  | Setting | Value | Why it matters |
  |---|---|---|
  | Hostname | `hawkeye-pi` | This is how you find the Pi. Without it you are reading DHCP leases off the router all weekend. |
  | Enable SSH | on, password or public key | This is the only way in. Forgetting it means reflashing. |
  | Username | `hawkeye` | Every path in these guides assumes it. Changing it means editing the build steps. |
  | Password | `TBD - decide and record here.` | Write it down and tell the team before you write the card. |
  | Configure wireless LAN | **off, empty** | The Pi's network path is the Cat5. A configured `wpa_supplicant` fights `nexmon_csi` for `wlan0` in Phase 6. |
  | Locale and timezone | whatever is convenient | Does not affect CSI. |

- [ ] Write, and let it verify. Do not skip the verify.

- [ ] If you already flashed without the settings editor, do the manual equivalent rather than reflashing.

  ```sh
  # The boot partition is bootfs on recent images and boot on older ones.
  # Check what actually mounted rather than assuming.
  ls /Volumes/

  touch /Volumes/bootfs/ssh
  echo "hawkeye:$(openssl passwd -6)" > /Volumes/bootfs/userconf.txt
  ```
  Expect: an `ssh` file and a `userconf.txt` on the boot partition.
  Do **not** create `wpa_supplicant.conf`.

### First boot, which you cannot watch

- [ ] Insert the card. Plug the USB ethernet adapter into the Pi and the Cat5 from adapter to a router LAN port.
- [ ] Power the Pi from the kit's 5V/3A wall supply. Never from a router or laptop USB port.

  A brownout under load corrupts the card silently. It does not reboot where you can see it.

- [ ] Wait about 60 seconds. First boot resizes the filesystem and reboots itself once, so it is slower than every boot after it.
- [ ] Pi is reachable over the wire.

  ```sh
  ping -c 3 hawkeye-pi.local
  ssh hawkeye@hawkeye-pi.local
  ```
  Expect: replies, then a shell prompt. If mDNS fails, find the lease in Advanced > Network > DHCP Server > DHCP Client List.

  If nothing appears in the lease list either, the Pi did not get far enough to reach the network.
  See "The Pi never appears on the network" at the bottom of this file.
  Do not start swapping cables until you have read the boot partition back on the MacBook.

- [ ] **The kernel check. This one decides the night.**

  ```sh
  uname -r
  ```
  Expect: a version starting `4.19.`, `5.4.`, or `5.10.`.

  Anything else: stop, reflash, do not build.

  Recorded kernel: `TBD - decide and record here.`

- [ ] Chip is the expected one.

  ```sh
  ls /lib/firmware/brcm/ | grep 43455
  ```
  Expect: `brcmfmac43455-sdio.bin` and related files.

- [ ] Reserve the Pi's DHCP address on the router, against the **USB ethernet adapter's** MAC.

  Reserved address: `TBD - decide and record here.`

  Note the MAC belongs to the adapter, not the Pi's onboard ethernet, and not `wlan0`.
  Reserving the wrong one produces a Pi that moves address after a reboot and looks like it died.

### Make the MacBook the console

The Pi's screen is a terminal on your Mac. Set it up once, now, rather than during Phase 6 when something is on fire.

- [ ] Install `tmux` on the Pi so a long-running build or capture survives a dropped SSH session.

  ```sh
  sudo apt-get update && sudo apt-get install -y tmux
  tmux new -s bringup
  ```
  Expect: a status bar at the bottom of the terminal.
  Detach with `ctrl-b d`, reattach with `tmux a -t bringup`.

  Run Phase 4's build and Phase 6's capture inside tmux.
  Without it, closing the laptop lid kills them.

- [ ] Confirm you can open a second session at the same time, so you can watch one thing while doing another.

  ```sh
  # in a second MacBook terminal tab
  ssh hawkeye@hawkeye-pi.local 'uptime'
  ```
  Expect: a load average, and your first session unaffected.

- [ ] Decide how code gets onto the Pi, and use only that way.

  ```sh
  # push from the MacBook, fastest to iterate
  rsync -av --exclude '.git' sensor/ hawkeye@hawkeye-pi.local:~/sensor/

  # or pull on the Pi, which makes "what is actually running" answerable
  ssh hawkeye@hawkeye-pi.local 'cd ~/VTHacks && git pull && git rev-parse --short HEAD'
  ```
  Expect: files present on the Pi under `~/sensor/`.

  Mixing the two is how you spend an hour debugging code the Pi is not running.

- [ ] Optional, and worth the five minutes: connect VS Code to the Pi with Remote-SSH, host `hawkeye-pi.local`.

  That gives an editor, a file tree, and a terminal on the Pi in one window, which is the whole of what a monitor would have given you.

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

Start this, then do Phase 5 while it compiles.
Run all of it inside the tmux session from Phase 2.
The nexmon base build takes long enough that a dropped SSH session during it is a real risk, and losing it means starting the compile over.

- [ ] Hold the kernel packages so nothing upgrades them.

  ```sh
  sudo apt-mark hold raspberrypi-kernel raspberrypi-kernel-headers
  ```
  Expect: `raspberrypi-kernel set on hold.`

- [ ] Install build dependencies and reboot.

  ```sh
  sudo apt-get update
  sudo apt-get install -y raspberrypi-kernel-headers git libgmp3-dev gawk qpdf \
    bison flex make xxd automake autoconf libtool texinfo
  sudo reboot
  ```

- [ ] Kernel did not move.

  ```sh
  uname -r
  ```
  Expect: the same string you recorded above. If it changed, reflash.

- [ ] The two armhf libraries upstream requires are present.

  ```sh
  ls -l /usr/lib/arm-linux-gnueabihf/libisl.so.10 /usr/lib/arm-linux-gnueabihf/libmpfr.so.4
  ```
  Expect: both listed. If missing, build from `buildtools/` per the upstream README.

- [ ] Build the nexmon base.

  ```sh
  sudo su
  cd /home/hawkeye && git clone https://github.com/seemoo-lab/nexmon.git && cd nexmon
  source setup_env.sh && make
  ```
  Expect: completes without error. This takes a while on a Pi 4B.

- [ ] Build and install the CSI firmware patch.

  ```sh
  cd patches/bcm43455c0/7_45_189/
  git clone https://github.com/seemoo-lab/nexmon_csi.git
  cd nexmon_csi && make install-firmware
  ```
  Expect: completes without error.

- [ ] Build and install `nexutil`.

  ```sh
  cd /home/hawkeye/nexmon/utilities/nexutil/ && make && make install
  ```

- [ ] Tools are callable.

  ```sh
  which nexutil
  find /home/hawkeye/nexmon -name makecsiparams -type f
  ```
  Expect: a path for each. Record the `makecsiparams` path.

- [ ] Reboot so the patched firmware is the one that loads.

---

## Phase 5: traffic generator

- [ ] MacBook is on the 5GHz SSID with `PHY Mode: 802.11ac` (verified in Phase 1).
- [ ] Start the generator.

  ```sh
  sudo caffeinate -i ping -i 0.01 192.168.0.1
  ```
  Expect: a continuous stream of replies. If it errors on the interval, you forgot `sudo`.

- [ ] Confirm the rate on the MacBook side: interrupt after ~20 seconds and read the summary.

  Expect: transmitted divided by elapsed seconds close to 100.

- [ ] Restart it and leave it running for the rest of the bring-up.

  The script at `sensor/tools/trafficgen.sh` in [macbook-traffic-generator.md](macbook-traffic-generator.md) does start, stop, and status.

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

- [ ] Shut the Pi down cleanly, pull the card, image it on the MacBook.

  ```sh
  diskutil list
  diskutil unmountDisk /dev/diskN
  sudo dd if=/dev/rdiskN of=~/hawkeye-pi-working.img bs=4m status=progress
  ```
  Expect: an image file roughly the size of the card.

- [ ] Copy that image somewhere that is not only the MacBook.
- [ ] Capture a CSI session for replay. Do this even though live CSI is healthy.

  ```sh
  sudo tcpdump -i wlan0 dst port 5500 -w /home/hawkeye/csi-session-$(date +%Y%m%d-%H%M).pcap
  ```
  Expect: a growing pcap. Let it run through a representative sequence, including someone going still and staying still.

- [ ] Pull the pcap off the Pi and store it with the disk image.

  The venue demo runs on this file. It is not a backup, it is Sunday's primary input.

- [ ] Record in this file: the image filename, the kernel version, the channel, the router MAC, the base64 blob, and the `makecsiparams` path. All of it, in one place.

---

## Phase 8: the agent sees a person

- [ ] The `sensor/` layer is producing the output contract in `sensor/CLAUDE.md`, with a populated `occupancy` array.
- [ ] `agents/people` is consuming it and reporting at least one presence with a `zone` and a `confidence`.
- [ ] `calibration.healthy` is `true` and `baseline_age_s` is climbing sensibly.

  Remember that `occupancy` is the one tier 1 agent that genuinely needs a baseline, and the baseline is a rolling percentile with deliberately slow adaptation, not a calibration ritual.
  If a motionless person disappears after a few minutes, the adaptation constant is too fast. That is the worst bug available to this project.

- [ ] Walk out of the space and confirm the presence count drops. Walk back in and confirm it comes back.

---

## Definition of done

All of these are true at the same time:

1. `uname -r` on the Pi is 4.19, 5.4, or 5.10, and the kernel packages are held.
2. The MacBook is associated at `PHY Mode: 802.11ac` on the fixed channel the router is pinned to.
3. The traffic generator is running and the Pi is seeing 100 or more CSI packets per second on port 5500.
4. Payloads are non-zero and visibly change when a person moves between the router and the Pi.
5. A `dd` image of the working microSD exists on at least two machines.
6. A recorded CSI session pcap exists, covering a representative sequence, stored with the image.
7. `agents/people` reports a presence when someone is in the space and stops reporting one when they leave.
8. The channel, kernel version, router MAC, base64 blob, and image filename are all written down in these files rather than in someone's scrollback.

Item 5 and item 6 are the ones people skip and the ones that save the weekend.

---

## If you are stuck

Work the troubleshooting table in the relevant guide first:

- Pi, kernel, build, monitor mode, zero payloads: [raspberry-pi-4b.md](raspberry-pi-4b.md)
- Band, channel, steering, subnet: [router-archer-ax1450.md](router-archer-ax1450.md)
- Packet rate, throttling, Internet Sharing: [macbook-traffic-generator.md](macbook-traffic-generator.md)
- Flat signal with a healthy packet rate: [assembly-and-placement.md](assembly-and-placement.md)

### The Pi never appears on the network

This is the one failure a monitor would have made obvious, so work it deliberately rather than by swapping cables.

1. Confirm the Pi has power and is doing something.

   The red PWR LED solid means power is good.
   The green ACT LED should flicker as it reads the card.
   Solid green and never flickering means it is not booting off the card at all.

2. Confirm it is not a network problem before assuming it is a boot problem.

   Check the router's DHCP client list for any new lease.
   Try the Pi's onboard ethernet port with the Cat5 directly, temporarily, to rule out the USB adapter.

3. Read the card back on the MacBook. This is the substitute for a screen.

   ```sh
   # power the Pi down, pull the card, insert it into the MacBook
   ls /Volumes/bootfs/ssh /Volumes/bootfs/userconf.txt
   ```
   Expect: both present. If `ssh` is missing, SSH was never enabled and the card must be redone.
   If a `wpa_supplicant.conf` is present, delete it.

4. If the card looks right and it still never appears, reflash rather than debugging further.

   A card that fails verification writes an image that boots partway and stops, which looks exactly like a dead Pi.

A USB-TTL serial console on the GPIO header would show the boot log directly and settle this in seconds.
We do not own one and nothing further is being purchased, so the card readback above is the documented recovery route.
If someone on the team already owns a USB-TTL adapter, say so and this section gets a faster first step.

If none of those fixes it and the timebox has expired, **the fallback ladder is in `sensor/CLAUDE.md`.**

Descend one level only when the level above is timeboxed out:

1. `nexmon_csi` on the Pi, live CSI from the router.
2. Recorded CSI replay through the same pipeline. The downstream agents cannot tell the difference. Capture this while level 1 is working, not after it breaks.
3. RuView's simulated data: `docker pull ruvnet/wifi-densepose:latest`. Honest fallback, but say so on stage rather than implying live hardware.

Whichever level you land on, the agent layer must not know which one it is.
`sensor/` exposes one interface and what is behind it is our problem.

And keep the honesty rule in view.
The agent, its ANS identity, its certificate, its card, and its contract are always real.
Simulated inputs are labeled in the data itself, and said out loud on stage before anyone asks.
