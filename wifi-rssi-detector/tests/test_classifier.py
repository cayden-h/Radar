import pytest
from classifier import BaselineClassifier


def test_classify_absent_when_variance_near_baseline():
    clf = BaselineClassifier(initial_baseline_variance=1.0, initial_baseline_motion_energy=1.0)
    state = clf.classify(variance=1.0, motion_energy=1.0)
    assert state == "absent"


def test_classify_present_still_when_variance_elevated_but_motion_low():
    clf = BaselineClassifier(
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        initial_baseline_variance=1.0,
        initial_baseline_motion_energy=1.0,
    )
    state = clf.classify(variance=5.0, motion_energy=1.0)  # ratio 5.0 > 3.0, motion ratio 1.0 < 4.0
    assert state == "present-still"


def test_classify_active_when_motion_ratio_exceeds_threshold():
    clf = BaselineClassifier(
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        initial_baseline_variance=1.0,
        initial_baseline_motion_energy=1.0,
    )
    state = clf.classify(variance=5.0, motion_energy=10.0)  # motion ratio 10.0 > 4.0
    assert state == "active"


def test_baseline_updates_toward_new_quiet_readings():
    clf = BaselineClassifier(
        baseline_alpha=0.5,  # fast for test determinism
        initial_baseline_variance=1.0,
        initial_baseline_motion_energy=1.0,
    )
    clf.classify(variance=1.0, motion_energy=1.0)  # absent tick, baseline updates
    clf.classify(variance=2.0, motion_energy=1.0)  # still absent-ish, updates again
    assert clf.baseline_variance == pytest.approx(1.5)


def test_baseline_does_not_update_on_active_tick():
    clf = BaselineClassifier(
        baseline_alpha=0.5,
        active_motion_ratio=4.0,
        initial_baseline_variance=1.0,
        initial_baseline_motion_energy=1.0,
    )
    clf.classify(variance=50.0, motion_energy=50.0)  # active — ratios blow past thresholds
    assert clf.baseline_variance == pytest.approx(1.0)
    assert clf.baseline_motion_energy == pytest.approx(1.0)


def test_epsilon_prevents_division_by_zero_when_baseline_is_zero():
    clf = BaselineClassifier(initial_baseline_variance=0.0, initial_baseline_motion_energy=0.0, epsilon=1e-6)
    state = clf.classify(variance=0.0, motion_energy=0.0)
    assert state == "absent"
