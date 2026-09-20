"""The real pin. One SG92R on the Pi's GPIO, driven through `pigpio`.

Same interface as `StubShutter` and no more logic than it: the gate is proved
against the stub, and this file exists only to put the movement somewhere
physical. Full wiring guide: `docs/hardware/servo-sg92r.md`.

Two things bite, and both fail quietly rather than loudly:

- **Do not power the servo from the Pi's 5V rail under load.** The SG92R stalls
  at over 700mA and browns the Pi out mid-demo, which presents as the whole
  capture path dying for no visible reason. Separate supply, common ground.
- **Software PWM jitters.** The shield twitching between frames looks like a
  fault and will show up in the footage. `pigpio` gives hardware-timed pulses
  on any pin, which is why it is here rather than `RPi.GPIO`.

`pigpio` is imported inside the constructor, not at module scope, so that this
module can be imported - and the class inspected - on a laptop with no daemon
running. That matters: the honesty test asserts against `source` without ever
touching a servo.
"""

from __future__ import annotations

from hawkeye_backend.models.common import Source

from agents.shutter.backend import CLOSED_ANGLE

#: Hardware PWM capable. GPIO 12 or 18; 18 is the one the hardware guide wires.
DEFAULT_PIN = 18

#: Microseconds. The SG92R's datasheet range, and the range the guide measured
#: this particular servo against. Driving outside it buzzes and draws current
#: without moving, which is the stall condition that browns out the Pi.
MIN_PULSE_US = 500
MAX_PULSE_US = 2400


def pulse_width_us(angle: int) -> int:
    """Degrees to microseconds, linear across the SG92R's usable travel.

    Separated from the driver because it is the only arithmetic here, and the
    only part that can be wrong in a way a test on a laptop could catch.
    """
    if not 0 <= angle <= 180:
        raise ValueError(f"angle {angle} is outside the SG92R's 0-180 degree travel")
    span = MAX_PULSE_US - MIN_PULSE_US
    return round(MIN_PULSE_US + span * angle / 180)


class PigpioShutter:
    """The shield, on a real servo, on a real pin."""

    #: What a position claim from this backend is sourced as. DERIVED, because
    #: the servo is open-loop: this is the angle commanded, never the angle
    #: reached. See `Source.SERVO_GPIO`.
    source = Source.SERVO_GPIO

    def __init__(self, *, pin: int = DEFAULT_PIN, angle: int = CLOSED_ANGLE) -> None:
        import pigpio  # noqa: PLC0415 - absent on any machine without the daemon

        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError(
                "pigpiod is not running. `sudo pigpiod`. Failing here rather than "
                "falling back to the stub is deliberate: a shutter that silently "
                "became a number would report open with the lens covered."
            )
        self._pin = pin
        self._angle = angle
        # Rest closed. The shield covers the lens until something proves it
        # should not, and that includes across a restart.
        self.set_angle(angle)

    @property
    def angle(self) -> int:
        return self._angle

    def set_angle(self, angle: int) -> None:
        self._pi.set_servo_pulsewidth(self._pin, pulse_width_us(angle))
        self._angle = angle

    def close(self) -> None:
        """Release the pin. A servo left under PWM hums and draws current all night."""
        self._pi.set_servo_pulsewidth(self._pin, 0)
        self._pi.stop()
