"""The frame source contract, proved against the fixture implementation."""

from datetime import datetime

from hawkeye_backend.models.common import Source
from hawkeye_vision.fixture import FileFixture


def test_fixture_yields_every_frame_in_the_file(bright_mp4):
    with FileFixture(bright_mp4) as source:
        frames = list(source.frames())

    assert len(frames) == 30


def test_frames_carry_a_monotonic_index_and_a_utc_timestamp(bright_mp4):
    with FileFixture(bright_mp4) as source:
        frames = list(source.frames())

    assert [f.index for f in frames] == list(range(30))
    assert all(isinstance(f.captured_at, datetime) for f in frames)
    assert all(f.captured_at.tzinfo is not None for f in frames)


def test_a_synthetic_fixture_declares_itself_simulated(bright_mp4):
    """The honesty rule, at the seam where it is cheapest to enforce."""
    with FileFixture(bright_mp4) as source:
        assert source.source is Source.CAMERA_SIM


def test_real_footage_replayed_declares_itself_measured_replay(bright_mp4):
    with FileFixture(bright_mp4, source=Source.REPLAY_VIDEO) as source:
        assert source.source is Source.REPLAY_VIDEO


def test_frames_are_bgr_images_with_three_channels(bright_mp4):
    with FileFixture(bright_mp4) as source:
        first = next(source.frames())

    assert first.image.ndim == 3
    assert first.image.shape[2] == 3


def test_opening_a_missing_file_raises_rather_than_yielding_nothing():
    """A silently empty frame source is the worst possible failure here: it
    looks exactly like a room with nothing happening in it."""
    import pytest

    with pytest.raises(FileNotFoundError):
        FileFixture("/nonexistent/definitely-not-here.mp4")
