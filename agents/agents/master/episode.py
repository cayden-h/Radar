"""The refractory lock: what stops the shield oscillating.

Motion opens the lens and the camera's own verdict closes it again. Those two
rules alone oscillate: a resident walks through, the camera sees a person, they
leave frame, the lens closes, and the next motion tick re-opens it while they
are still in the room.

That is not a cosmetic bug. The SG92R stalls over 700mA and
`docs/hardware/servo-sg92r.md` records that this browns out the Pi, which means
an oscillating shutter is the demo dying on stage.

**This lives in `master` and not in `shutter`.** `shutter` must stay a thing
that verifies a grant and moves. Giving it an opinion about whether it should
have been asked makes it a second policy engine, which is what the pivot
rejected when it rejected folding `shutter` into `vision`. Keeping the bound
here also keeps it testable with no hardware.

It is a pure state machine: no clock, no I/O, no grants. Every transition is a
method call, which is what lets the flood case be tested over 500 ticks in
microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto

#: Consecutive motion-free ticks before a benign close stops suppressing an
#: open. The same constant and the same reasoning as `CLEAR_TICKS_TO_DROP` in
#: `agents/intruder`: a state that flickers off and back a second later is worse
#: than no state at all.
CLEAR_TICKS_TO_RELEASE = 10


class _State(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    LOCKED = auto()


@dataclass
class _Room:
    state: _State = _State.CLOSED
    clear_ticks: int = 0
    suppressed: bool = False


@dataclass
class ShutterEpisode:
    """Per-room shutter state, and the lock that bounds servo commands."""

    _rooms: dict[str, _Room] = field(default_factory=dict)

    def _room(self, room: str) -> _Room:
        return self._rooms.setdefault(room, _Room())

    def on_motion(self, room: str) -> bool:
        """Motion was reported in `room`. True if master should open the lens.

        Any motion resets the clear count, including motion that is itself
        suppressed. A fan that trips motion every few seconds must never
        accumulate clear ticks between gusts and slip past the lock.
        """
        entry = self._room(room)
        entry.clear_ticks = 0

        if entry.state is _State.CLOSED:
            entry.suppressed = False
            return True

        entry.suppressed = entry.state is _State.LOCKED
        return False

    def on_clear(self, room: str) -> None:
        """A tick with no motion in `room`."""
        entry = self._room(room)
        if entry.state is not _State.LOCKED:
            return
        entry.clear_ticks += 1
        if entry.clear_ticks >= CLEAR_TICKS_TO_RELEASE:
            entry.state = _State.CLOSED
            entry.clear_ticks = 0
            entry.suppressed = False

    def opened(self, room: str) -> None:
        """`shutter` attested open."""
        entry = self._room(room)
        entry.state = _State.OPEN
        entry.suppressed = False

    def closed(self, room: str) -> None:
        """`shutter` attested closed after a benign verdict. Starts the lock."""
        entry = self._room(room)
        entry.state = _State.LOCKED
        entry.clear_ticks = 0

    def is_open(self, room: str) -> bool:
        return self._room(room).state is _State.OPEN

    def suppression_reason(self, room: str) -> str | None:
        """Why the last open was suppressed, for the discard feed.

        A suppressed open is evidence rather than a gap, so it is reportable in
        the same place `TrustGate` reports everything else it refused.
        """
        entry = self._room(room)
        if not entry.suppressed:
            return None
        return (
            f"open suppressed in {room}: benign close is still holding, "
            f"{entry.clear_ticks} clear ticks of {CLEAR_TICKS_TO_RELEASE}"
        )
