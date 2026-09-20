# Raspberry Pi 4B

The only device in Hawk Eye that measures anything.
Everything in `agents/` consumes what comes off this board.

Read `sensor/CLAUDE.md` before starting.
This guide is the procedure; that file is the reasoning and the stop conditions.

## What it is and why it is this board

The Pi 4B carries a Broadcom BCM43455c0 Wi-Fi chip.
That chip is one of the four chips `nexmon_csi` supports, with firmware `7_45_189` covering Raspberry Pi 3B+, 4B, and 5.
`nexmon_csi` patches that firmware so the chip reports the per-frame Channel State Information it normally computes and discards.

That is the entire reason this board is in the project.
A Pi 5, a Pi Zero 2 W, or any other single-board computer would need a different or nonexistent patch.

What the patched firmware gives us:

- CSI extracted from OFDM-modulated 802.11a/g/n/ac frames
- One measurement per received frame matching the configured filter
- Bandwidths up to 80 MHz

What it does not give us:

- Anything from 802.11ax (HE) or 802.11be (EHT) frames. This is why the router must be forced to 802.11ac. See [router-archer-ax1450.md](router-archer-ax1450.md).
- Gas composition, of any kind. CSI is not a chemical sensor and the radio is not near the 60 GHz oxygen band.

## The trap that costs people the whole night, stated first

Two things, both of which fail silently.

**1. There is no Wi-Fi station interface while you are capturing.**
`nexmon_csi` holds `wlan0` in a monitor-adjacent state.
You cannot both capture CSI and use that interface for connectivity.
If you SSH in over Wi-Fi and then start the capture, you lose the Pi and have to physically power-cycle it.

The Cat5 cable and the ethernet adapter are mandatory, not a convenience.
Plan on SSH over the wire for the entire event.

**2. The kernel version used to silently decide whether the patch works — that's no longer our path.**
The original plan pinned to a specific old kernel because `nexmon_csi`'s classic patch is kernel-version-bound.
**Corrected 2026-09-19: we use the `Makefile.rpi` build path instead**, which tolerates a range of recent kernels via `update-alternatives` rather than a version-bound driver patch. See "Kernel reality, corrected 2026-09-19" in `sensor/CLAUDE.md` for why, and the recorded values there for what's actually on the card.
Still verify with `uname -r` after flashing regardless — knowing what's on the card matters even though this path is more forgiving of what it is.

## Step 1: pick and flash the OS image

### The constraint that governs, and why it changed

The original plan called for `nexmon_csi`'s classic patch, which states support for Raspberry Pi OS kernels **4.19, 5.4, and 5.10** and required pinning the kernel and holding the kernel packages.

**That plan doesn't survive contact with what Raspberry Pi Imager actually serves in 2026.** Its "Legacy, 32-bit" catalog entry no longer ships Bullseye/5.10 — it now ships Bookworm with a 6.12 kernel. Bullseye 32-bit was EOL'd May 2023, and hunting down an archived copy is its own risk for no real benefit, because `nexmon_csi` added a second, actively-maintained path for exactly this situation: `Makefile.rpi`, using `update-alternatives` for firmware switching instead of a kernel-bound patch. It works across recent kernels including 6.12, verified end to end on our exact chip and firmware.

**Still take a 32-bit (`armhf`) userspace image.** The cross-compiler toolchain nexmon bundles targets armhf regardless of which build path you use, and 32-bit userspace is what makes the `libisl`/`libmpfr` library paths below match what upstream's instructions assume. The kernel itself ends up 64-bit either way on a Pi 4 (`aarch64` kernel, `armhf` userspace) — that's normal for Raspberry Pi OS Bookworm and not something to fight.

### The exact image

Raspberry Pi Imager → Choose OS → "Raspberry Pi OS (other)" → **Raspberry Pi OS (Legacy, 32-bit)**. Pick **Lite**, not Full — this project runs headless for its entire life, so the desktop environment in Full is pure overhead (bigger image, slower first-boot resize, background services competing with the `nexmon_csi` compile for CPU on a Pi 4B).

Confirmed on a card that works, 2026-09-19: `uname -r` → `6.12.109+rpt-rpi-v8`. `dpkg --print-architecture` → `armhf`. `cat /etc/os-release` → Raspbian GNU/Linux 12 (bookworm).
Do not accept an image because the release name looks right — the only thing that matters is what `uname -r` and `dpkg --print-architecture` actually print once it's booted.

