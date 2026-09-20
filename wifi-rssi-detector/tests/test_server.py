import pytest
from server import build_tick_payload
from classifier import BaselineClassifier


def test_build_tick_payload_empty_snapshot():
    clf = BaselineClassifier()
    payload = build_tick_payload([], clf, window_seconds=12.0, clock=lambda: 42.0)
    assert payload["ts"] == 42.0
    assert payload["rssi"] is None
    assert payload["variance"] == 0.0
    assert payload["motion_energy"] == 0.0
    assert payload["state"] == "absent"


def test_build_tick_payload_uses_latest_rssi():
    clf = BaselineClassifier()
    snapshot = [(0.0, -60.0), (1.0, -61.0), (2.0, -59.0)]
    payload = build_tick_payload(snapshot, clf, window_seconds=12.0, clock=lambda: 2.0)
    assert payload["rssi"] == -59.0
    assert payload["state"] in {"absent", "present-still", "active"}


def test_build_tick_payload_flags_active_on_large_swings():
    clf = BaselineClassifier(
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        initial_baseline_variance=0.5,
        initial_baseline_motion_energy=0.5,
    )
    # first, a few quiet ticks to look "normal"
    quiet_snapshot = [(0.0, -60.0), (1.0, -60.2), (2.0, -59.9)]
    build_tick_payload(quiet_snapshot, clf, window_seconds=12.0, clock=lambda: 2.0)
    # then a big swing
    active_snapshot = quiet_snapshot + [(3.0, -50.0), (4.0, -70.0), (5.0, -48.0)]
    payload = build_tick_payload(active_snapshot, clf, window_seconds=12.0, clock=lambda: 5.0)
    assert payload["state"] == "active"
