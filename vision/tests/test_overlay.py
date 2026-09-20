"""Drawing tracks onto a frame. Pure pixels, no camera."""

import numpy as np

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.overlay import draw
from hawkeye_vision.track import BBox, Detection, TrackBook


def _blank() -> np.ndarray:
    return np.zeros((240, 320, 3), dtype=np.uint8)


def _book_with_one_track() -> TrackBook:
    book = TrackBook(VisionConfig())
    book.ingest(
        [Detection(track_id=3, bbox=BBox(x1=0.2, y1=0.2, x2=0.6, y2=0.9), confidence=0.9)],
        frame_index=0,
    )
    return book


def test_drawing_does_not_mutate_the_frame_it_was_given():
    """The recorder gets the same frame. An overlay burned into evidence is fatal."""
    frame = _blank()
    before = frame.copy()

    draw(frame, _book_with_one_track(), LightingMode.DAY, 200.0)

    assert np.array_equal(frame, before)


def test_drawing_puts_pixels_on_the_returned_copy():
    result = draw(_blank(), _book_with_one_track(), LightingMode.DAY, 200.0)

    assert result.sum() > 0


def test_an_empty_book_still_renders_the_status_line():
    result = draw(_blank(), TrackBook(VisionConfig()), LightingMode.TOO_DARK, 4.0)

    assert result.sum() > 0


def test_boxes_are_scaled_from_normalised_coordinates_to_the_frame():
    """A 0.2..0.6 box on a 320-wide frame must land at x 64..192, not at 0..1.

    Only the rows above the status line are examined. The status text starts at
    x=8 and runs most of the width, so it puts ink in every column near the
    bottom of the frame and would mask the thing this test is actually about.
    """
    result = draw(_blank(), _book_with_one_track(), LightingMode.DAY, 200.0)
    above_status = result[:200]
    column_has_ink = above_status.sum(axis=(0, 2)) > 0

    assert column_has_ink[64], "expected the box's left edge at x=64"
    assert not column_has_ink[20], "nothing should be drawn left of the box"
    assert column_has_ink[192], "expected the box's right edge at x=192"


def test_each_lighting_mode_draws_in_its_own_colour():
    """The state must be readable at a glance from across a demo room."""
    book = _book_with_one_track()
    day = draw(_blank(), book, LightingMode.DAY, 200.0)
    low = draw(_blank(), book, LightingMode.LOW, 50.0)
    dark = draw(_blank(), book, LightingMode.TOO_DARK, 4.0)

    assert not np.array_equal(day, low)
    assert not np.array_equal(low, dark)


def test_the_returned_frame_keeps_the_original_shape_and_dtype():
    result = draw(_blank(), _book_with_one_track(), LightingMode.DAY, 200.0)

    assert result.shape == (240, 320, 3)
    assert result.dtype == np.uint8
