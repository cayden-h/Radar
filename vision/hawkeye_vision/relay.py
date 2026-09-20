"""A `FrameSource` that reads the hub's camera relay.

This is what lets the tracker run on the Mac while the camera is on the Pi.
Everything below the `FrameSource` seam is unchanged: YOLO11m with BoT-SORT,
the lighting state machine, the mp4 recorder and the narrator all keep working
against the interface they already had.

It polls `/v1/camera/still` rather than consuming the MJPEG stream. The tracker
samples at its own rate and drops what it cannot keep up with anyway, so pulling
the newest frame on demand is both simpler and closer to what it wants than
being pushed a backlog it will discard.

**A stale frame is never yielded.** Drawing boxes on a frame from a minute ago,
or narrating a room from a minute ago, produces claims that are false in exactly
the way this project exists to prevent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import httpx
import numpy as np
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 0.1

#: How long to keep polling with nothing usable coming back before giving up.
#: Generous relative to any capture rate, so this fires on a camera that has
#: genuinely stopped rather than on one slow frame.
DEFAULT_GIVE_UP_AFTER_S = 10.0


class RelayUnavailable(RuntimeError):
    """The hub could not be reached.

    Raised rather than returning no frames, because a consumer that cannot tell
    "nothing is happening" from "the hub is gone" will report an empty room.
    """


class RelayFrameSource(FrameSource):
    """Frames pulled from `app/backend`'s camera relay."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        max_frames: int | None = None,
        timeout_s: float = 5.0,
        give_up_after_s: float = DEFAULT_GIVE_UP_AFTER_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._poll_interval_s = poll_interval_s
        self._max_frames = max_frames
        self._timeout_s = timeout_s
        self._give_up_after_s = give_up_after_s
        self._index = 0
        #: Until the hub says otherwise, this does not claim to be a camera.
        #: `CAMERA_SIM` is the honest default: it classes as SIMULATED, so
        #: anything rendering a provenance badge shows one until proven wrong.
        self.source: Source = Source.CAMERA_SIM
        self._client = None

    # ------------------------------------------------------------------ HTTP

    def _http(self):  # noqa: ANN202 - httpx.Client
        import httpx

        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout_s)
        return self._client

    def _get_still(self):  # noqa: ANN202 - httpx.Response
        # `raw=1` is not optional here. The hub draws this tracker's own boxes
        # onto that endpoint by default, for the humans watching it, and a
        # detector fed a frame with last pass's rectangles painted on it is
        # measuring its own output. Ask for the clean frame, always.
        return self._http().get("/v1/camera/still", params={"raw": "1"})

    def _fetch_status(self) -> dict:
        response = self._http().get("/v1/hub")
        response.raise_for_status()
        return response.json()["camera"]

    def refresh_source(self) -> None:
        """Ask the hub what is actually producing frames, and believe it.

        Not hardcoded. If the hub says the frames come from a replayed video,
        this reports a replayed video, and every claim built on it is labelled
        accordingly. That is the entire reason `FrameSource.source` is part of
        the interface rather than a detail of each implementation.
        """
        try:
            status = self._fetch_status()
        except Exception as exc:  # noqa: BLE001
            raise RelayUnavailable(f"could not read camera status: {exc}") from exc
        raw = status.get("source")
        if raw:
            self.source = Source(raw)

    # ---------------------------------------------------------------- frames

    def frames(self) -> Iterator[Frame]:
        import cv2

        polls = 0
        # When the last usable frame arrived. A consumer blocked forever on a
        # camera that stopped is the same failure as a frozen frame on a screen:
        # "nothing is happening" and "the camera is gone" must not share a
        # representation, or the caller will report an empty room.
        last_good = time.monotonic()

        while self._max_frames is None or polls < self._max_frames:
            polls += 1
            if time.monotonic() - last_good > self._give_up_after_s:
                raise RelayUnavailable(
                    f"no usable frame from {self._base_url} in "
                    f"{self._give_up_after_s:.0f}s. The camera has stopped, which is "
                    "not the same as an empty room."
                )
            try:
                response = self._get_still()
            except Exception as exc:  # noqa: BLE001
                raise RelayUnavailable(f"hub unreachable: {exc}") from exc

            if getattr(response, "status_code", 200) == 503:
                # No frame yet. Not an error: the edge may not have connected.
                self._sleep()
                continue
            response.raise_for_status()

            if response.headers.get("x-hawkeye-live", "false").lower() != "true":
                logger.debug(
                    "relay: skipping a frame %ss old",
                    response.headers.get("x-hawkeye-frame-age", "?"),
                )
                self._sleep()
                continue

            image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("relay: the hub returned bytes OpenCV could not decode")
                self._sleep()
                continue

            yield Frame(image=image, index=self._index, captured_at=utc_now())
            self._index += 1
            # Stamped *after* the consumer resumes, so its processing time is
            # not charged against the give-up window. The first YOLO11m
            # inference includes a 40MB weight download and a model load, which
            # routinely exceeds ten seconds; stamping before the yield would
            # raise RelayUnavailable about a camera that never stopped.
            last_good = time.monotonic()
            self._sleep()

    def _sleep(self) -> None:
        if self._poll_interval_s:
            time.sleep(self._poll_interval_s)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class HubTrackPublisher:
    """Posts the tracker's boxes to the hub so every surface can draw them.

    The counterpart to `RelayFrameSource`: frames come down that, boxes go up
    this, and between them the camera can sit on a Pi that cannot run a model
    while the model runs on a machine that has no lens.

    **It throttles, and the throttle is the point.** YOLO runs at whatever rate
    the relay feeds it - about 7 Hz against the Brio - and a POST per frame
    would put several hundred requests a minute onto the one service every app
    talks to, to move a payload that changes by a few pixels. `MIN_INTERVAL_S`
    keeps it to a rate a human eye cannot tell from continuous.

    The one case that is never throttled is the transition to empty. A box left
    on screen after the person has gone is the failure this whole overlay could
    plausibly introduce, so the frame that first finds nobody is always sent.
    """

    #: Fast enough to look continuous, slow enough to be a rounding error on
    #: the hub. Well inside `LiveCamera.TRACK_STALE_AFTER_S`, so a steady
    #: publisher never ages its own boxes out.
    MIN_INTERVAL_S = 0.2

    def __init__(self, base_url: str = "http://127.0.0.1:8787", *, timeout_s: float = 2.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client: httpx.Client | None = None
        self._last_sent = 0.0
        self._last_count = -1

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout_s)
        return self._client

    def __call__(self, detections) -> None:  # noqa: ANN001 - Sequence[Detection]
        now = time.monotonic()
        count = len(detections)
        emptied = count == 0 and self._last_count != 0
        if not emptied and now - self._last_sent < self.MIN_INTERVAL_S:
            return
        self._last_sent = now
        self._last_count = count

        self._http().post(
            "/v1/camera/tracks",
            json={
                "tracks": [
                    {
                        "track_id": int(d.track_id),
                        "x1": float(d.bbox.x1),
                        "y1": float(d.bbox.y1),
                        "x2": float(d.bbox.x2),
                        "y2": float(d.bbox.y2),
                        "confidence": float(getattr(d, "confidence", 1.0)),
                    }
                    for d in detections
                ]
            },
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