### Flash it

On the MacBook, with Raspberry Pi Imager:

1. Choose Device: Raspberry Pi 4.
2. Choose OS: Raspberry Pi OS (other) then the legacy 32-bit image identified above.
3. Choose Storage: the microSD card.
4. Click the gear or "Edit Settings" and configure headless setup before writing. See step 2.
5. Write, then let it verify.

If you would rather not use Imager's settings editor, the manual equivalents are in step 2.

## Step 2: headless setup

The Pi has no monitor or keyboard in this setup.
Everything below is configured on the boot partition before first boot.

In Raspberry Pi Imager's settings editor, set:

- Hostname: `hawkeye-pi` (or record whatever you choose here)
- Enable SSH, with password authentication or your public key
- Username and password: `radar`, password set at flash time (not recorded here — this file is git-tracked). Pick one, write it down somewhere the team can reach, and tell them. Nothing is worse at 2am than not knowing the login.
- Locale and timezone: whatever is convenient, it does not affect CSI

Newer Imager versions use a tabbed dialog (Hostname / Localization / User / Wifi / Remote access) instead of a single settings sheet with a gear icon. Same settings, different layout: SSH lives under **Remote access**, not a separate toggle. On the **Wifi** tab, leave the SSID field empty — there's no explicit "off" toggle in this layout, an empty SSID is how you skip it.

Right after flashing, set up an SSH key so you're not typing a password on every login for the rest of the build (there will be many):

```sh
# on the bring-up laptop
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_radar_pi -N "" -C "radar-pi-bringup"
ssh-copy-id -i ~/.ssh/id_ed25519_radar_pi.pub radar@radar-pi.local
```

And add an alias to `~/.ssh/config` so every command below can just say `ssh radar-pi`:

```
Host radar-pi
    HostName radar-pi.local
    User radar
    IdentityFile ~/.ssh/id_ed25519_radar_pi
    IdentitiesOnly yes
```

Leave Wi-Fi configuration **empty**.
The Pi does not use Wi-Fi for connectivity in this project, and a configured `wpa_supplicant` is one more thing that will fight the capture.

Manual equivalents, if you flashed without the settings editor.
Mount the boot partition and:

```sh
# Enable SSH on first boot
touch /Volumes/bootfs/ssh

# Create a user (replace the hash with the output of: openssl passwd -6)
echo 'hawkeye:<PASSWORD_HASH>' > /Volumes/bootfs/userconf.txt
```

The boot partition is named `bootfs` on recent images and `boot` on older ones.
Check what actually mounted rather than assuming.

Do not create `wpa_supplicant.conf`.

## Step 3: first boot and the kernel check

1. Insert the microSD.
2. Plug the USB ethernet adapter into the Pi and the Cat5 into the router's LAN port. See [assembly-and-placement.md](assembly-and-placement.md).
3. Plug in the kit's 5V/3A USB-C supply. The Pi 4B's USB-C port is power only. Never power the Pi from a router USB port. It browns out under load and corrupts the SD card rather than rebooting visibly.
4. Wait about 60 seconds.

Find it and log in:

```sh
# From the bring-up laptop, on the same router
ping -c 3 radar-pi.local
ssh radar-pi   # or: ssh radar@radar-pi.local
```

If mDNS does not resolve, find the Pi's lease in the router's client list.
See [router-archer-ax1450.md](router-archer-ax1450.md) for where that list lives.
If you're bringing the Pi up over a MacBook's Internet Sharing bridge rather than the router (see the headless-no-uplink note in `docs/hardware/bring-up-checklist.md`), the lease shows up in `/var/db/dhcpd_leases` on the Mac instead, or just `arp -a | grep 192.168.2`.

**Check the kernel, not because a specific version is required now, but because you should know what's actually on the card:**

```sh
uname -r
dpkg --print-architecture
```

Confirmed working 2026-09-19: `6.12.109+rpt-rpi-v8`, `armhf`. This is **not** the 4.19/5.4/5.10 the old kernel-pinned plan called for — see "Kernel reality, corrected 2026-09-19" in `sensor/CLAUDE.md`. Use the `Makefile.rpi` build path in Step 4 below regardless of which recent kernel you land on; don't reflash chasing a specific old version.

Also confirm the chip is what we think it is:

```sh
ls /lib/firmware/brcm/ | grep 43455
# expect: brcmfmac43455-sdio.bin and friends
```

