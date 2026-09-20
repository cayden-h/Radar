"""The film print. Separate file, separate bytes, never confused with evidence."""

import numpy as np
import pytest

from hawkeye_vision.render import OverlayRenderer


def _frame(value: int = 200, size=(120, 160)) -> np.ndarray:
    return np.full((size[0], size[1], 3), value, dtype=np.uint8)


def test_frames_land_in_a_playable_mp4(tmp_path):
    import cv2

    renderer = OverlayRenderer(tmp_path / "print.mp4", fps=15)
    for _ in range(20):
        renderer.write(_frame())
    renderer.close()

    capture = cv2.VideoCapture(str(tmp_path / "print.mp4"))
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 20
    capture.release()


def test_a_missing_parent_directory_is_created(tmp_path):
    renderer = OverlayRenderer(tmp_path / "deep" / "nested" / "print.mp4", fps=15)
    renderer.write(_frame())
    renderer.close()

    assert (tmp_path / "deep" / "nested" / "print.mp4").exists()


def test_an_unwritable_path_loses_the_print_and_nothing_else(tmp_path):
    """A film print is not evidence. Failing to write one must not raise."""
    renderer = OverlayRenderer(tmp_path / "nope" / "print.mp4", fps=15)
    renderer.path = tmp_path  # a directory: the writer cannot open it

    renderer.write(_frame())
    renderer.close()

    assert renderer.frames == 0


def test_closing_twice_is_safe(tmp_path):
    renderer = OverlayRenderer(tmp_path / "print.mp4", fps=15)
    renderer.write(_frame())
    renderer.close()
    renderer.close()


def test_the_record_and_the_print_are_different_files(tmp_path, bright_mp4):
    """--record and --render together: clean segments, overlaid print."""
    from hawkeye_vision.record import SegmentWriter

    writer = SegmentWriter(tmp_path / "record", fps=15, segment_frames=15)
    renderer = OverlayRenderer(tmp_path / "print.mp4", fps=15)

    assert renderer.path not in {seg.path for seg in writer.sealed}
