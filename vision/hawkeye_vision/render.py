"""The film print. One mp4 with the overlay burned into every frame.

**This is not the record and must never be mistaken for it.** `record.py`
writes what came off the sensor, unenhanced and ungraphed, because those files
are hashed into the chain and emailed to a police department. This writes a
second, separate file with boxes and labels drawn on top, for the demo video
and for looking at a clip afterwards.

Two files, two purposes, and the evidence one is the one with nothing drawn on
it. `--record` and `--render` may be used together and produce different bytes
on purpose.

Unlike the segment writer there is no rotation and no hash. Losing the last ten
seconds of a film print costs ten seconds of a film print.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class OverlayRenderer:
    """Write already-overlaid frames into a single mp4.

    The writer is opened lazily, on the first frame, because its frame size has
    to match the frames it is given and nothing knows that until one arrives.
    """

    def __init__(self, path: str | Path, fps: int) -> None:
        self.path = Path(path)
        self.fps = fps
        self.frames = 0
        self._writer: cv2.VideoWriter | None = None

    def write(self, image: np.ndarray) -> None:
        """Append one overlaid frame. Never raises; a lost print is not an incident."""
        try:
            if self._writer is None:
                self._open(image)
            if self._writer is not None:
                self._writer.write(image)
                self.frames += 1
        except Exception:
            logger.exception("render write failed on frame %d; continuing", self.frames)

    def _open(self, image: np.ndarray) -> None:
        height, width = image.shape[:2]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter.fourcc(*"mp4v"), self.fps, (width, height)
        )
        if not writer.isOpened():
            logger.error("could not open a render writer for %s; no print", self.path)
            return
        self._writer = writer

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        logger.info("rendered %d frames to %s", self.frames, self.path)