## Step 4: build and install nexmon_csi via Makefile.rpi

**Corrected 2026-09-19. This replaces the old kernel-pinned build below** (kept at the bottom of this section for reference only — don't follow it on a current image).

Upstream: https://github.com/seemoo-lab/nexmon_csi, discussion #395 (`Makefile.rpi` for recent kernels). Verified end to end against `bcm43455c0` / `7_45_189` on Pi 4B, Bookworm, kernel `6.12.109`.

This build takes a while on a Pi 4B. Do it inside `tmux` — a dropped SSH session mid-compile means starting over.

```sh
tmux new -s bringup   # if not already in one; ctrl-b d to detach, tmux a -t bringup to reattach
```

Dependencies — this path isn't kernel-bound, so `full-upgrade` is safe here (unlike the old plan):

```sh
sudo apt-get update && sudo apt-get full-upgrade -y
sudo apt-get install -y git libgmp3-dev gawk qpdf bison flex make autoconf libtool \
  texinfo xxd libnl-3-dev libnl-genl-3-dev bc libssl-dev tcpdump
```

**Python 2.7**, needed by the `bcm43-tools`, no longer ships in Bookworm — pull it from Debian's archived Stretch repo. Its Release file is 8 years past EOL and unsigned, so mark the source line trusted (this alone, plus `--allow-unauthenticated` at install time, is what actually works — without `[trusted=yes]`, `apt-get update` hard-fails on the unsigned Release and never even indexes the package):

```sh
sudo cp /etc/apt/sources.list /tmp/sources.list.bak
echo 'deb [trusted=yes] http://archive.debian.org/debian/ stretch contrib main non-free' | sudo tee -a /etc/apt/sources.list
sudo apt-get update
sudo apt-get install -y python2.7 --allow-unauthenticated
sudo cp /tmp/sources.list.bak /etc/apt/sources.list   # restore immediately, don't leave Stretch enabled
sudo apt-get update
```

Clone and build the nexmon base:

```sh
cd ~
git clone --depth=1 https://github.com/seemoo-lab/nexmon.git
cd nexmon
source setup_env.sh
sed -i '1 s/$/2.7/' $NEXMON_ROOT/buildtools/b43-v3/debug/b43-beautifier
make
```

Build and install `nexutil` (note `USE_VENDOR_CMD=1` — without it the firmware rejects the IOCTLs this path relies on):

```sh
cd $NEXMON_ROOT/utilities/nexutil
sudo -E make install USE_VENDOR_CMD=1
sudo setcap cap_net_admin+ep /usr/bin/nexutil
```

**The bundled ARM cross-compiler needs `libisl.so.10`/`libmpfr.so.4`, and Bookworm only ships newer SONAMEs (`libisl.so.23`, `libmpfr.so.6`).** This is the same library gap the old plan called out, just under different version numbers now. Symlink them — this is a compiler ABI shim, not a system downgrade, and it's the standard fix:

```sh
sudo ln -sf /usr/lib/arm-linux-gnueabihf/libisl.so.23 /usr/lib/arm-linux-gnueabihf/libisl.so.10
sudo ln -sf /usr/lib/arm-linux-gnueabihf/libmpfr.so.6 /usr/lib/arm-linux-gnueabihf/libmpfr.so.4
```

Clone and build the CSI patch, via `Makefile.rpi`:

```sh
cd $NEXMON_ROOT/patches/bcm43455c0/7_45_189/
git clone --depth=1 https://github.com/seemoo-lab/nexmon_csi.git
cd nexmon_csi
make -f Makefile.rpi install-firmware     # not `make install-firmware` — that's the old path
```

`unmanage` stops NetworkManager fighting for `wlan0`. **If `wlan0` was never associated to anything (our setup — WiFi is left unconfigured on this Pi by design), the `nmcli dev disconnect` sub-step fails with "device is not active" and `make` stops there before the rest of the target runs.** Finish it by hand:

```sh
make -f Makefile.rpi unmanage   # will likely error partway through; that's expected here
sudo nmcli dev set wlan0 managed no
sudo nmcli radio wifi off
sudo rfkill unblock wifi
```

Reload the driver with the patched firmware. This only touches the WiFi module, not Ethernet, so an SSH session over the Cat5 survives it fine:

```sh
make -f Makefile.rpi reload-full
```

Build `makecsiparams` (it ships as source under `utils/`, not prebuilt):

```sh
cd $NEXMON_ROOT/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams
make
```

Confirmed path, 2026-09-19: `~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams`.

Confirm the patch actually loaded:

```sh
dmesg | grep -i 'brcmfmac_c_preinit_dcmds\|Firmware:'
# expect a line ending "(nexmon.org/csi: <hash>)" with today's build date, not the stock BCM date
```

**None of this runtime state (unmanaged, monitor mode, extractor config) survives a reboot** — only the firmware install itself does (via `update-alternatives`). After every reboot, redo the `unmanage` block above and Step 6 below before expecting CSI to flow.

<details>
<summary>Old kernel-pinned build (do not use on a current image — kept for reference only)</summary>

```sh
sudo su
apt-get update
apt-mark hold raspberrypi-kernel raspberrypi-kernel-headers
apt-get install -y raspberrypi-kernel-headers git libgmp3-dev gawk qpdf \
  bison flex make xxd automake autoconf libtool texinfo
reboot
# after reboot, confirm uname -r did not move, then:
cd /home/hawkeye
git clone https://github.com/seemoo-lab/nexmon.git
cd nexmon
source setup_env.sh
make
cd patches/bcm43455c0/7_45_189/
git clone https://github.com/seemoo-lab/nexmon_csi.git
cd nexmon_csi
make install-firmware
cd /home/hawkeye/nexmon/utilities/nexutil/
make
make install
```

This only works on a genuinely old (4.19/5.4/5.10) kernel, which current Imager downloads no longer serve. See "Kernel reality, corrected 2026-09-19" in `sensor/CLAUDE.md`.

</details>

## Step 5: generate the CSI parameters

`makecsiparams` encodes what the chip should capture into a base64 blob that you hand to `nexutil`.

```sh
makecsiparams -c <CHANNEL>/<BANDWIDTH> -C 1 -N 1 -m <ROUTER_MAC> -b 0x88
```

Parameters, and what each means here:

| Flag | Value for us | Why |
|---|---|---|
| `-c` | `<channel>/80` | Must match the router exactly. Channel from the router's 5GHz setting, bandwidth 80MHz. See [router-archer-ax1450.md](router-archer-ax1450.md). |
| `-C` | `1` | Core bitmask. One core is enough and keeps the UDP rate manageable. |
| `-N` | `1` | Spatial stream bitmask. Same reasoning. |
| `-m` | router MAC, or the traffic generator's MAC | Filters to frames from a specific transmitter. Filtering to the router captures its beacons **(beacons are Management frames and don't match `-b 0x88` — see below)** and any ping replies it sends. Filtering to the traffic-generator device captures its outgoing ping requests, guaranteed at the ping rate regardless of whether the router answers. **We found the generator's own MAC more reliable in practice** — our router didn't consistently reply to ICMP aimed at its own gateway address, so filtering on the router left us with a near-empty capture even with a generator running. |
| `-b` | `0x88` | Frame start byte filter. **This is Frame Control byte `0x88` = Data type, QoS Data subtype.** It does not match beacons or other Management frames (those are `0x80`), so don't expect any packets under this filter until a traffic generator is actually producing data frames on the channel — zero packets with only a router present (no generator yet) is expected, not a fault. |

