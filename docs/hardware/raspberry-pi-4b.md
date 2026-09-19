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

**2. The kernel version silently decides whether the patch works.**
`nexmon_csi` is kernel-version-bound.
A mismatched kernel does not produce a build error or an install error.
It produces a firmware patch that builds, installs, and then emits all-zero or garbage CSI while every component reports healthy.

This is the single most likely way to spend a night and produce nothing.
Verify the kernel before you build, and never `apt full-upgrade` afterwards.

## Step 1: pick and flash the OS image

### The constraint that governs

`nexmon_csi` states support for Raspberry Pi OS kernels **4.19, 5.4, and 5.10**.
This is the governing constraint and it is upstream's own statement.
Upstream also notes that recent kernels no longer require the modified `brcmfmac` driver and gives separate guidance for newer setups, but we are not taking that path.
We are pinning to a supported kernel because a 36 hour build is not the place to debug an unsupported one.

Take a 32-bit Raspberry Pi OS image.
The build in step 4 links against `/usr/lib/arm-linux-gnueabihf/libisl.so.10` and `/usr/lib/arm-linux-gnueabihf/libmpfr.so.4`, which are armhf paths.
A 64-bit image puts you on a path upstream's Pi instructions do not describe.

### The exact image

`TBD - decide and record here.`
Write the exact image filename and its SHA256 in this file once someone has flashed a card that works.

How to determine it: on the Raspberry Pi OS download page, take a **Raspberry Pi OS (Legacy, 32-bit)** release whose kernel is in the 5.10 series, then confirm with `uname -r` on first boot before building anything.
Raspberry Pi Imager exposes legacy images under "Raspberry Pi OS (other)".
Do not accept an image because the release name looks right. The only thing that matters is what `uname -r` prints.

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
- Username and password: `TBD - decide and record here.` Pick one, write it down, and tell the team. Nothing is worse at 2am than not knowing the login.
- Locale and timezone: whatever is convenient, it does not affect CSI

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
# From the MacBook, on the same router
ping -c 3 hawkeye-pi.local
ssh hawkeye@hawkeye-pi.local
```

If mDNS does not resolve, find the Pi's lease in the router's client list.
See [router-archer-ax1450.md](router-archer-ax1450.md) for where that list lives.

**Now do the check that decides everything:**

```sh
uname -r
```

Expected: a version beginning `4.19.`, `5.4.`, or `5.10.`.

If it prints anything else, stop.
Do not build. Do not "try it anyway."
Reflash with a correct image.
Building against an unsupported kernel is how the night disappears.

Also confirm the chip is what we think it is:

```sh
ls /lib/firmware/brcm/ | grep 43455
# expect: brcmfmac43455-sdio.bin and friends
```

## Step 4: build and install nexmon_csi

Upstream: https://github.com/seemoo-lab/nexmon_csi
These are upstream's bcm43455c0 instructions, followed exactly.
Where they differ from what is written here, upstream wins.

This build takes a while on a Pi 4B.
Start it, then go configure the router.

```sh
sudo su
apt-get update
```

**Do not run `apt full-upgrade` and do not let anything upgrade the kernel.**
Upstream's instructions say `apt-get upgrade`.
On our pinned-kernel plan, an upgrade that pulls a new `raspberrypi-kernel` silently breaks the patch.
Safer sequence:

```sh
apt-mark hold raspberrypi-kernel raspberrypi-kernel-headers
apt-get install -y raspberrypi-kernel-headers git libgmp3-dev gawk qpdf \
  bison flex make xxd automake autoconf libtool texinfo
