"""The real OccupancySource. The half of it that matters is staleness.

`LiveOccupancySource` exists so `agents/vision` stops answering from a script,
and the interesting assertions here are not "it finds a person" - the tracker's
own suite covers that - but the three ways it must refuse to answer:

- before any frame has arrived
- once the newest verdict is older than the room it describes
- when the frame source dies mid-run

All three have to come back as `TRACKER_UNAVAILABLE` rather than `NO_PERSON`,
because `master` closes a verified shutter grant on `no_person`. A blind camera
that reports an empty room is the one failure that turns this system's central
privacy mechanism into a thing that fires at random.
"""

from __future__ import annotations

import time

import numpy as np
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.live_occupancy import LiveOccupancySource
from hawkeye_vision.occupancy import Occupancy
from hawkeye_vision.track import BBox, Detection


def _frame(index: int) -> Frame:
    return Frame(
        index=index,
        captured_at=utc_now(),
        image=np.zeros((48, 64, 3), dtype=np.uint8),
    )


class _Frames:
    """A frame source that yields a fixed number, then ends.

    Paced, deliberately. An unpaced fake hands over fifty frames in microseconds
    and the source is back to `TRACKER_UNAVAILABLE` before a poller can observe
    anything, which reads as a bug in the source rather than as a fake with no
    clock. Real capture arrives at a camera's rate and these tests are about
    what a reader sees while it does.
    """

    source = Source.CAMERA_SIM

    def __init__(
        self, count: int = 3, *, raises: Exception | None = None, interval_s: float = 0.005
    ) -> None:
        self._count = count
        self._raises = raises
        self._interval_s = interval_s
        self.passes = 0

    def frames(self):
        self.passes += 1
        for i in range(self._count):
            yield _frame(i)
            time.sleep(self._interval_s)
        if self._raises is not None:
            raise self._raises

    def close(self) -> None:
        pass


class _Tracker:
    """A tracker that finds a person, or does not, or cannot look."""

    def __init__(self, *, finds: bool = True, available: bool = True) -> None:
        self.available = available
        self.reason = None if available else "no weights loaded"
        self._finds = finds
        self.frames_seen = 0

    def update(self, frame: Frame):
        self.frames_seen += 1
        if not self._finds:
            return []
        return [Detection(track_id=1, bbox=BBox(0.1, 0.1, 0.4, 0.8), confidence=0.9)]


def _settle(source: LiveOccupancySource, want: Occupancy, timeout_s: float = 15.0) -> Occupancy:
    """Poll until the verdict is what we are waiting for, or time out.

    The capture thread runs at its own rate, so a bare sleep would either be
    flaky or slow. Polling for the expected value keeps the test fast when it
    passes and still fails honestly when it does not.

    The timeout is generous because it is a deadline, not a measurement: these
    tests pass in milliseconds on an idle machine, and the only thing a tight
    bound buys is a failure whenever the full suite happens to be saturating
    the CPU alongside them. A flaky test is worse than a slow one - it teaches
    the team to re-run rather than to read.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        got = source.occupancy()
        if got is want:
            return got
        time.sleep(0.01)
    return source.occupancy()


def test_nothing_has_arrived_yet_is_blindness_not_emptiness():
    """Before the first frame there is no verdict, and no verdict is not 'empty'."""
    source = LiveOccupancySource(_Frames(count=0), _Tracker())
    assert source.occupancy() is Occupancy.TRACKER_UNAVAILABLE


def test_a_person_in_frame_reaches_the_verdict():
    source = LiveOccupancySource(_Frames(count=100_000), _Tracker(finds=True))
    source.start()
    try:
        assert _settle(source, Occupancy.PERSON_PRESENT) is Occupancy.PERSON_PRESENT
    finally:
        source.stop()


def test_an_empty_room_is_reported_empty_while_frames_are_current():
    """NO_PERSON is a real answer and must be available, or nothing ever closes."""
    source = LiveOccupancySource(_Frames(count=100_000), _Tracker(finds=False))
    source.start()
    try:
        assert _settle(source, Occupancy.NO_PERSON) is Occupancy.NO_PERSON
    finally:
        source.stop()


def test_a_stale_verdict_becomes_blindness_rather_than_an_empty_room():
    """The assertion this module exists for.

    A verdict that has aged out describes a room that no longer exists. Handing
    `no_person` to `master` on the strength of it closes a shutter the grant
    said to open, on evidence nobody has.
    """
    tracker = _Tracker(finds=False)
    source = LiveOccupancySource(_Frames(count=1), tracker, stale_after_s=0.05)
    source.start()
    try:
        _settle(source, Occupancy.NO_PERSON)
        time.sleep(0.15)
        assert source.occupancy() is Occupancy.TRACKER_UNAVAILABLE
    finally:
        source.stop()


def test_a_tracker_that_cannot_look_is_never_believed():
    """Boxes from an unavailable tracker have no provenance we can describe."""
    source = LiveOccupancySource(_Frames(count=100_000), _Tracker(finds=True, available=False))
    source.start()
    try:
        assert _settle(source, Occupancy.TRACKER_UNAVAILABLE) is Occupancy.TRACKER_UNAVAILABLE
    finally:
        source.stop()


def test_a_dead_frame_source_is_reconnected_rather_than_fatal():
    """A Pi reboots and WiFi moves. Neither may end the agent's sight for good."""
    frames = _Frames(count=2, raises=RuntimeError("edge went away"))
    source = LiveOccupancySource(frames, _Tracker(finds=True), stale_after_s=5.0)
    source.start()
    try:
        _settle(source, Occupancy.PERSON_PRESENT)
        deadline = time.monotonic() + 8.0
        while frames.passes < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert frames.passes >= 2, "the capture loop gave up after one failure"
    finally:
        source.stop()


def test_the_source_label_comes_from_the_frames_not_from_this_process():
    """A video file must not read as a camera."""
    frames = _Frames(count=1)
    frames.source = Source.REPLAY_VIDEO
    source = LiveOccupancySource(frames, _Tracker())
    assert source.source is Source.REPLAY_VIDEO
