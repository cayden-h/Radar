"""An mp4 as a frame source.

Two jobs, and they are genuinely different. Every test in this package runs
against a synthetic fixture, which is `Source.CAMERA_SIM`. The venue fallback
replays real footage captured at the house, which is `Source.REPLAY_VIDEO` and
is measured-but-not-live. The caller says which, and the enum stops the two
being confused.
"""

from __future__ import annotations

from collections.abc import Iterator

import cv2
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now


class FileFixture(FrameSource):
    """Read a video file frame by frame, as fast as the consumer asks."""

    def __init__(self, path: str, *, source: Source = Source.CAMERA_SIM) -> None:
        self.source = source
        self._path = path
        self._capture = cv2.VideoCapture(path)
        if not self._capture.isOpened():
            raise FileNotFoundError(f"OpenCV could not open {path}")

    def frames(self) -> Iterator[Frame]:
        index = 0
        while True:
            ok, image = self._capture.read()
            if not ok:
                return
            yield Frame(image=image, index=index, captured_at=utc_now())
            index += 1

    def close(self) -> None:
        self._capture.release()

    def __enter__(self) -> "FileFixture":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
