"""Track bookkeeping, proved with no model weights and no torch installed."""

import numpy as np
import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.track import BBox, Detection, StubTracker, Track, TrackBook, UnavailableTracker


def _frame(index: int) -> Frame:
    return Frame(
        image=np.zeros((120, 160, 3), dtype=np.uint8),
        index=index,
        captured_at=utc_now(),
    )


def test_bbox_rejects_coordinates_outside_zero_to_one():
    """Normalised, so a client can scale them to any view size."""
    with pytest.raises(ValueError):
        BBox(x1=0.1, y1=0.1, x2=1.4, y2=0.9)


def test_bbox_rejects_an_inverted_box():
    with pytest.raises(ValueError):
        BBox(x1=0.9, y1=0.1, x2=0.2, y2=0.8)


def test_bbox_accepts_the_full_frame():
    """Someone standing right against the lens. Legal, not an error."""
    assert BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0).x2 == 1.0


def test_a_track_seen_once_is_present_and_counted():
    book = TrackBook(VisionConfig())
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9))]])

    book.ingest(tracker.update(_frame(0)), frame_index=0)

    assert book.people_visible == 1
    assert [t.track_id for t in book.active] == [7]


def test_a_track_holds_its_identity_across_frames():
    book = TrackBook(VisionConfig())
    box = BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9)
    tracker = StubTracker([[(7, box)], [(7, box)], [(7, box)]])

    for index in range(3):
        book.ingest(tracker.update(_frame(index)), frame_index=index)

    assert book.people_visible == 1
    assert book.active[0].frames_held == 3
    assert book.active[0].first_seen_frame == 0
    assert book.active[0].last_seen_frame == 2


def test_two_people_are_counted_separately():
    book = TrackBook(VisionConfig())
    tracker = StubTracker([[
        (7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9)),
        (8, BBox(x1=0.5, y1=0.1, x2=0.7, y2=0.9)),
    ]])

    book.ingest(tracker.update(_frame(0)), frame_index=0)

    assert book.people_visible == 2


def test_a_track_survives_a_brief_gap():
    """BoT-SORT keeps lost tracks alive through occlusion. So must the book."""
    config = VisionConfig(track_expiry_frames=10)
    book = TrackBook(config)
    box = BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9)
    tracker = StubTracker([[(7, box)], [], [], [(7, box)]])

    for index in range(4):
        book.ingest(tracker.update(_frame(index)), frame_index=index)

    assert book.people_visible == 1
    assert book.active[0].track_id == 7


def test_a_track_expires_once_it_has_been_gone_long_enough():
    config = VisionConfig(track_expiry_frames=2)
    book = TrackBook(config)
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9))], [], [], []])

    for index in range(4):
        book.ingest(tracker.update(_frame(index)), frame_index=index)

    assert book.people_visible == 0


def test_an_empty_room_reports_zero_rather_than_unknown():
    """Zero people in this room is a fact. It is not an absence of information."""
    book = TrackBook(VisionConfig())
    book.ingest([], frame_index=0)

    assert book.people_visible == 0
    assert book.active == []


def test_a_tracks_box_follows_it_rather_than_staying_where_it_appeared():
    book = TrackBook(VisionConfig())
    tracker = StubTracker([
        [(7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9))],
        [(7, BBox(x1=0.6, y1=0.1, x2=0.8, y2=0.9))],
    ])

    for index in range(2):
        book.ingest(tracker.update(_frame(index)), frame_index=index)

    assert book.active[0].bbox.x1 == 0.6


def test_a_track_exposes_the_fields_a_claim_needs():
    book = TrackBook(VisionConfig())
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.2, x2=0.3, y2=0.9))]])
    book.ingest(tracker.update(_frame(0)), frame_index=0)

    track = book.active[0]

    assert isinstance(track, Track)
    assert track.track_id == 7
    assert track.bbox.x1 == 0.1
    assert track.confidence == 1.0


def test_active_is_ordered_by_when_each_person_first_appeared():
    """Stable ordering, so an overlay does not reshuffle its labels each frame."""
    book = TrackBook(VisionConfig())
    first = BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9)
    second = BBox(x1=0.5, y1=0.1, x2=0.7, y2=0.9)
    tracker = StubTracker([[(9, first)], [(9, first), (4, second)]])

    for index in range(2):
        book.ingest(tracker.update(_frame(index)), frame_index=index)

    assert [t.track_id for t in book.active] == [9, 4]


def test_the_stub_runs_out_of_script_gracefully():
    """Past the end of its script it reports an empty room, it does not raise."""
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.1, x2=0.3, y2=0.9))]])

    tracker.update(_frame(0))

    assert tracker.update(_frame(1)) == []


def test_a_detection_defaults_to_full_confidence():
    """The stub asserts what it was told. Only a real detector has doubt."""
    assert Detection(track_id=1, bbox=BBox(x1=0.1, y1=0.1, x2=0.2, y2=0.2)).confidence == 1.0


def test_a_failed_detector_yields_a_tracker_that_finds_nothing_rather_than_raising():
    """The tracker is a corroborating view, not a gate.

    A missing weights file or an unavailable MPS backend must cost the measured
    count and nothing else. Narration and recording keep running, because the
    footage is the thing worth having when everything else fails.
    """
    tracker = UnavailableTracker(reason="weights missing")

    assert tracker.update(_frame(0)) == []
    assert tracker.available is False
    assert tracker.reason == "weights missing"


def test_a_working_tracker_reports_itself_available():
    tracker = StubTracker([[]])

    assert tracker.available is True
    assert tracker.reason is None


def test_the_book_of_an_unavailable_tracker_reports_zero_not_a_false_count():
    book = TrackBook(VisionConfig())
    tracker = UnavailableTracker(reason="mps unavailable")

    book.ingest(tracker.update(_frame(0)), frame_index=0)

    assert book.people_visible == 0


def test_an_unavailable_tracker_keeps_returning_nothing_rather_than_degrading():
    """Called every frame for the length of an incident. It must stay quiet."""
    tracker = UnavailableTracker(reason="weights missing")

    assert all(tracker.update(_frame(i)) == [] for i in range(100))


def test_the_factory_returns_an_unavailable_tracker_when_weights_are_missing():
    """The single place that decides between the real thing and the stand-in."""
    from hawkeye_vision.yolo_tracker import build_tracker

    tracker = build_tracker(VisionConfig(), weights="/nonexistent/no-such-weights.pt")

    assert tracker.available is False
    assert tracker.reason is not None
    assert tracker.update(_frame(0)) == []
