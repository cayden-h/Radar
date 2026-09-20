"""The one GPIO pin, behind an interface, so the gate is provable without it.

Two implementations and a hard rule. `StubShutter` is what every test and the
whole mock demo path run against; `PigpioShutter` is the same interface over a
real SG92R on the Pi. Swapping them is a constructor argument, which is the
seam `docs/swapping-in-real-parts.md` asks every simulated thing to have.

**Neither one takes an angle.** They take a `VerifiedGrant`, a type only the
verifier can construct, so there is no code path from a failed verification to
a servo movement - not as a convention someone maintains, but because the call
does not typecheck without a value nothing else can make.
"""

from __future__ import annotations

from typing import Protocol

from hawkeye_backend.models.common import Source

#: Shield clear of the lens. Ninety degrees, per `docs/hardware/servo-sg92r.md`.
OPEN_ANGLE = 90

#: Shield covering the lens, and the position the servo rests at. The camera
#: cannot see here - not "is configured not to record", cannot see, because
#: there is an opaque object in front of it.
CLOSED_ANGLE = 0


class ShutterBackend(Protocol):
    """Something that can put the shield in one of two places.

    `source` is part of the interface rather than a detail of each
    implementation, because it is what stops a shield made of a number from
    presenting as a shield made of plastic. Root CLAUDE.md requires the limit to
    be carried in the data; this is where the data gets it.
    """

    source: Source

    @property
    def angle(self) -> int:
        """The angle last commanded. Commanded, not measured: see `shutter/CLAUDE.md`."""

    def set_angle(self, angle: int) -> None:
        """Drive the servo. Called only from behind a `VerifiedGrant`."""


class StubShutter:
    """A servo that exists only as a number. What the tests and the mock run on.

    It is a first-class implementation rather than a branch inside the real
    one, because the demo must never depend on hardware being alive.
    """

    #: SIMULATED, and computed into every claim this shutter produces. A demo
    #: running with no servo attached cannot look like one that has a servo.
    source = Source.SERVO_STUB

    def __init__(self, *, angle: int = CLOSED_ANGLE) -> None:
        self._angle = angle
        self.history: list[int] = []

    @property
    def angle(self) -> int:
        return self._angle

    def set_angle(self, angle: int) -> None:
        self._angle = angle
        self.history.append(angle)
