"""Who is in frame, and the bookkeeping that turns detections into a count.

The seam is the same one `shutter` uses for its GPIO pin. `Tracker` is a
Protocol, `StubTracker` is a first-class implementation that every test and the
whole mock demo path run against, and `YoloBotSortTracker` is the same interface
over real weights. Swapping them is a constructor argument.

Track identities are stable **within a session only**. That is not a limitation
we are apologising for, it is the same rule `Assertion.presence_id` already
states: we do not do re-identification across sessions and we have no database
to do it against. A track id says "the same person as a moment ago", never "this
particular person".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame


@dataclass(frozen=True, slots=True)
class BBox:
    """A box around a person, normalised to 0..1 of the frame.

    Normalised rather than in pixels because the consumer is a client drawing an
    overlay at whatever size its view happens to be, and because a claim that
    travels between agents should not carry this camera's resolution as a hidden
    assumption.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        for name in ("x1", "y1", "x2", "y2"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"BBox.{name} must be within 0..1, got {value}")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("BBox must have x2 > x1 and y2 > y1")


@dataclass(frozen=True, slots=True)
class Detection:
    """One person the tracker saw in one frame, with the identity it assigned."""

    track_id: int
    bbox: BBox
    confidence: float = 1.0


@dataclass(slots=True)
class Track:
    """One person, followed across frames."""

    track_id: int
    bbox: BBox
    confidence: float
    first_seen_frame: int
    last_seen_frame: int
    frames_held: int = field(default=1)


class Tracker(Protocol):
    """Something that finds people in a frame and keeps their identities."""

    def update(self, frame: Frame) -> Sequence[Detection]:
        """Detections for this frame, each carrying a stable identity."""


class StubTracker:
    """A tracker that replays a script. What the tests and the mock run on.

    A first-class implementation rather than a branch inside the real one, for
    the reason `StubShutter` is: the demo must never depend on hardware, or in
    this case on model weights and a working MPS backend, being alive.
    """

    def __init__(self, script: Sequence[Sequence[tuple[int, BBox]]]) -> None:
        self._script = list(script)
        self._calls = 0

    def update(self, frame: Frame) -> Sequence[Detection]:
        if self._calls >= len(self._script):
            return []
        entries = self._script[self._calls]
        self._calls += 1
        return [Detection(track_id=tid, bbox=box) for tid, box in entries]


class TrackBook:
    """Holds the tracks currently considered present.

    The detector loses people constantly: they turn side-on, they walk behind a
    sofa, the frame is noisy. BoT-SORT keeps a lost track alive in its buffer,
    and this mirrors that with an expiry, so a person who steps behind a doorway
    for half a second does not make `people_visible` drop to zero and back.

    A flickering count is not cosmetic here. It is the number a caller agent
    reads to a 911 operator.
    """

    def __init__(self, config: VisionConfig) -> None:
        self._config = config
        self._tracks: dict[int, Track] = {}
        self._last_frame = -1

    def ingest(self, detections: Sequence[Detection], *, frame_index: int) -> None:
        """Fold one frame's detections into the book."""
        self._last_frame = frame_index

        for detection in detections:
            existing = self._tracks.get(detection.track_id)
            if existing is None:
                self._tracks[detection.track_id] = Track(
                    track_id=detection.track_id,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    first_seen_frame=frame_index,
                    last_seen_frame=frame_index,
                )
            else:
                existing.bbox = detection.bbox
                existing.confidence = detection.confidence
                existing.last_seen_frame = frame_index
                existing.frames_held += 1

        self._expire(frame_index)

    def _expire(self, frame_index: int) -> None:
        cutoff = self._config.track_expiry_frames
        self._tracks = {
            tid: track
            for tid, track in self._tracks.items()
            if frame_index - track.last_seen_frame <= cutoff
        }

    @property
    def active(self) -> list[Track]:
        """Tracks considered present, in the order they were first seen."""
        return sorted(self._tracks.values(), key=lambda t: t.first_seen_frame)

    @property
    def people_visible(self) -> int:
        """How many distinct people this camera can see in this room.

        A count of what is in frame, never a count of the building. When it is
        zero that is a fact about this room, and `master` must not turn it into
        an absence claim about the house.
        """
        return len(self._tracks)
