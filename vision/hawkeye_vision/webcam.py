"""The Logitech Brio 101 on this laptop, over AVFoundation.

The Pi will get a `PiV4L2` alongside this with the `v4l2-ctl` exposure and
white balance pinning from `docs/hardware/logitech-camera.md`. Both satisfy
`FrameSource`, so nothing downstream changes.

**Open the device once.** Two processes opening the same camera is the classic
device-busy failure, and it will happen the first time someone runs the
recorder and the preview separately. One reader, fan out in software.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import cv2
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now

logger = logging.getLogger(__name__)


class CameraUnavailable(RuntimeError):
    """The camera could not be opened. Consumers report `no_camera`."""


class MacCamera(FrameSource):
    """A UVC camera on macOS.

    `index` is the AVFoundation device index, which is ordering-dependent: the
    built-in FaceTime camera is usually 0 and an external USB camera usually 1,
    but plugging in an iPhone via Continuity Camera shifts them. Check with
    `system_profiler SPCameraDataType` and pass the index explicitly.
    """

    source = Source.CAMERA_UVC

    def __init__(self, index: int = 1, *, width: int = 1280, height: int = 720) -> None:
        self._capture = cv2.VideoCapture(index)
        if not self._capture.isOpened():
            raise CameraUnavailable(f"could not open camera at index {index}")

        # MJPG, per docs/hardware/logitech-camera.md. A YUYV stream at 720p is
        # roughly 27MB/sec over USB 2.0 and the Pi drops frames or refuses to
        # open the stream at all.
        self._capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        actual_w = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (actual_w, actual_h) != (width, height):
            logger.warning(
                "camera gave %dx%d rather than the requested %dx%d",
                actual_w, actual_h, width, height,
            )

    def frames(self) -> Iterator[Frame]:
        index = 0
        while True:
            ok, image = self._capture.read()
            if not ok:
                logger.error("camera read failed; stream has ended")
                return
            yield Frame(image=image, index=index, captured_at=utc_now())
            index += 1

    def close(self) -> None:
        self._capture.release()

    def __enter__(self) -> "MacCamera":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