reboot
```

After the reboot, run `uname -r` again and confirm it did not move.

Then:

```sh
sudo su
cd /home/hawkeye
git clone https://github.com/seemoo-lab/nexmon.git
cd nexmon
```

Check the two libraries upstream calls out:

```sh
ls -l /usr/lib/arm-linux-gnueabihf/libisl.so.10
ls -l /usr/lib/arm-linux-gnueabihf/libmpfr.so.4
```

If either is missing, compile it from the sources shipped under `buildtools/` in the nexmon tree, following upstream's README for that step.
On a matching 32-bit legacy image they are normally already present.

Build the nexmon base:

```sh
source setup_env.sh
make
```

Then the CSI patch:

```sh
cd patches/bcm43455c0/7_45_189/
git clone https://github.com/seemoo-lab/nexmon_csi.git
cd nexmon_csi
make install-firmware
```

Then `nexutil`, which is how you configure the extractor at runtime:

```sh
cd /home/hawkeye/nexmon/utilities/nexutil/
make
make install
```

Sanity check:

```sh
which nexutil && nexutil -h 2>&1 | head -5
which makecsiparams
```

`makecsiparams` is built inside the `nexmon_csi` directory.
If `which` does not find it, call it by its full path or add its directory to `PATH`.
Record the path here once you know it: `TBD - decide and record here.`

Reboot once after `make install-firmware` so the patched firmware is the one that loads.

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
| `-m` | router MAC, or the traffic generator's MAC | Filters to frames from a specific transmitter. Filtering to the router captures its beacons and ping replies. Filtering to the MacBook captures the ping requests. Try both. |
| `-b` | `0x88` | Frame start byte filter, from upstream's own example. |

`<CHANNEL>` is `TBD - decide and record here.`
How to determine it: `sensor/CLAUDE.md` specifies 5GHz channel 36, 40, 44, or 48, all UNII-1 and non-DFS.
Pick whichever one the household's existing network is not on, set it in the router, and write the number here.
Channel separation matters: the Pi monitors exactly one channel, so shared channels mean household traffic contaminates the capture.

`<ROUTER_MAC>` is `TBD - decide and record here.`
How to determine it: read the label on the underside of the Archer AX1450, or from the MacBook while associated to it run `arp -n <gateway ip>`.

A worked example, using upstream's own numbers so you can see the shape.
Do not paste this verbatim, the channel is wrong for us:

```sh
makecsiparams -c 157/80 -C 1 -N 1 -m 00:11:22:33:44:55 -b 0x88
# m+IBEQGIAgAAESIzRFWqu6q7qrsAAAAAAAAAAAAAAAAAAA==
```

Save the blob your invocation prints.
You will paste it into the next step every time you start a capture.

## Step 6: put the interface into monitor mode and start the extractor

Order matters.
Run these as root, over the Cat5 SSH session, never over Wi-Fi.

```sh
sudo su

# 1. Load the parameters into the extractor
nexutil -Iwlan0 -s500 -b -l34 -v<YOUR_BASE64_BLOB>

# 2. Stop wpa_supplicant. Required on bcm43455c0.
pkill wpa_supplicant

# 3. Bring the interface up
ifconfig wlan0 up

