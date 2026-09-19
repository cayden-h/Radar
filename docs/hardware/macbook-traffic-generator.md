# The MacBook

The MacBook has three jobs in this project.
Only the first one is easy to forget and catastrophic to forget.

1. **Traffic generator.** It makes the frames the Pi measures.
2. **Dev machine.** It builds and runs the agents, and runs the iOS app in the simulator or deploys it to the iPhone.
3. **Internet Sharing host**, at a venue only. Not at the house.

Read `sensor/CLAUDE.md` for why job 1 exists.
This guide is how to do it and how to prove it is working.

## The failure mode, in full

This is the one that produces a healthy-looking system that measures nothing.

**CSI is computed per received frame.**
The chip measures the channel from an actual transmission crossing the air.
There is no CSI without a frame.
No frames, no measurements, no matter how good the model downstream is.

A router with nothing connected still beacons.
But it beacons at roughly ten times a second.

Here is what that rate is worth, from `sensor/CLAUDE.md`:

| | Signal | Sample rate needed |
|---|---|---|
| Breathing | 0.1-0.5 Hz | ~10 Hz, marginal |
| Fall transient | 0.5-1s event | 10 Hz too coarse to characterize |
| Heart rate | 0.7-2 Hz, buried under breathing harmonics | 20-50 Hz and up |

So at beacon rate:

- Breathing is marginal and noisy.
- A fall transient cannot be characterized, and `still_down_s` is the clinical variable the whole pitch rests on.
- Heart rate is simply not available.

10 Hz is the floor and it is not enough.
**Target 100+ Hz.**

### Why this is worse than an outage

Nothing reports an error.

`tcpdump` shows UDP packets arriving on port 5500.
The extractor is configured.
The monitor interface is up.
The Pi is reachable.
Every health check in the pipeline is green.

The data is just too sparse to resolve the things the demo depends on, and the symptom shows up three layers away as "collapse detection is unreliable" or "heart rate never populates."
Somebody then spends hours tuning a detector that has nothing to work with.

Check the packet rate first, every time, before debugging anything downstream.

## The fix

Put the MacBook on the router's 5GHz Wi-Fi and ping the gateway at 100 packets per second.

```sh
sudo ping -i 0.01 192.168.0.1
```

That is it.
Every request and every reply is a frame crossing the monitored channel, so you get traffic in both directions from one command.

Notes on that command:

- Fractional `-i` below 0.2 seconds requires root on macOS. That is why `sudo` is there, and it will prompt for a password. Do not background it before it has prompted.
- `-i 0.01` is 100 packets per second outbound, plus 100 replies, so roughly 200 frames per second on the air.
- `192.168.0.1` is the Archer AX1450's factory gateway address. Confirm it rather than assuming. See below.

### The MacBook must be on the monitored band and channel

The generator has to be on the **same band and channel the Pi monitors**.
This is the reason band steering has to be off on the router.

Join the 5GHz SSID explicitly by name, not the 2.4GHz one, and confirm:

```sh
system_profiler SPAirPortDataType | grep -A 12 "Current Network"
```

Check three lines in that output:

- The SSID is the 5GHz one
- `Channel` matches what is configured on the router and what you passed to `makecsiparams -c`
- `PHY Mode` is `802.11ac`, not `802.11ax`

If PHY Mode says `802.11ax`, stop.
`nexmon_csi` extracts nothing from HE frames.
Go fix the router's Mode dropdown. See [router-archer-ax1450.md](router-archer-ax1450.md).

### Finding the gateway, if it is not 192.168.0.1

```sh
# The default route
route -n get default | grep gateway

# Or, per interface
netstat -rn -f inet | grep '^default'

# Which interface is the Wi-Fi one
networksetup -listallhardwareports
```

On most Macs the Wi-Fi interface is `en0`, but on a machine with a USB ethernet adapter attached the numbering can shift.
Use `networksetup -listallhardwareports` rather than guessing.

## Confirming the packet rate is actually being achieved

Asking for 100 packets per second and getting 100 packets per second are different things.
Power save, a sleeping display, or a weak link can all silently throttle it.

### On the MacBook

Let the ping run for a while, then interrupt it with Ctrl-C and read the summary:

```
2043 packets transmitted, 2041 packets received, 0.1% packet loss
```

Divide transmitted by elapsed seconds.
For `-i 0.01` you want that number close to 100.
If it is 30, something is throttling you.

### On the Pi, which is what actually matters

The Pi's view is the only view that counts.
Count the CSI UDP packets over a fixed window:

```sh
sudo timeout 10 tcpdump -i wlan0 dst port 5500 -w /dev/null 2>&1 | tail -3
```

Read the `packets captured` line and divide by 10.

| Rate seen on the Pi | Verdict |
|---|---|
| 0/sec | Extractor not configured, or wrong channel. Not a traffic problem. |
| ~10/sec | Beacons only. The generator is not running, or is on the wrong band. |
| 50-100/sec | Usable. Check for throttling. |
| 100+/sec | Healthy. Proceed. |

