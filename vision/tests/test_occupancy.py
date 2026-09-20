"""The three-valued occupancy verdict.

`tracker_unavailable` is the interesting one. A tracker with no weights file
returns zero detections, which is indistinguishable from an empty room unless
the verdict carries the distinction explicitly. A blind camera that reads as
`no_person` would close the shutter and look like a working benign close.
"""

from __future__ import annotations

from hawkeye_vision.occupancy import Occupancy, verdict
from hawkeye_vision.track import BBox, Detection


def _det(track_id: int) -> Detection:
    return Detection(track_id=track_id, bbox=BBox(0.1, 0.1, 0.2, 0.4))


def test_no_detections_is_no_person() -> None:
    assert verdict([], tracker_available=True) is Occupancy.NO_PERSON


def test_one_detection_is_person_present() -> None:
    assert verdict([_det(1)], tracker_available=True) is Occupancy.PERSON_PRESENT


def test_many_detections_are_still_person_present() -> None:
    """The verdict is personhood, not a count. A count would be an identity claim."""
    assert verdict([_det(1), _det(2)], tracker_available=True) is Occupancy.PERSON_PRESENT


def test_unavailable_tracker_is_not_no_person() -> None:
    """The blind-camera case. Zero detections from a tracker that cannot see
    must never read as an empty room."""
    assert verdict([], tracker_available=False) is Occupancy.TRACKER_UNAVAILABLE


def test_unavailable_tracker_wins_over_detections() -> None:
    """A tracker that reports itself unavailable is not believed even if it
    somehow produced boxes."""
    assert verdict([_det(1)], tracker_available=False) is Occupancy.TRACKER_UNAVAILABLE