`<CHANNEL>` — recorded 2026-09-19: **40** (80MHz). `sensor/CLAUDE.md` specifies 5GHz channel 36, 40, 44, or 48, all UNII-1 and non-DFS; pick whichever the household/venue network isn't on. Channel separation matters: the Pi monitors exactly one channel, so shared channels mean outside traffic contaminates the capture.

`<ROUTER_MAC>` — **do not trust the label on the router.** The AX1450 uses a different MAC per radio/band; ours was off by one in the last octet between the label and the actual `Radar-5g` over-the-air BSSID. Get the real one from a scan while monitor mode is off:

```sh
sudo nexutil -m0                      # monitor mode off, if it was on
sudo /sbin/iw dev wlan0 scan | grep -B12 'SSID: <your 5GHz SSID>'
# look for the "BSS <mac>(on wlan0)" line and the freq line just above the SSID
```

The `freq:` line doubles as a channel sanity check (5200 MHz = channel 40, etc). `/sbin/iw` and `/sbin/ifconfig` — both exist but usually aren't on a non-interactive SSH shell's default `PATH`; use the full path or `sudo` (whose `secure_path` usually includes `/sbin`).

A worked example, using upstream's own numbers so you can see the shape.
Do not paste this verbatim, the channel is wrong for us:

```sh
makecsiparams -c 157/80 -C 1 -N 1 -m 00:11:22:33:44:55 -b 0x88
# m+IBEQGIAgAAESIzRFWqu6q7qrsAAAAAAAAAAAAAAAAAAA==
```

