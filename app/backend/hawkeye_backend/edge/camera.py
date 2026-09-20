"""The newest frame off the edge link, and everyone who wants a copy of it.

One producer (whichever edge link is connected), three kinds of consumer:
full-rate MJPEG for the phone and the browser, a 1 Hz thumbnail on the event
stream for the watch, and a single still on demand.

A slow consumer is dropped rather than allowed to back up the camera, which is
the same rule `EventBus` already applies to slow websocket subscribers and for
the same reason: during an incident a stale frame is worthless, and blocking the
camera on a phone that went to sleep is unacceptable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from hawkeye_backend.models.camera import TrackBox
from hawkeye_backend.models.common import Source, utc_now
from hawkeye_backend.models.hub import CameraStatus

logger = logging.getLogger(__name__)

#: Frames older than this are not presentable as current. Generous relative to
#: any real capture rate, so this fires on a genuinely stalled camera rather
#: than on one slow frame.
DEFAULT_STALE_AFTER_S = 3.0

#: How long the newest set of boxes may be drawn for.
#:
#: Much tighter than frame staleness, and for a different reason. A stale frame
#: is still a true statement about the last thing the camera saw. A stale *box*
#: is not: it is a claim that somebody is standing in a particular place right
#: now, drawn over a picture that has moved on. `agents/vision` publishes on
#: every pass of the detector, so anything past this means the detector stopped,
#: and the honest response is to take the boxes off rather than leave them
#: hovering over a room nobody is measuring.
TRACK_STALE_AFTER_S = 2.0

#: Window the reported frame rate is measured over.
FPS_WINDOW_S = 10.0

#: Default per-subscriber buffer for MJPEG. Small on purpose: a consumer that
#: has fallen three frames behind wants the newest frame, not the backlog.
DEFAULT_SUBSCRIBER_BUFFER = 4


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """One JPEG, when the camera took it, and when it got here.

    **Two timestamps, and the difference is load-bearing.** `captured_at` is
    stamped on the Pi and is what a claim quotes. `arrived_at` is this machine's
    own monotonic clock and is the only thing staleness is measured against.

    A Pi 4B has no battery-backed real-time clock. Before NTP settles it is
    routinely minutes out, and judging freshness on its timestamp would mark
    every frame stale while frames poured in at full rate - which would read, on
    every surface, as a camera that had stopped. That failure is silent, total,
    and looks exactly like a bug in this code.
    """

    jpeg: bytes
    index: int
    captured_at: datetime
    arrived_at: float


class FrameSubscription:
    """One MJPEG consumer's queue."""

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[CapturedFrame] = asyncio.Queue(maxsize=maxsize)
        self.dropped: int = 0