# 4. Create the monitor interface. This is the bcm43455c0 form.
iw phy `iw dev wlan0 info | gawk '/wiphy/ {printf "phy" $2}'` interface add mon0 type monitor
ifconfig mon0 up
```

The moment step 4 completes, `wlan0` is no longer a usable station interface.
This is expected and is why you are on ethernet.

The `-s500 -b -l34` arguments are upstream's, and mean: parameter set 500, binary, length 34 bytes.
Do not change them.

## Step 7: verify CSI frames are actually arriving

The patched firmware emits one UDP packet **per configured core and spatial stream, per incoming frame matching the filter**, to port 5500.

```sh
sudo tcpdump -i wlan0 dst port 5500
```

### Healthy output

A continuous stream of UDP packets to port 5500, arriving at roughly the rate frames are crossing the channel.

With the MacBook ping running at `-i 0.01`, expect on the order of 100 or more packets per second.
With no traffic generator, expect roughly 10 per second, which is beacons only and is not enough.
See [macbook-traffic-generator.md](macbook-traffic-generator.md).

Count them rather than eyeballing:

```sh
sudo timeout 10 tcpdump -i wlan0 dst port 5500 -w /dev/null 2>&1 | tail -3
# read the "packets captured" line, divide by 10
```

Target is 100+ per second.
10 Hz is the floor and it is not enough for collapse or heart rate.

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

## Step 8: image the card, immediately

Do this the moment CSI flows.
Not later, not after one more thing works.

Shut down cleanly, pull the card, put it in the MacBook:

```sh
diskutil list                      # find the card, e.g. /dev/disk4
diskutil unmountDisk /dev/disk4
sudo dd if=/dev/rdisk4 of=~/hawkeye-pi-working.img bs=4m status=progress
```

Copy that image somewhere that is not the same machine.
If the card corrupts at 4am, this file is the difference between a demo and no demo.

## Step 9: capture a session for replay

Do this even if live CSI is healthy.
`sensor/CLAUDE.md` makes this explicit: recorded CSI replay is fallback level 2 and you capture it while level 1 is working, not after it breaks.

```sh
sudo tcpdump -i wlan0 dst port 5500 -w /home/hawkeye/csi-session-$(date +%Y%m%d-%H%M).pcap
```

Pull it off the Pi over the Cat5 and keep it with the disk image.
The venue demo runs on replayed CSI, so this file is not a backup, it is the primary input on Sunday.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Lost the SSH session the instant monitor mode came up | You were connected over Wi-Fi | Power-cycle, reconnect over Cat5, do not repeat |
| `uname -r` is not 4.19 / 5.4 / 5.10 | Wrong image, or a kernel upgrade happened | Reflash. Do not proceed. `apt-mark hold` the kernel packages afterwards. |
| CSI worked yesterday, not today, nothing changed | An unattended upgrade bumped the kernel | `uname -r`, compare with what is recorded here. Reflash from the `dd` image. |
| `make` fails on missing `libisl.so.10` or `libmpfr.so.4` | 64-bit image, or a legacy image missing armhf libs | Reflash 32-bit, or build them from `buildtools/` per upstream README |
| No UDP packets on port 5500 at all | Extractor never configured, or `mon0` not up | Re-run step 6 in order. Confirm with `ifconfig mon0` and `iw dev`. |
| Packets arrive, payloads are all zero | Kernel/firmware version mismatch, or channel mismatch | Check `uname -r`. Check `makecsiparams -c` matches the router's actual channel and width exactly. |
| Roughly 10 packets/sec and no more | No traffic generator running | Start the ping. See [macbook-traffic-generator.md](macbook-traffic-generator.md). |
| Packet rate is fine but the signal never moves | Router and Pi are on the same side of the space | Move them to opposite sides with people in between. See [assembly-and-placement.md](assembly-and-placement.md). |
| Signal is noisy and jittery for no reason | Traffic generator is a phone with Wi-Fi power save on | Use the MacBook. Phone power-save injects jitter that reads as CSI noise. |
| Capture is contaminated by traffic nobody is generating | Demo router shares a channel with the household network | Move the demo router to a different non-DFS channel |
| Pi reboots or the card corrupts under load | Powered from a router or laptop USB port | Use the kit's 5V/3A wall supply, always |
| `makecsiparams: command not found` | It is built inside the `nexmon_csi` directory, not installed to PATH | Call it by full path, or add that directory to PATH and record it above |
| Nothing in this table fits, and it is late | Timebox expired | Drop to the fallback ladder in `sensor/CLAUDE.md` and do not look back |

## What not to claim about this board

- It does not see through walls "like a camera." It resolves coarse, room-level zones, not coordinates.
- It does not identify people. Presence IDs are stable within a session only.
- It does not sense gas. Not CO, not oxygen, not smoke as a chemical. That is the air-quality reading `agents/master` takes, it comes through a separate sensor interface, and on this build that reading is simulated and labeled `demo-trigger`.