Save the blob your invocation prints.
You will paste it into the next step every time you start a capture.

## Step 6: put the interface into monitor mode and start the extractor

**Corrected 2026-09-19.** The `Makefile.rpi` / `USE_VENDOR_CMD=1` path sets monitor mode directly on `wlan0` at the firmware level via `nexutil -m`, rather than creating a separate `mon0` virtual interface with `iw`. Simpler, and it's what we actually used. (The old `iw phy ... add mon0 type monitor` approach, kept below, is for the classic kernel-pinned patch — don't mix the two.)

Order matters. Run these over the Cat5 SSH session, never over Wi-Fi.

```sh
# 1. Load the CSI extraction parameters into the firmware
sudo nexutil -Iwlan0 -s500 -b -l34 -v<YOUR_BASE64_BLOB>

# 2. Enable monitor mode at the firmware level
sudo nexutil -m1

# verify it took:
nexutil -m
# expect: monitor: 1
sudo /sbin/iw dev wlan0 info
# expect: channel matching what you generated params for, e.g. "channel 40 (5200 MHz), width: 80 MHz"
```

Note `iw dev wlan0 info` still reports `type managed` even with monitor mode on — that's expected under this vendor-command approach; `nexutil -m` is the actual source of truth, not the OS-reported interface type.

`wlan0` stops being a usable station interface the moment monitor mode is on. This is expected and is why you are on ethernet.

The `-s500 -b -l34` arguments are upstream's, and mean: parameter set 500, binary, length 34 bytes. Do not change them.

**None of this survives a reboot.** Re-run both `nexutil` commands (and the `unmanage` block from Step 4) every time the Pi restarts, before expecting CSI to flow again.

<details>
<summary>Old approach: separate mon0 interface via iw (classic kernel-pinned patch only)</summary>

```sh
sudo su
nexutil -Iwlan0 -s500 -b -l34 -v<YOUR_BASE64_BLOB>
pkill wpa_supplicant
ifconfig wlan0 up
iw phy `iw dev wlan0 info | gawk '/wiphy/ {printf "phy" $2}'` interface add mon0 type monitor
ifconfig mon0 up
```

</details>

## Step 7: verify CSI frames are actually arriving

The patched firmware emits one UDP packet **per configured core and spatial stream, per incoming frame matching the filter**, to port 5500.

```sh
sudo tcpdump -i wlan0 dst port 5500
```

### Healthy output

A continuous stream of UDP packets to port 5500, arriving at roughly the rate frames are crossing the channel.

With a generator running at `-i 0.01`, expect on the order of 100 packets per second in principle; **our own measured rate was 30-70/sec** filtering on the generator's MAC, well above the 10Hz floor but short of the 100+ target — not yet root-caused, plausibly 802.11 frame aggregation reducing distinct-frame count below the raw ping rate. Treat 100+ as the target to keep chasing if there's time, not a hard gate — 30-70/sec was sufficient to confirm the whole pipeline works.
With no traffic generator at all, expect roughly 10 per second (beacons only) — **and note that under our `-b 0x88` filter, even that 10/sec won't show up**, because beacons are Management frames and `0x88` matches Data/QoS-Data only. Zero packets with the router up but no generator running is the expected state, not a fault.
See [macbook-traffic-generator.md](macbook-traffic-generator.md).

Count them rather than eyeballing:

```sh
sudo timeout 10 tcpdump -i wlan0 dst port 5500 -w /dev/null 2>&1 | tail -3
# read the "packets captured" line, divide by 10
```

Target is 100+ per second.
10 Hz is the floor and it is not enough for a short motion transient or for heart rate.

### Dead output

Any of these means something is wrong:

- No packets at all
- Packets arriving but every CSI payload is zeros
- A burst at startup then nothing

All-zero payloads are the dangerous one, because `tcpdump` shows traffic and everything looks alive.
Dump payloads and look at them:

```sh
sudo tcpdump -i wlan0 dst port 5500 -X -c 5
```