class LiveCamera:
    """Holds the newest frame and tells the truth about how old it is."""

    def __init__(
        self,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        track_stale_after_s: float = TRACK_STALE_AFTER_S,
    ) -> None:
        self._stale_after_s = stale_after_s
        self._track_stale_after_s = track_stale_after_s
        self._tracks: tuple[TrackBox, ...] = ()
        self._tracks_at: float | None = None
        self._latest: CapturedFrame | None = None
        self._subscribers: set[FrameSubscription] = set()
        self._linked = False
        self._edge_id: str | None = None
        self._source: Source | None = None
        self._frames_received = 0
        self._frames_dropped = 0
        self._next_index = 0
        self._detail = "No edge camera has connected yet."
        #: Arrival times inside the fps window.
        self._arrivals: deque[datetime] = deque()

    # ------------------------------------------------------------- link state

    def link_opened(self, *, edge_id: str, source: Source) -> None:
        self._linked = True
        self._edge_id = edge_id
        self._source = source
        self._next_index = 0
        self._detail = f"Edge camera {edge_id} connected, reporting source {source.value}."
        logger.info("%s", self._detail)

    def link_closed(self, reason: str) -> None:
        """The edge went away. The last frame is kept; `live` is what goes false.

        Keeping the frame is deliberate. It is still a true statement about the
        last thing the camera saw, and the status is what stops it being
        presented as the current one.
        """
        self._linked = False
        self._detail = f"Edge camera disconnected: {reason}"
        logger.warning("%s", self._detail)

    # ----------------------------------------------------------------- frames

    def accept(self, jpeg: bytes, *, index: int, captured_at: datetime) -> None:
        """Take one frame from the link and hand it to every consumer."""
        if index > self._next_index:
            self._frames_dropped += index - self._next_index
        self._next_index = index + 1
        self._frames_received += 1

        frame = CapturedFrame(
            jpeg=jpeg, index=index, captured_at=captured_at, arrived_at=time.monotonic()
        )
        self._latest = frame

        now = utc_now()
        self._arrivals.append(now)
        while self._arrivals and (now - self._arrivals[0]).total_seconds() > FPS_WINDOW_S:
            self._arrivals.popleft()

        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(frame)
            except asyncio.QueueFull:
                sub.dropped += 1

    # ----------------------------------------------------------- the overlay

    def set_tracks(self, tracks: Sequence[TrackBox]) -> None:
        """Take the newest boxes from `agents/vision`.

        An empty sequence is accepted and meaningful: it is how the detector
        says it looked and found nobody, and it is what clears the last person's
        box off every screen.
        """
        self._tracks = tuple(tracks)
        self._tracks_at = time.monotonic()

    @property
    def tracks(self) -> tuple[TrackBox, ...]:
        """The boxes, or nothing at all if they are too old to draw.

        See `TRACK_STALE_AFTER_S`. This returning empty does not mean the room
        is empty - it means nobody has measured it recently enough to say.
        """
        if self._tracks_at is None:
            return ()
        if time.monotonic() - self._tracks_at > self._track_stale_after_s:
            return ()
        return self._tracks

    @property
    def latest(self) -> CapturedFrame | None:
        """The newest frame, or None if none has ever arrived.

        Callers must consult `status().live` before presenting this as current.
        """
        return self._latest

    # ------------------------------------------------------------ subscribers

    async def subscribe(self, buffer: int = DEFAULT_SUBSCRIBER_BUFFER) -> FrameSubscription:
        sub = FrameSubscription(buffer)
        self._subscribers.add(sub)
        logger.info("camera subscriber joined (%d total)", len(self._subscribers))
        return sub

    async def unsubscribe(self, sub: FrameSubscription) -> None:
        self._subscribers.discard(sub)
        logger.info("camera subscriber left (%d total)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ----------------------------------------------------------------- status

    def status(self) -> CameraStatus:
        # Measured against arrival on this machine, never against the Pi's
        # timestamp. See `CapturedFrame`: an unsynchronised Pi clock would
        # otherwise mark a perfectly healthy feed permanently stale.
        age: float | None = None
        if self._latest is not None:
            age = max(0.0, time.monotonic() - self._latest.arrived_at)

        live = self._linked and age is not None and age <= self._stale_after_s

        detail = self._detail
        if self._linked and age is not None and age > self._stale_after_s:
            detail = (
                f"Edge camera {self._edge_id} is connected but nothing has arrived "
                f"for {age:.1f}s, which is stale. Not presentable as current."
            )
        elif live:
            detail = (
                f"Edge camera {self._edge_id} live at {self._fps():.1f} fps, "
                f"newest frame arrived {age:.1f}s ago."
            )

        return CameraStatus(
            linked=self._linked,
            live=live,
            edge_id=self._edge_id,
            source=self._source,
            last_frame_age_s=round(age, 3) if age is not None else None,
            fps=round(self._fps(), 2),
            frames_received=self._frames_received,
            frames_dropped=self._frames_dropped,
            detail=detail,
        )

    def _fps(self) -> float:
        if len(self._arrivals) < 2:
            return 0.0
        span = (self._arrivals[-1] - self._arrivals[0]).total_seconds()
        if span <= 0:
            return 0.0
        return (len(self._arrivals) - 1) / span
