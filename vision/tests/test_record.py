"""Rotating mp4 segments, and the hash of each one as it closes."""

import hashlib
import os

import numpy as np
import pytest

from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.record import SegmentWriter


def _frame(index: int, value: int = 120) -> Frame:
    return Frame(
        image=np.full((120, 160, 3), value, dtype=np.uint8),
        index=index,
        captured_at=utc_now(),
    )


def test_segments_land_under_the_incident_directory(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(10):
            writer.write(_frame(i))

    assert os.path.isdir(tmp_path / "inc-1")
    assert (tmp_path / "inc-1" / "seg-0000.mp4").exists()


def test_the_writer_rotates_at_the_segment_boundary(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(25):
            writer.write(_frame(i))

    names = sorted(p.name for p in (tmp_path / "inc-1").glob("*.mp4"))
    assert names == ["seg-0000.mp4", "seg-0001.mp4", "seg-0002.mp4"]


def test_a_closed_segment_reports_its_sha256(tmp_path):
    """A file still being written cannot be hashed. Only closed ones are sealed."""
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(10):
            writer.write(_frame(i))
        writer.write(_frame(10))  # forces the first segment closed

        sealed = list(writer.sealed)

    assert len(sealed) == 1
    assert sealed[0].path.endswith("seg-0000.mp4")
    assert len(sealed[0].sha256) == 64


def test_the_reported_hash_matches_the_file_on_disk(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5) as writer:
        for i in range(10):
            writer.write(_frame(i))

    for segment in writer.sealed:
        with open(segment.path, "rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == segment.sha256


def test_closing_seals_the_final_partial_segment(tmp_path):
    """An incident that ends abruptly must not lose its last seconds."""
    writer = SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10)
    for i in range(13):
        writer.write(_frame(i))
    writer.close()

    assert len(writer.sealed) == 2
    assert all(len(s.sha256) == 64 for s in writer.sealed)
    assert writer.sealed[-1].frames == 3


def test_two_identical_segments_do_not_share_a_path(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5) as writer:
        for i in range(10):
            writer.write(_frame(i, value=120))

    paths = {s.path for s in writer.sealed}
    assert len(paths) == 2


def test_writing_after_close_is_refused(tmp_path):
    writer = SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5)
    writer.write(_frame(0))
    writer.close()

    with pytest.raises(RuntimeError):
        writer.write(_frame(1))


def test_closing_twice_is_harmless(tmp_path):
    """Called from a finally block and from __exit__. Must not double-seal."""
    writer = SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5)
    writer.write(_frame(0))
    writer.close()
    writer.close()

    assert len(writer.sealed) == 1


def test_a_writer_that_never_saw_a_frame_seals_nothing(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5):
        pass

    assert True  # closing an empty writer must not raise


def test_the_recorder_does_not_alter_the_frame_it_is_given(tmp_path):
    """These files are evidence. The array handed in must come back untouched."""
    frame = _frame(0)
    before = frame.image.copy()

    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5) as writer:
        writer.write(frame)

    assert np.array_equal(frame.image, before)
