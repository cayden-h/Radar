"""What the capture settings become in each lighting state."""

import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.profiles import CaptureProfile, for_mode


def test_day_runs_at_full_rate_in_colour_without_enhancement():
    profile = for_mode(LightingMode.DAY, VisionConfig())

    assert profile.fps == 15
    assert profile.enhance is False
    assert profile.detect is True


def test_low_drops_the_rate_and_enhances_before_detection():
    profile = for_mode(LightingMode.LOW, VisionConfig())

    assert profile.fps == 8
    assert profile.enhance is True
    assert profile.detect is True


def test_low_raises_the_confidence_floor():
    """A gain-boosted frame produces confident nonsense. Demand more of it."""
    day = for_mode(LightingMode.DAY, VisionConfig())
    low = for_mode(LightingMode.LOW, VisionConfig())

    assert low.confidence > day.confidence


def test_too_dark_does_not_detect_at_all():
    profile = for_mode(LightingMode.TOO_DARK, VisionConfig())

    assert profile.detect is False


def test_too_dark_does_not_enhance_either():
    """Contrast-stretching a black frame produces amplified noise, which the
    detector then finds people in. Enhancement is not a substitute for light."""
    profile = for_mode(LightingMode.TOO_DARK, VisionConfig())

    assert profile.enhance is False


def test_a_profile_cannot_be_mutated_after_it_is_chosen():
    profile = for_mode(LightingMode.DAY, VisionConfig())

    with pytest.raises(Exception):
        profile.fps = 60


def test_profiles_follow_the_config_rather_than_hardcoding():
    """Thresholds and rates are calibrated at the venue, so nothing is baked in."""
    tuned = VisionConfig(day_fps=30, low_fps=4, day_confidence=0.2, low_confidence=0.9)

    assert for_mode(LightingMode.DAY, tuned).fps == 30
    assert for_mode(LightingMode.LOW, tuned).fps == 4
    assert for_mode(LightingMode.DAY, tuned).confidence == 0.2
    assert for_mode(LightingMode.LOW, tuned).confidence == 0.9


def test_every_lighting_mode_has_a_profile():
    """A new mode with no profile must fail loudly, not silently pick a default."""
    for mode in LightingMode:
        assert isinstance(for_mode(mode, VisionConfig()), CaptureProfile)