If the bytes after the header are all `00`, the firmware patch is not extracting.
Go to the troubleshooting table.

### The sanity test that takes ten seconds

Watch the packet rate while someone waves a hand between the router and the Pi.
The rate should not change much, but the payloads should.
If you have anything plotting amplitude, the trace should visibly move.
If nothing moves no matter what anyone does in the room, suspect the geometry before you suspect the firmware.
See [assembly-and-placement.md](assembly-and-placement.md).

**A crude raw-byte-diff test is not a valid way to check this.** We tried computing frame-to-frame byte deltas across a "moving" and a "baseline" capture and got statistically identical results for both — not because geometry was bad, but because every raw CSI packet carries random per-packet phase noise (carrier/sampling frequency offset, AGC scaling — see "Phase and hardware sanitization" in `sensor/CLAUDE.md`) that swamps a hand-sized perturbation unless you actually parse the per-subcarrier I/Q values and average across them. That parsing is downstream `sensor/` software, not something to improvise as a hardware check. Eyeballing a proper amplitude plot (once one exists) is the real test; a naive byte-diff script is not evidence either way.

## Step 8: image the card, immediately

Do this the moment CSI flows.
Not later, not after one more thing works.

Shut down cleanly, pull the card, put it in the bring-up laptop:

```sh
diskutil list                      # find the card, e.g. /dev/disk4
diskutil unmountDisk /dev/disk4
sudo dd if=/dev/rdisk4 of=/Users/<you>/radar-backups/radar-pi-working-$(date +%Y%m%d-%H%M).img bs=4m status=progress
```

**Use the fully-expanded path, not `~`, in the `of=` argument.** In `zsh`, `~` doesn't reliably expand inside a `KEY=value`-shaped argument like `of=~/path` unless `MAGIC_EQUAL_SUBST` is on — `dd` can end up receiving a literal `~` character and fail with a confusing "No such file or directory: ~/..." even though the directory genuinely exists. `echo $HOME` first if unsure.

Also: `sudo dd` run as a backgrounded/non-interactive command fails with "a terminal is required to read the password" — run it in a real interactive terminal, not scripted.

Confirmed 2026-09-19: 15.6GB card imaged successfully in ~3 minutes at ~86MB/s. **Copy that image somewhere that is not the same machine.** If the card corrupts at 4am, this file is the difference between a demo and no demo.

## Step 9: capture a session for replay

Do this even if live CSI is healthy.
`sensor/CLAUDE.md` makes this explicit: recorded CSI replay is fallback level 2 and you capture it while level 1 is working, not after it breaks.

```sh
sudo tcpdump -i wlan0 dst port 5500 -w ~/csi-session-$(date +%Y%m%d-%H%M).pcap
```

Pull it off the Pi over the Cat5 and keep it with the disk image:

```sh
scp radar-pi:~/csi-session-*.pcap ~/radar-backups/
```

