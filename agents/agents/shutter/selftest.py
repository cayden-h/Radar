"""Move the shield, once, with nothing verifying anything. The bring-up script.

    python -m agents.shutter.selftest                 # stub, runs anywhere
    python -m agents.shutter.selftest --backend pigpio  # the real servo

**This deliberately bypasses the gate**, and that is the only reason it is a
separate entry point rather than a flag on the agent. It exists to answer one
question during hardware bring-up - does the servo physically move, and does the
shield clear the lens - at a moment when the answer to "is the grant valid" is
noise. `Shutter` itself has no such path: there, the GPIO write is reachable
only through a `VerifiedGrant`.

It is not reachable from the running agent, it is not importable from it, and it
takes no input from the network. Someone who can run this already has a shell on
the Pi, which is a strictly larger capability than opening a shutter.

T21 on the board is this command moving a real servo, followed by the check that
actually matters: a camera frame taken with the shield closed has a mean
luminance near zero. That second half is in `docs/hardware/logitech-camera.md`
and it is the one protecting the project's central privacy claim.
"""

from __future__ import annotations

import argparse
import sys
import time

from agents.shutter.backend import CLOSED_ANGLE, OPEN_ANGLE, ShutterBackend, StubShutter

#: Seconds to hold at each end. Long enough to look at the shield and long
#: enough for an SG92R to actually arrive, which is roughly 0.1s per 60 degrees
#: unloaded and longer with a flag on the horn.
DWELL_S = 1.0


def sweep(backend: ShutterBackend, *, dwell_s: float = 0.0) -> list[int]:
    """Closed, open, closed. Returns the angles commanded, in order.

    **It ends closed**, always. A bring-up script that finishes with the shield
    out of the way leaves a camera watching a room, and on a bench with no
    shield glued on yet that is easy not to notice.
    """
    commanded: list[int] = []
    for angle in (CLOSED_ANGLE, OPEN_ANGLE, CLOSED_ANGLE):
        backend.set_angle(angle)
        commanded.append(angle)
        if dwell_s:
            time.sleep(dwell_s)
    return commanded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents.shutter.selftest", description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("stub", "pigpio"),
        default="stub",
        help="`stub` runs anywhere and proves the sequence. `pigpio` moves a servo.",
    )
    parser.add_argument("--dwell", type=float, default=DWELL_S, help="Seconds to hold at each end.")
    args = parser.parse_args(argv)

    if args.backend == "stub":
        backend: ShutterBackend = StubShutter()
        print("stub backend: nothing will move. --backend pigpio drives the pin.")
    else:
        from agents.shutter.pigpio_backend import PigpioShutter

        backend = PigpioShutter()

    for angle in sweep(backend, dwell_s=args.dwell):
        print(f"commanded {angle:>3} degrees  ({'shield clear' if angle else 'lens covered'})")

    print(
        "\nThe servo moving is half of T21. The other half is a camera frame taken now, "
        "with the shield closed, having a mean luminance near zero - see "
        "docs/hardware/logitech-camera.md. Re-run that check after the mount is "
        "touched for the last time."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
