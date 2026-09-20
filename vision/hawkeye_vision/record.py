"""The record. Rotating mp4 segments, each hashed as it closes.

Three consumers, one artifact: the resident watches these in the iOS app,
`replay` folds each hash into the chain, and `replay` attaches them to the
police email. That is why the hash is taken here, at the moment the file is
closed, rather than later by whoever happens to read it.

Ten-second segments rather than one long file, for two reasons that are both
about failure. A file still being written cannot be hashed, so a single growing
file could never be sealed until the incident ended. And an incident that ends
abruptly, because the power went or the process was killed, should lose ten
seconds rather than everything.

**Nothing in this module enhances, brightens or filters a frame.** These files
are evidence. The low-light work happens in `enhance.py` before detection, and
in the client before display, and neither touches what lands here.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

from hawkeye_vision.frames import Frame

logger = logging.getLogger(__name__)

#: Read the file in chunks rather than whole: a segment is a few megabytes now,
#: but the hash must not become the thing that runs the Pi out of memory.
_HASH_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class SealedSegment:
    """One closed segment file and the hash of its bytes."""

    path: str
    sha256: str
    frames: int


def sha256_of(path: str | Path) -> str:
    """SHA-256 of a file's bytes, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class SegmentWriter:
    """Write frames into rotating, hashable mp4 segments."""

    def __init__(
        self,
        directory: str | Path,
        *,
        fps: int,
        segment_frames: int,
    ) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._fps = fps
        self._segment_frames = segment_frames

        self._writer: cv2.VideoWriter | None = None
        self._current_path: Path | None = None
        self._frames_in_segment = 0
        self._segment_index = 0
        self._closed = False
        self.sealed: list[SealedSegment] = []

    def write(self, frame: Frame) -> None:
        """Append one frame, rotating first if the current segment is full."""
        if self._closed:
            raise RuntimeError("SegmentWriter is closed")

        if self._writer is None:
            self._open_segment(frame)
        elif self._frames_in_segment >= self._segment_frames:
            self._seal_segment()
            self._open_segment(frame)

        assert self._writer is not None
        self._writer.write(frame.image)
        self._frames_in_segment += 1

    def _open_segment(self, frame: Frame) -> None:
        height, width = frame.image.shape[:2]
        self._current_path = self._directory / f"seg-{self._segment_index:04d}.mp4"
        writer = cv2.VideoWriter(
            str(self._current_path),
            cv2.VideoWriter.fourcc(*"mp4v"),
            self._fps,
            (width, height),
        )
        if not writer.isOpened():
            # Loud, per vision/CLAUDE.md: a sealed record missing its video is
            # worse than a visible failure.
            raise OSError(f"could not open a video writer at {self._current_path}")
        self._writer = writer
        self._frames_in_segment = 0

    def _seal_segment(self) -> None:
        """Close the current file and hash it. The only place a hash is taken."""
        if self._writer is None or self._current_path is None:
            return
        self._writer.release()
        self.sealed.append(
            SealedSegment(
                path=str(self._current_path),
                sha256=sha256_of(self._current_path),
                frames=self._frames_in_segment,
            )
        )
        logger.info("sealed %s (%d frames)", self._current_path.name, self._frames_in_segment)
        self._writer = None
        self._current_path = None
        self._segment_index += 1

    def close(self) -> None:
        """Seal the segment in progress and stop accepting frames."""
        if self._closed:
            return
        self._seal_segment()
        self._closed = True

    def __enter__(self) -> "SegmentWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
