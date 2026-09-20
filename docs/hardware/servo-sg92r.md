# TowerPro SG92R micro servo, and the camera shield

The thing that physically uncovers the camera.
Driven by `agents/agents/shutter/`, which will not move it without a verified grant from `master`.
(`shutter/` at the repo root is the contract; the code lives in the agents package with its siblings.)

Read `shutter/CLAUDE.md` for why this exists and what a grant is.
This guide is the how.

## What you are building

A small opaque flag on a servo horn, mounted so that at 0 degrees it completely covers the camera lens and at 90 degrees it is clear of it.

That is the entire mechanism. It is deliberately dumb.

**The flag must be genuinely opaque and it must genuinely cover the lens.**
A judge will look, and a shield that leaves a crescent of lens visible turns the project's central privacy claim into a prop.
Black foam board, black PLA, or a bottle cap painted matte black. Not tape over a hole, not translucent plastic.

## The two things that will bite you

### 1. Do not power the servo from the Pi's 5V pin under load

The SG92R draws roughly 100-250mA moving and **stalls at over 700mA**.
The Pi's 5V rail will sag, and a sagging Pi does not reboot visibly. It corrupts the SD card, or it drops the CSI capture, or it becomes unreachable, and none of those failures mention the servo.

This is the single most likely way this component costs you the demo, and it will happen at the worst moment because it only happens under load.

**Do this instead:**

```
   Separate 5V supply ──┬──► servo red (V+)
                        │
   Pi GND ──────────────┴──► servo brown/black (GND)      <-- common ground, required
   Pi GPIO 18 ───────────► servo orange/yellow (signal)
```

A USB power bank with a broken-out USB-A, a spare phone charger, or a 4xAA pack all work.
**The grounds must be tied together** or the servo sees no valid signal and twitches or does nothing.

If you absolutely must run it off the Pi for a bench test, add a 470uF or larger capacitor across the servo's V+ and GND, keep the Pi on its 3A supply, and do not leave it that way for the demo.

### 2. Software PWM jitters, and it shows up on camera

Servo position comes from pulse width: roughly 500us for 0 degrees, 2400us for 180, at 50 Hz.
Linux is not a real-time OS, so a software PWM loop produces pulses a few tens of microseconds off, and the horn buzzes and twitches.

On a bench that is a curiosity. In your demo footage it is a shield that looks broken.

Use one of:

- **Hardware PWM**, on GPIO 12, 13, 18 or 19
- **`pigpio`**, which does DMA-timed pulses and is good enough: `sudo apt install pigpio && sudo systemctl enable --now pigpiod`

```python
import pigpio
pi = pigpio.pi()
pi.set_servo_pulsewidth(18, 500)    # closed
pi.set_servo_pulsewidth(18, 1500)   # open, roughly 90 degrees
pi.set_servo_pulsewidth(18, 0)      # stop sending. Do this after the move
```

**Send `0` when the move is done.** A servo held at a position with a live signal hunts, hums, and draws current forever. Send the pulse, wait about 500ms, then stop.

## Wiring

| SG92R wire | Goes to |
|---|---|
| Orange or yellow (signal) | Pi GPIO 18, physical pin 12 |
| Red (V+) | Separate 5V supply, **not** the Pi 5V pin |
| Brown or black (GND) | Pi GND (physical pin 6) **and** the supply ground, tied together |

## Calibrating the two positions

Do this once, write the two pulse widths into `agents/agents/shutter/pigpio_backend.py`
(`MIN_PULSE_US` and `MAX_PULSE_US`), and never touch it again.
There is a test asserting both the closed and open angles land inside that range.

1. Mount the camera in its final position first. The shield's geometry depends on it
2. `pi.set_servo_pulsewidth(18, 1500)` and note where the horn sits
3. Fit the horn so the flag is clear of the lens at that position
4. Walk the pulse width down in steps of 100 until the flag fully covers the lens. That value is `closed`
5. Check the covered position with the camera actually streaming. A frame that is not fully black means the flag is not fully covering
6. Add about 100us of margin on the closed side so the flag presses lightly rather than sitting on the edge of coverage

**Do not calibrate against the servo's rated range.** SG92R horns vary and the mount is hand-made; calibrate against what the camera sees.

## Verifying it

```sh
# Is the daemon up
pgrep pigpiod

# Does the shutter agent refuse a grant nobody signed. Expect a *result*
# carrying refusal: "unregistered_issuer" - never an error, and never a movement.
curl -s -X POST localhost:8106/a2a -H 'content-type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"shutter.open","params":{"grant":"{}"}}' | jq
# expect a refusal, and the flag does not move

# Does the servo physically move, and does the shield clear the lens
python -m agents.shutter.selftest --backend pigpio
# expect: closed, open, closed - with a dwell at each end, ending covered
```

**The self-test bypasses the gate on purpose and proves nothing about it.** It answers one question during
bring-up - does this servo move and does this shield clear this lens - at a moment when "is the grant valid"
is noise. It is a separate entry point for exactly that reason: the running agent has no such path, and
someone who can run it already has a shell on the Pi, which is a strictly larger capability than opening a
shutter.

The gate is proved on a laptop, by `cd agents && python -m pytest tests/test_shutter.py -q`, and end to end
by T50. What this bench check adds is the physical half.

Run it at least once **with the real servo attached** before the demo, and record it.

**Then do the half that actually matters**: with the sweep finished and the shield closed, take a camera frame
and confirm its mean luminance is near zero (`docs/hardware/logitech-camera.md`). The SG92R is open-loop, so a
jammed, slipped or mis-glued shield attests `open` exactly as a working one does. The frame is the only thing
that catches it, and a shield leaving a crescent of lens visible turns the project's central privacy claim
into a prop that nobody would notice. Re-run it after the mount is touched for the last time.

## The way this fails quietly

| Symptom | Cause |
|---|---|
| Pi becomes unreachable when the shutter moves | Servo on the Pi's 5V rail. Brownout. Fix the power first, before anything else |
| Flag buzzes and twitches at rest | Signal still being sent after the move. Send pulse width 0 |
| Flag moves but the camera frame is still black | Calibration is wrong on the open side, or the flag is fouling the lens housing |
| Frame is not black when the shield is closed | **The worst one.** The privacy claim is false and nobody would notice. Check this specifically, with the camera live, every time the mount is touched |
| Servo does nothing, no movement, no noise | Grounds not tied together. Check this before suspecting the code |
| Shutter agent refuses a grant you believe is valid | Almost always a stale or already-spent nonce. Check the TTL, then the clock |

## Mounting

`docs/hardware/assembly-and-placement.md` has the room geometry.
The servo constraint is short:

- The servo mounts to the **camera**, not to the Pi. They are connected by wire and nothing else
- The camera faces the entry point the demo uses. The Pi's own placement is governed by CSI geometry, which is a different and sometimes opposing constraint. Do not let one silently break the other
- Hot glue and a scrap of board is fine. This is demo-grade hardware and `shutter/CLAUDE.md` says so out loud rather than implying tamper resistance