A first session was captured 2026-09-19 (60s, ~4300 packets) to prove the pipeline end to end. **Capture a longer, more representative one during the actual house shoot** — the docs call for "a representative sequence, including a fall," which this first one wasn't. The venue demo runs on replayed CSI, so this file is not a backup, it is the primary input on Sunday.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Lost the SSH session the instant monitor mode came up | You were connected over Wi-Fi | Power-cycle, reconnect over Cat5, do not repeat |
| `uname -r` isn't 4.19/5.4/5.10 | Expected on a current image — Imager no longer serves that kernel | Not a problem by itself. Use the `Makefile.rpi` build path in Step 4, not the old kernel-pinned one. |
| CSI worked yesterday, not today, nothing changed | An unattended upgrade bumped the kernel | Since we're on `Makefile.rpi`, a kernel bump alone shouldn't break this — check `dmesg` for the firmware version line first before assuming the worst. Reflash from the `dd` image if truly stuck. |
| `cc1: error while loading shared libraries: libisl.so.10` during `make -f Makefile.rpi install-firmware` | Bookworm only ships `libisl.so.23`/`libmpfr.so.6`, not the old SONAMEs the bundled cross-compiler wants | Symlink them — see Step 4. This is expected on a current image, not a sign anything's wrong. |
| `apt-get install python2.7 --allow-unauthenticated` says "no installation candidate" | The Stretch archive's Release file is unsigned and apt refused to index it at all during `apt-get update` | Add `[trusted=yes]` to the sources.list line itself, not just `--allow-unauthenticated` at install time — the two are different apt trust checks. See Step 4. |
| `makecsiparams` produces a blob, but zero CSI packets ever arrive, no errors anywhere | Filtering `-m` on the label's printed MAC, which isn't the router's actual radio MAC for that band | Get the real MAC from a scan (monitor mode off), not the label. See Step 5. |
| Zero CSI packets with the router powered on and broadcasting, before any traffic generator is running | **Expected**, not a fault — `-b 0x88` only matches Data/QoS-Data frames, and beacons are Management frames | Start the traffic generator. Zero packets here doesn't mean anything is broken. |
| CSI flowed a minute ago, now zero, nothing changed | A momentary gap in traffic-generator output, or just RF variance | Recheck with a longer capture window (10-15s) before concluding something broke — we saw exactly this, a transient zero that resolved on the next check. |
| `make` fails on missing `libisl.so.10` or `libmpfr.so.4` (old kernel-pinned path only) | 64-bit image, or a legacy image missing armhf libs | Reflash 32-bit, or build them from `buildtools/` per upstream README |
| No UDP packets on port 5500 at all | Extractor never configured, or monitor mode not actually on | Re-run Step 6 in order. Confirm with `nexutil -m` (expect `monitor: 1`), not `iw dev` — `iw` still reports `type managed` under this build path even when monitor mode is genuinely on. |
| Packets arrive, payloads are all zero | Kernel/firmware version mismatch, or channel mismatch | Check `dmesg` for the firmware version line. Check `makecsiparams -c` matches the router's actual channel and width exactly. |
| Roughly 10 packets/sec and no more | No traffic generator running, or it's a phone with power-save on | Start a generator on a laptop, not a phone if avoidable. See [macbook-traffic-generator.md](macbook-traffic-generator.md). |
| Filtering on the router's MAC gives almost nothing even with a generator running | Router isn't reliably replying to ICMP aimed at its own gateway address | Filter on the traffic-generator device's own MAC instead — its outgoing request frames are guaranteed regardless of replies. See Step 5. |
| Packet rate is fine but the signal never moves | Router and Pi are on the same side of the space, or the test itself is too crude to show anything (see note above Step 8) | Move them to opposite sides with people in between. See [assembly-and-placement.md](assembly-and-placement.md). Don't trust a raw byte-diff test either way. |
| Signal is noisy and jittery for no reason | Traffic generator is a phone with Wi-Fi power save on | Use a laptop. Phone power-save injects jitter that reads as CSI noise. |
| Capture is contaminated by traffic nobody is generating | Demo router shares a channel with the household network | Move the demo router to a different non-DFS channel |
| Pi reboots or the card corrupts under load | Powered from a router or laptop USB port | Use the kit's 5V/3A wall supply, always |
| `makecsiparams: command not found` | It's not built by default — it's source under `utils/makecsiparams/`, needs its own `make` | `cd` into that directory and `make` it. Path once built: `~/nexmon/patches/bcm43455c0/7_45_189/nexmon_csi/utils/makecsiparams/makecsiparams`. |
| `sudo dd of=~/path/file.img` fails "No such file or directory" even though the directory exists | zsh doesn't reliably expand `~` inside a `KEY=value` argument | Use the fully-expanded path (`/Users/you/...`), not `~`. See Step 8. |
| `sudo` command fails "a terminal is required to read the password" when run in the background | Backgrounded/non-interactive shells can't prompt for a sudo password | Run it in a real foreground interactive terminal instead. |
| macOS Internet Sharing toggle shows "on" but the shared interface gets no IP, and `log show` mentions `BRDGADD: failed Resource busy` | A known macOS flake — the bridge interface didn't actually attach | Toggle Internet Sharing off, physically unplug and replug the USB-Ethernet adapter, then toggle back on. Worked reliably for us; a full reboot is the fallback if it doesn't. |
| Nothing in this table fits, and it is late | Timebox expired | Drop to the fallback ladder in `sensor/CLAUDE.md` and do not look back |

## What not to claim about this board

- It does not see through walls "like a camera." It resolves coarse, room-level zones, not coordinates.
- It does not identify people. Presence IDs are stable within a session only.
- It does not sense gas. Not CO, not oxygen, not smoke as a chemical. That is the air-quality reading `agents/master` takes, it comes through a separate sensor interface, and on this build that reading is simulated and labeled `demo-trigger`.
