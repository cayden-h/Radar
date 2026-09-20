"""master's shutter decisions.

The refractory lock is the test that protects the physical demo: an oscillating
SG92R stalls over 700mA and browns out the Pi.
"""

from __future__ import annotations

from agents.master.episode import CLEAR_TICKS_TO_RELEASE, ShutterEpisode

ROOM = "living_room"


def test_motion_on_a_closed_shutter_opens_it() -> None:
    episode = ShutterEpisode()
    assert episode.on_motion(ROOM) is True


def test_motion_while_already_open_does_not_re_open() -> None:
    """Re-issuing an open grant for an already-open lens is a wasted servo
    command and a wasted nonce."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    assert episode.on_motion(ROOM) is False


def test_benign_close_locks_out_immediate_re_open() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion(ROOM) is False


def test_lock_releases_after_enough_clear_ticks() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is True


def test_motion_during_the_lock_restarts_the_clear_count() -> None:
    """A fan that keeps tripping motion must never accumulate clear ticks
    between gusts and slip past the lock."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False  # still locked, and this resets it
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False


def test_the_lock_is_per_room() -> None:
    """A locked living room must not suppress an open for the kitchen."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion("kitchen") is True


def test_motion_flood_is_bounded() -> None:
    """The brownout guard. 500 ticks of unbroken motion must produce a small,
    bounded number of open commands, not one per tick."""
    episode = ShutterEpisode()
    opens = 0
    for _ in range(500):
        if episode.on_motion(ROOM):
            opens += 1
            episode.opened(ROOM)
            episode.closed(ROOM)
    assert opens == 1, f"servo commanded {opens} times under continuous motion"


def test_suppression_reason_is_reportable() -> None:
    """A suppressed open is evidence, not a gap. master puts this string in the
    discard feed so the replay console shows the suppression."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    episode.on_clear(ROOM)
    episode.on_motion(ROOM)
    reason = episode.suppression_reason(ROOM)
    assert reason is not None
    assert str(CLEAR_TICKS_TO_RELEASE) in reason
