"""Synthetic video fixtures, generated at test time.

No mp4s are committed. A fixture that lives in git drifts from the code that
reads it and nobody notices, and a binary in a diff is unreviewable.
"""

from __future__ import annotations

import os

import cv2
import numpy as np
import pytest


def _write_mp4(path, frames, fps: int = 15) -> str:
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened(), f"OpenCV could not open a writer for {path}"
    for frame in frames:
        writer.write(frame)
    writer.release()
    return str(path)


def _flat(value: int, count: int, size=(120, 160)) -> list[np.ndarray]:
    """`count` frames of a single grey level. BGR, so all three channels equal."""
    return [np.full((size[0], size[1], 3), value, dtype=np.uint8) for _ in range(count)]


@pytest.fixture
def bright_mp4(tmp_path) -> str:
    """A well-lit room, as far as the luminance guard is concerned."""
    return _write_mp4(tmp_path / "bright.mp4", _flat(200, 30))


@pytest.fixture
def dark_mp4(tmp_path) -> str:
    """Below any usable threshold. The shield-still-covering-the-lens case."""
    return _write_mp4(tmp_path / "dark.mp4", _flat(5, 30))


@pytest.fixture
def ramp_mp4(tmp_path) -> str:
    """Luminance falling smoothly from bright to black, then back up.

    This is the fixture the hysteresis test needs: a naive classifier changes
    state many times crossing the boundary, and a correct one does not.
    """
    down = [f for value in range(200, 0, -4) for f in _flat(value, 1)]
    up = [f for value in range(0, 200, 4) for f in _flat(value, 1)]
    return _write_mp4(tmp_path / "ramp.mp4", down + up)


@pytest.fixture
def person_mp4() -> str:
    """Real footage of people, recorded from the Brio.

    Synthetic rectangles are not people and YOLO will not detect them, so this
    one fixture cannot be generated. Record it once with:

        python3 -m hawkeye_vision.record_fixture tests/footage/person.mp4

    and keep it out of git. It is the only test that needs it, and that test is
    marked integration for exactly this reason.
    """
    path = os.path.join(os.path.dirname(__file__), "footage", "person.mp4")
    if not os.path.exists(path):
        pytest.skip(f"recorded fixture missing: {path}")
    return path
