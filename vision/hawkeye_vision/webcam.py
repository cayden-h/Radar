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

    `index` is the AVFoundation device index, and OpenCV exposes no device name,
    vendor id or any other distinguishing property through it. The ordering does
    NOT match `system_profiler SPCameraDataType`, and it shifts when an iPhone
    attaches as a Continuity Camera. Every index on this machine opens happily
    and reports the same 1280x720, so an index that works is not evidence that
    it is the right camera.

    Identified 2026-09-19 on Cayden's MacBook by capturing one frame from each
    index and looking at it: **0 is the Brio 101**, 1 is the iPhone Continuity
    Camera, 2 is the built-in FaceTime. The Brio is the wide room view; the
    other two are close views of whatever the laptop faces.

    Re-check the same way whenever the USB layout changes, because nothing in
    software will tell you it is wrong:

        python3 -c "import cv2; from hawkeye_vision.webcam import MacCamera
        for i in (0, 1, 2):
            with MacCamera(index=i) as c:
                f = next(c.frames()); cv2.imwrite(f'/tmp/cam_{i}.png', f.image)"
    """

    source = Source.CAMERA_UVC

    def __init__(self, index: int = 0, *, width: int = 1280, height: int = 720) -> None:
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
