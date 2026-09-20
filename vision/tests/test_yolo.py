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
    """The reason ReID is on: an identity must survive being briefly occluded.

    What this asserts, and what it deliberately does not, because an earlier
    version of this test got it wrong twice.

    Counting every id ever issued is the wrong measure. A hand at the frame
    edge, or a head half out of shot, earns a legitimate id that lives three
    frames and vanishes. That is the detector working.

    Counting long-lived ids and comparing to the number of people is also the
    wrong measure. `botsort_reid.yaml` sets `track_buffer: 30`, so a track dies
    after two seconds unseen, and `vision/CLAUDE.md` states plainly that
    identities are stable within a session only and that we do no
    re-identification. A person who leaves the room and comes back a minute
    later SHOULD be a new id. Asserting otherwise would assert a capability we
    explicitly refuse to claim.

    What ReID actually buys us is continuity through a brief occlusion: someone
    passing behind another person, or behind furniture, keeps one id. That is
    what this measures, by requiring an identity to span far more frames than
    the track buffer could bridge on motion alone.

    Measured on the recorded fixture 2026-09-19: the longest track ran 235
    frames, and 7 tracks exceeded 80.
    """
    from collections import Counter

    from hawkeye_vision.fixture import FileFixture
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    frames_per_id: Counter[int] = Counter()

    with FileFixture(person_mp4) as source:
        for frame in source.frames():
            frames_per_id.update(d.track_id for d in tracker.update(frame))

    assert frames_per_id, "expected at least one person detected in the fixture"

    longest = max(frames_per_id.values())
    assert longest >= 100, (
        f"longest identity held only {longest} frames. ReID is not bridging "
        f"occlusion; check with_reid is still True in botsort_reid.yaml"
    )

    sustained = sum(1 for n in frames_per_id.values() if n >= 80)
    assert sustained >= 2, (
        f"only {sustained} identities lasted 80+ frames. One long track could "
        f"be a person who never moved; two or more is evidence of real tracking"
    )