Do this check before every take.
It costs ten seconds and it is the single highest-value verification in the whole bring-up.

### Keep the Mac awake

A sleeping MacBook stops pinging.
Run the generator under `caffeinate`:

```sh
sudo caffeinate -i ping -i 0.01 192.168.0.1
```

`-i` on `caffeinate` prevents idle sleep while the command runs.

## A start/stop script

Save this as `sensor/tools/trafficgen.sh` (create the directory if it does not exist), `chmod +x` it, and stop retyping the command at 2am.

```sh
#!/bin/sh
# Hawk Eye traffic generator.
# Keeps frames crossing the monitored channel so the Pi has something to measure.
# Usage: sudo ./trafficgen.sh start [gateway]
#        sudo ./trafficgen.sh stop
#        ./trafficgen.sh status

set -e

PIDFILE=/tmp/hawkeye-trafficgen.pid
LOGFILE=/tmp/hawkeye-trafficgen.log

gateway() {
  if [ -n "$1" ]; then
    echo "$1"
  else
    route -n get default 2>/dev/null | awk '/gateway/ {print $2}'
  fi
}

case "$1" in
  start)
    GW=$(gateway "$2")
    if [ -z "$GW" ]; then
      echo "No default gateway found. Is the Mac on the router's Wi-Fi?" >&2
      exit 1
    fi
    if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
      echo "Already running, pid $(cat $PIDFILE)"
      exit 0
    fi
    echo "Band check:"
    system_profiler SPAirPortDataType | grep -E 'PHY Mode|Channel:' | head -2
    echo "Pinging $GW at 100 packets/sec. Log: $LOGFILE"
    caffeinate -i ping -i 0.01 "$GW" > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Started, pid $(cat $PIDFILE)"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat $PIDFILE)" 2>/dev/null || true
      rm -f "$PIDFILE"
      echo "Stopped."
    else
      echo "Not running."
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
      echo "Running, pid $(cat $PIDFILE)"
      tail -1 "$LOGFILE"
    else
      echo "Not running."
    fi
    ;;
  *)
    echo "Usage: $0 {start [gateway]|stop|status}" >&2
    exit 1
    ;;
esac
```

`start` needs `sudo` because of the fractional ping interval.
`status` does not.

## A laptop beats a phone here

If someone suggests using a phone as the generator instead, the answer is no unless there is no laptop.

Phone Wi-Fi power save injects jitter into transmission timing, and that jitter shows up as noise in the CSI.
It is not a small effect and it is hard to see until you are trying to pull a 0.2 Hz respiration signal out of the result.

If a phone is genuinely the only option: disable power saving, keep the screen awake, and keep it plugged in.

## Internet Sharing: venue only

At the house, the demo router's WAN goes straight to home internet over Cat5.
There is no Internet Sharing in that chain at all, and that is deliberate.
It removes three failure points: macOS Internet Sharing itself, the USB Ethernet adapter in the uplink role, and the 192.168.2.x subnet collision.

**Do not set up Internet Sharing at the house.**
It buys nothing and it introduces a NAT range that will collide later.

At a venue, if the Pi needs to be online, the chain is:

```
venue Wi-Fi or phone hotspot
   └─► MacBook (Internet Sharing: Wi-Fi source ─► USB Ethernet)
          └─ Cat5 ─► AX1450 WAN
```

To configure it: System Settings > General > Sharing > Internet Sharing.
Share your connection from **Wi-Fi**, to computers using **the USB ethernet adapter**.

Two constraints:

- **The router LAN subnet must not be 192.168.2.x**, because that is Internet Sharing's NAT range. The AX1450's factory 192.168.0.x is fine. Verify rather than assume.
- **A captive-portal venue network cannot be shared.** The fallback is USB tethering a phone to the MacBook and sharing that connection instead.

Note the conflict this creates: if the MacBook's Wi-Fi is being used as the Internet Sharing *source*, it is associated to the venue network, not to the AX1450, so it is not generating traffic on the monitored channel.
At a venue, either the MacBook shares internet or it generates traffic, not both.
This is acceptable because the venue demo does not run the sensing pipeline.
The venue bit is movement response only, which a judge's own hand provides the motion for, and the router's beacons plus any associated phone provide enough frames for that.

## The MacBook's other jobs

It is also the dev machine.
The agents get built here, the iOS app runs here in the simulator or gets deployed to the iPhone from here, and the `dd` image of the Pi's working microSD lives here.

Two consequences worth stating:

- **The Pi's microSD image goes somewhere that is not only this machine.** One laptop is one point of failure for the thing that saves the demo.
- **When the iPhone is running the app against the live system, it must be on the same router.** Join it to the 5GHz SSID like everything else. See [router-archer-ax1450.md](router-archer-ax1450.md).

Nothing about the dev workload should run during a take if it can be avoided.
A build kicking off mid-capture changes the Mac's own Wi-Fi traffic pattern, and while that mostly just adds frames, it is uncontrolled.
