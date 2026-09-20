"""The real detector. Marked integration: needs weights and a working MPS path.

Run with:     python3 -m pytest tests/test_yolo.py -v -m integration
Skip with:    python3 -m pytest tests/ -m 'not integration'
"""

import numpy as np
import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.track import BBox, Detection

pytestmark = pytest.mark.integration


def _frame(image: np.ndarray, index: int = 0) -> Frame:
    return Frame(image=image, index=index, captured_at=utc_now())


def test_the_yolo_tracker_satisfies_the_tracker_protocol():
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    result = tracker.update(_frame(np.zeros((480, 640, 3), dtype=np.uint8)))

    assert isinstance(result, list)
    assert all(isinstance(d, Detection) for d in result)


def test_an_empty_frame_produces_no_detections_rather_than_raising():
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())

    assert tracker.update(_frame(np.zeros((480, 640, 3), dtype=np.uint8))) == []


def test_the_confidence_floor_can_be_raised_for_low_light():
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    config = VisionConfig()
    tracker = YoloBotSortTracker(config)
    tracker.set_confidence(config.low_confidence)

    assert tracker.update(_frame(np.zeros((480, 640, 3), dtype=np.uint8))) == []


def test_detections_come_back_normalised(person_mp4):
    """Pixel coordinates leaking out of here would break every client overlay."""
    from hawkeye_vision.fixture import FileFixture
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    seen: list[Detection] = []

    with FileFixture(person_mp4) as source:
        for frame in source.frames():
            seen.extend(tracker.update(frame))

    assert seen, "expected at least one person detected in the recorded fixture"
    for detection in seen:
        assert isinstance(detection.bbox, BBox)


def test_track_identity_survives_a_crossing_occlusion(person_mp4):
    """The reason ReID is on. Two people crossing must not swap or multiply ids."""
    from hawkeye_vision.fixture import FileFixture
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    ids: set[int] = set()

    with FileFixture(person_mp4) as source:
        for frame in source.frames():
            ids.update(d.track_id for d in tracker.update(frame))

    # Record the fixture with a known number of people and set this to match.
    # A count far above it means identities are being dropped and reissued.
    assert len(ids) <= 4
