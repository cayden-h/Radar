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


def test_baseline_does_not_collapse_below_the_floor_during_a_long_quiet_run():
    # Constant integer RSSI readings produce exact-zero variance/motion_energy.
    # Without a floor, the EMA baseline geometrically decays toward zero over a
    # long quiet run, and epsilon (1e-6) becomes the effective divisor -- so a
    # single-dBm flicker (routine radio noise) then reads as a huge ratio and
    # falsely triggers "active".
    clf = BaselineClassifier(min_baseline_variance=0.1, min_baseline_motion_energy=0.1)
    for _ in range(5000):  # far more than enough ticks for unfloored EMA to collapse
        state = clf.classify(variance=0.0, motion_energy=0.0)
        assert state == "absent"
    assert clf.baseline_variance == pytest.approx(0.1)
    assert clf.baseline_motion_energy == pytest.approx(0.1)

    # A one-dBm flicker after that long quiet run must not falsely read as motion.
    state = clf.classify(variance=0.027, motion_energy=0.029)
    assert state == "absent"


def test_present_still_is_sustained_rather_than_decaying_to_absent():
    # Freezing the baseline only on "active" let a present-still tick keep
    # dragging the baseline toward itself, so present-still decayed back to
    # absent within a few seconds. Freezing on any non-absent state fixes it.
    clf = BaselineClassifier(
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        baseline_alpha=0.02,
        initial_baseline_variance=1.0,
        initial_baseline_motion_energy=1.0,
    )
    states = [clf.classify(variance=5.0, motion_energy=1.0) for _ in range(50)]
    assert all(state == "present-still" for state in states)
