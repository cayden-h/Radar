"""Luminance measurement and the three states it maps onto."""

import numpy as np

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode, classify, mean_luminance


def _flat(value: int) -> np.ndarray:
    return np.full((120, 160, 3), value, dtype=np.uint8)


def test_mean_luminance_of_a_flat_field_is_that_value():
    assert mean_luminance(_flat(200)) == 200.0
    assert mean_luminance(_flat(0)) == 0.0


def test_mean_luminance_is_a_float_between_zero_and_255():
    value = mean_luminance(_flat(137))
    assert isinstance(value, float)
    assert 0.0 <= value <= 255.0


def test_a_bright_room_classifies_as_day():
    config = VisionConfig()
    assert classify(200.0, config) is LightingMode.DAY


def test_a_dim_room_classifies_as_low():
    config = VisionConfig()
    assert classify(50.0, config) is LightingMode.LOW


def test_a_black_frame_classifies_as_too_dark():
    """The shield-still-covering-the-lens case, and it must not be LOW."""
    config = VisionConfig()
    assert classify(5.0, config) is LightingMode.TOO_DARK


def test_thresholds_are_configurable_not_constants():
    """They must be calibrated at the venue, so they cannot be baked in."""
    strict = VisionConfig(day_threshold=220.0, dark_threshold=100.0)
    assert classify(200.0, strict) is LightingMode.LOW
    assert classify(50.0, strict) is LightingMode.TOO_DARK


def test_a_dark_video_classifies_as_too_dark_end_to_end(dark_mp4):
    """Straight off a file, the way the real pipeline sees it.

    This is the failure that looks like success: a working camera behind a
    shield that never moved produces exactly this, and the pipeline must call
    it too_dark rather than describe a dimly lit room.
    """
    from hawkeye_vision.fixture import FileFixture

    config = VisionConfig()
    with FileFixture(dark_mp4) as source:
        modes = [classify(mean_luminance(f.image), config) for f in source.frames()]

    assert set(modes) == {LightingMode.TOO_DARK}


def test_a_bright_video_classifies_as_day_end_to_end(bright_mp4):
    from hawkeye_vision.fixture import FileFixture

    config = VisionConfig()
    with FileFixture(bright_mp4) as source:
        modes = [classify(mean_luminance(f.image), config) for f in source.frames()]

    assert set(modes) == {LightingMode.DAY}
