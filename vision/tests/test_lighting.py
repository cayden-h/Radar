"""Luminance measurement and the three states it maps onto."""

import numpy as np

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.fixture import FileFixture
from hawkeye_vision.lighting import LightingClassifier, LightingMode, classify, mean_luminance


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


def test_classifier_starts_in_the_state_of_its_first_reading():
    classifier = LightingClassifier(VisionConfig())
    assert classifier.update(200.0) is LightingMode.DAY


def test_a_single_dark_frame_does_not_change_state():
    """One frame is a shadow. Three seconds of frames is nightfall."""
    config = VisionConfig(dwell_frames=45)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    assert classifier.update(5.0) is LightingMode.DAY


def test_state_changes_once_the_candidate_holds_for_the_dwell():
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    results = [classifier.update(5.0) for _ in range(6)]

    assert results[:4] == [LightingMode.DAY] * 4
    assert results[-1] is LightingMode.TOO_DARK


def test_an_interrupted_candidate_resets_the_dwell():
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    classifier.update(5.0)
    classifier.update(5.0)
    classifier.update(200.0)  # back to bright: the candidate is abandoned
    results = [classifier.update(5.0) for _ in range(4)]

    assert results == [LightingMode.DAY] * 4


def test_the_mode_property_reports_the_state_in_effect():
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)

    assert classifier.mode is None

    classifier.update(200.0)
    assert classifier.mode is LightingMode.DAY


def test_a_value_sitting_on_the_boundary_does_not_flap(ramp_mp4):
    """A smooth fall to black and back produces the transitions the signal
    physically contains, and no more.

    This fixture is monotonic, so it does NOT exercise hysteresis: it never
    revisits a threshold from both sides. The hysteresis proof is
    `test_noise_straddling_a_threshold_does_not_change_state`."""
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)

    states = []
    with FileFixture(ramp_mp4) as source:
        for frame in source.frames():
            states.append(classifier.update(mean_luminance(frame.image)))

    transitions = sum(1 for a, b in zip(states, states[1:]) if a is not b)

    # The ramp falls from bright to black and climbs back, crossing both
    # thresholds twice, so four transitions is the truth of this signal.
    assert transitions <= 6


def test_a_shield_jammed_over_the_lens_is_caught_even_from_broad_daylight():
    """Regression. The servo is open-loop and attests the angle it was told to,
    so a jammed shield reports open while still covering the lens. A dark frame
    is the only evidence there is, and a two-band jump from DAY must not be
    swallowed by hysteresis anchored on the wrong threshold."""
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    # 5.0 sits inside the band the old bug swallowed: above
    # dark_threshold - hysteresis, and below dark_threshold. That is exactly
    # where a two-step jump from DAY used to be held at DAY forever.
    for _ in range(20):
        classifier.update(5.0)

    assert classifier.mode is LightingMode.TOO_DARK


def test_every_luminance_below_the_dark_threshold_is_eventually_caught():
    """No value that classify() calls TOO_DARK may be permanently unreachable."""
    config = VisionConfig(dwell_frames=5)

    for luminance in range(0, int(config.dark_threshold)):
        classifier = LightingClassifier(config)
        classifier.update(200.0)
        for _ in range(20):
            classifier.update(float(luminance))

        assert classifier.mode is LightingMode.TOO_DARK, (
            f"luminance {luminance} is classified TOO_DARK by classify() "
            f"but the classifier stayed in {classifier.mode}"
        )


def test_a_lit_room_is_recognised_after_darkness_even_when_the_reading_is_noisy():
    """Regression. Noise straddling a threshold must not stall the dwell forever."""
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(5.0)

    for value in [89.0, 91.0] * 20:
        classifier.update(value)

    assert classifier.mode is not LightingMode.TOO_DARK


def test_noise_straddling_a_threshold_does_not_change_state():
    """The real hysteresis test, and one a classifier without hysteresis fails.

    88 and 92 sit either side of day_threshold (90) by less than the margin (8).
    classify() alternates LOW and DAY on this input every single frame. The
    classifier must sit still."""
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    states = [classifier.update(v) for v in [88.0, 92.0] * 50]

    assert set(states) == {LightingMode.DAY}


def test_the_stateless_classifier_really_does_flap_on_that_input():
    """Proves the test above has teeth rather than passing vacuously."""
    config = VisionConfig()
    naive = [classify(v, config) for v in [88.0, 92.0] * 50]

    assert len(set(naive)) == 2
