"""The transform applied to a frame before the detector sees it, in low light."""

import numpy as np

from hawkeye_vision.enhance import to_detection_input


def _noisy_dim(seed: int = 0) -> np.ndarray:
    """A dim frame with real structure in it, not a flat field."""
    rng = np.random.default_rng(seed)
    base = rng.integers(20, 70, size=(120, 160), dtype=np.uint8)
    return np.stack([base, base, base], axis=2)


def test_enhancement_returns_a_three_channel_image():
    """The detector wants BGR. Greyscale is stacked back to three channels."""
    result = to_detection_input(_noisy_dim(), enhance=True)

    assert result.shape == (120, 160, 3)
    assert result.dtype == np.uint8


def test_enhancement_widens_the_contrast_of_a_dim_frame():
    dim = _noisy_dim()
    result = to_detection_input(dim, enhance=True)

    assert result.std() > dim.std()


def test_enhancement_off_returns_the_frame_unchanged():
    dim = _noisy_dim()
    result = to_detection_input(dim, enhance=False)

    assert np.array_equal(result, dim)


def test_enhancement_does_not_mutate_the_frame_it_was_given():
    """The same frame goes to the recorder. Altering it in place alters evidence."""
    dim = _noisy_dim()
    before = dim.copy()

    to_detection_input(dim, enhance=True)

    assert np.array_equal(dim, before)


def test_enhancement_off_does_not_copy_needlessly():
    """This runs on every frame at 15fps. The no-op path must be a no-op."""
    dim = _noisy_dim()

    assert to_detection_input(dim, enhance=False) is dim


def test_a_black_frame_survives_enhancement_without_error():
    """TOO_DARK should stop us reaching here, but a black frame must not crash
    the pipeline if it does."""
    black = np.zeros((120, 160, 3), dtype=np.uint8)

    result = to_detection_input(black, enhance=True)

    assert result.shape == (120, 160, 3)
