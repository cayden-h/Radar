"""The real `OccupancySource`: frames in, a personhood verdict out.

The adapter T15b left open. `VisionAgent` has taken an `OccupancySource`
Protocol since it was written, and until now the only thing implementing it was
the test fake - so everything shipped ran on `StubTracker` and the agent's
verdict was scripted. This is the implementation that pulls a real frame,
detects on it, and says what the camera can actually see.

## Why it holds a thread

`VisionAgent.tick` is synchronous, runs once a second, and must not raise for
ordinary missing data. YOLO11m on a frame costs about 100ms on MPS and several
times that on CPU, and a capture that blocked the tick would put inference
latency in front of every claim the agent makes.

So capture and inference run in their own thread at their own rate, and `tick`
reads whatever the newest verdict is. That is also what the tracker wants:
BoT-SORT needs a continuous sequence of frames to keep identities across them,
and a tracker driven one frame per agent tick is a tracker with a two-second
memory of a two-second track buffer.

## The three states are three states

`Occupancy` has three values and this class is careful with all of them,
because the honest handling of the third is what the whole design rests on.

- **PERSON_PRESENT** - the detector found a person in the newest frame.
- **NO_PERSON** - the detector looked at a current frame and found nobody.
- **TRACKER_UNAVAILABLE** - no weights, no frames, or the newest frame is too
  old to describe the room now.

That last case is the one that matters. A blind camera reporting `NO_PERSON`
closes a shutter and looks like it is working, and `master` retires a verified
grant on the strength of it. Staleness is therefore treated as blindness rather
than as emptiness: past `STALE_AFTER_S` with nothing new, this reports that it
could not look, and the lens stays where it is.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

from hawkeye_backend.models.common import Source

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, FrameSource
from hawkeye_vision.occupancy import Occupancy, verdict
from hawkeye_vision.track import Detection, Tracker

logger = logging.getLogger(__name__)

#: How long the newest verdict stays usable. Past this the source reports that
#: it could not look rather than what it last saw. Deliberately a small multiple
#: of a capture interval: a verdict is a statement about the room *now*.
STALE_AFTER_S = 3.0

#: How long to wait before reconnecting a frame source that ended or failed.
#: The edge box dropping off is ordinary - a Pi reboots, WiFi moves - and a
#: capture loop that gave up on the first failure would need a human to restart
#: the agent every time.
RECONNECT_AFTER_S = 2.0

#: A sink for the boxes the tracker is holding, called once per frame with the
#: detections from that frame. Deliberately a bare callable rather than an
#: interface: the only implementation posts to the hub, and a Protocol here
#: would be ceremony around one function.
TrackSink = Callable[[Sequence[Detection]], None]

#: A sink for the frames themselves, called once per frame with the frame
#: exactly as it came off the source. The one implementation is
#: `hawkeye_vision.live_record.IncidentRecorder`.
#:
#: **It is handed the raw frame, before anything looks at it.** The recording is
#: evidence: nothing enhanced, brightened or annotated may reach it, and taking
#: the frame here rather than after detection is what makes that structural
#: rather than a rule somebody has to remember.
FrameSink = Callable[["Frame"], None]


class LiveOccupancySource:
    """Occupancy from a real `FrameSource` and a real `Tracker`.

    Both are injected rather than constructed here, which is what lets the same
    class run against the hub's relay with YOLO on the Mac, against a webcam
    directly, and against recorded footage in a test - with nothing below the
    `FrameSource` seam knowing which.
    """

    def __init__(
        self,
        frames: FrameSource,
        tracker: Tracker,
        *,
        config: VisionConfig | None = None,
        stale_after_s: float = STALE_AFTER_S,
        on_tracks: "TrackSink | None" = None,
        on_frame: "FrameSink | None" = None,
    ) -> None:
        self._frames = frames
        self._tracker = tracker
        #: Where to send the boxes so a human can see them. Optional, and it
        #: stays optional: nothing about the verdict depends on anyone being
        #: interested in the geometry, and the webcam path and the tests have no
        #: hub to publish to.
        self._on_tracks = on_tracks
        #: Where each frame goes to be recorded. Optional, and it stays
        #: optional: the verdict is this class's job and the mp4 is somebody
        #: else's, so a webcam run and every test work with no recorder at all.
        self._on_frame = on_frame
        self._config = config or VisionConfig()
        self._stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._verdict = Occupancy.TRACKER_UNAVAILABLE
        self._verdict_at = 0.0
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        #: What the frame source says is producing frames. Read by the agent
        #: each tick rather than fixed at construction, because the edge can
        #: reconnect carrying a different source and a claim must carry the
        #: label of the thing that actually produced it.
        self.source: Source = getattr(frames, "source", Source.CAMERA_SIM)
        #: Why the last pass produced no verdict. Surfaced in logs; the agent's
        #: own `Unknown` carries the reader-facing sentence.
        self.detail: str | None = "no frame has arrived yet"

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Begin capturing. Idempotent, so a restart is not a second thread."""
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, name="vision-capture", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    # ------------------------------------------------- the OccupancySource API

    def occupancy(self) -> Occupancy:
        """The verdict for the most recent frame, or blindness if it is stale.

        Stale is reported as `TRACKER_UNAVAILABLE` and never as `NO_PERSON`.
        Zero detections from a camera that stopped sending is not evidence that
        the room is empty, and a shutter closed on that basis is a lens covered
        for a reason nobody checked.
        """
        with self._lock:
            age = time.monotonic() - self._verdict_at
            if self._verdict_at == 0.0 or age > self._stale_after_s:
                return Occupancy.TRACKER_UNAVAILABLE
            return self._verdict

    # ------------------------------------------------------------- the thread

    def _capture_loop(self) -> None:
        """Capture, detect, record a verdict. Forever, reconnecting as needed.

        Every failure path here ends in a reconnect rather than an exit. This
        thread is the only thing standing between the agent and a permanent
        `tracker_unavailable`, and an agent that went blind at 3am because a
        websocket blinked is an agent that was not running continuously.
        """
        while not self._stopping.is_set():
            try:
                self._consume()
            except Exception as exc:  # noqa: BLE001 - see the docstring
                self.detail = f"frame source failed: {exc}"
                logger.warning("vision capture: %s; reconnecting", exc)
            else:
                self.detail = "the frame source ended"
                logger.info("vision capture: frame source ended; reconnecting")

            # A verdict does not survive the source that produced it. Without
            # this, a camera that vanished would keep answering `person_present`
            # until the staleness window expired, which is the frozen-frame
            # failure one layer down from the screen.
            self._forget()
            self._stopping.wait(RECONNECT_AFTER_S)

    def _consume(self) -> None:
        """Drain the frame source, updating the verdict per frame."""
        refresh = getattr(self._frames, "refresh_source", None)
        if refresh is not None:
            # Ask the hub what is actually producing frames, and believe it. A
            # video file must not read as a camera, and this is where that label
            # comes from rather than from an assumption in this process.
            try:
                refresh()
                self.source = self._frames.source
            except Exception as exc:  # noqa: BLE001
                logger.debug("vision capture: could not refresh source (%s)", exc)

        for frame in self._frames.frames():
            if self._stopping.is_set():
                return
            self._record_frame(frame)
            detections = self._tracker.update(frame)
            available = getattr(self._tracker, "available", True)
            self._record(verdict(detections, tracker_available=available))
            if not available:
                self.detail = getattr(self._tracker, "reason", None) or "tracker unavailable"
            else:
                # Publish on every pass, including the passes that found nobody.
                # An empty list is what takes the last person's box off the
                # screen, so skipping it would leave a rectangle hanging over an
                # empty room until it aged out.
                self._publish(detections)

    def _record_frame(self, frame: Frame) -> None:
        """Hand the frame to the recorder, and never let it break capture.

        Same rule as `_publish`, for a different artifact and a sharper reason.
        Losing the overlay costs a rectangle on a screen; losing this thread
        costs the personhood verdict that closes a shutter. A disk that filled
        up must not be able to blind the camera.
        """
        if self._on_frame is None:
            return
        try:
            self._on_frame(frame)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            logger.error("could not record a frame (%s)", exc)

    def _publish(self, detections) -> None:  # noqa: ANN001 - Sequence[Detection]
        """Hand the boxes to the sink, and never let it break capture.

        The sink is a network call to the hub. The hub restarting, or being
        slow, must not stop this thread measuring the room - the verdict is the
        job and the overlay is a courtesy.
        """
        if self._on_tracks is None:
            return
        try:
            self._on_tracks(detections)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            logger.debug("could not publish tracks (%s)", exc)

    def _record(self, value: Occupancy) -> None:
        with self._lock:
            self._verdict = value
            self._verdict_at = time.monotonic()
        if value is not Occupancy.TRACKER_UNAVAILABLE:
            self.detail = None

    def _forget(self) -> None:
        with self._lock:
            self._verdict = Occupancy.TRACKER_UNAVAILABLE
            self._verdict_at = 0.0
