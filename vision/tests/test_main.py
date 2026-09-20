"""The capture loop's resilience. The tracker must never cost us the footage."""

import numpy as np
import pytest

from hawkeye_vision.__main__ import detect_for_frame
from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.profiles import for_mode
from hawkeye_vision.track import BBox, Detection, StubTracker, UnavailableTracker


def _frame(index: int = 0) -> Frame:
    return Frame(
        image=np.full((120, 160, 3), 200, dtype=np.uint8),
        index=index,
        captured_at=utc_now(),
    )


class _ExplodingTracker:
    """A detector that loads fine and then fails mid-incident.

    `build_tracker` covers a model that fails to LOAD. This is the case that
    actually costs footage: an Ultralytics or MPS runtime error on some frame
    two minutes into an emergency.
    """

    available = True
    reason = None

    def update(self, frame):
        raise RuntimeError("MPS backend fell over")


def test_a_tracker_that_explodes_mid_incident_does_not_stop_the_loop():
    day = for_mode(LightingMode.DAY, VisionConfig())

    assert detect_for_frame(_ExplodingTracker(), _frame(), day) == []


def test_a_working_tracker_returns_its_detections():
    day = for_mode(LightingMode.DAY, VisionConfig())
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9))]])

    detections = detect_for_frame(tracker, _frame(), day)

    assert [d.track_id for d in detections] == [7]
    assert all(isinstance(d, Detection) for d in detections)


def test_a_too_dark_profile_does_not_reach_the_tracker_at_all():
    """A black frame must not be described. Not even attempted."""
    dark = for_mode(LightingMode.TOO_DARK, VisionConfig())

    assert detect_for_frame(_ExplodingTracker(), _frame(), dark) == []


def test_an_unavailable_tracker_yields_nothing_without_being_called():
    day = for_mode(LightingMode.DAY, VisionConfig())

    assert detect_for_frame(UnavailableTracker(reason="no weights"), _frame(), day) == []


def test_the_confidence_floor_is_pushed_down_when_the_tracker_accepts_one():
    seen = []

    class _Recording(StubTracker):
        def set_confidence(self, confidence):
            seen.append(confidence)

    config = VisionConfig()
    low = for_mode(LightingMode.LOW, config)
    detect_for_frame(_Recording([[]]), _frame(), low)

    assert seen == [config.low_confidence]


def test_a_tracker_with_no_set_confidence_is_still_usable():
    """StubTracker has no such method. It must not be required by the loop."""
    day = for_mode(LightingMode.DAY, VisionConfig())

    assert detect_for_frame(StubTracker([[]]), _frame(), day) == []
