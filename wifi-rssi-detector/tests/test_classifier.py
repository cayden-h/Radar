import pytest
from classifier import BaselineClassifier


def test_classify_absent_when_motion_near_baseline():
    clf = BaselineClassifier(initial_baseline_motion_energy=1.0)
    state = clf.classify(variance=1.0, motion_energy=1.0)
    assert state == "absent"


def test_classify_active_when_motion_ratio_exceeds_threshold():
    clf = BaselineClassifier(active_motion_ratio=4.0, initial_baseline_motion_energy=1.0)
    state = clf.classify(variance=5.0, motion_energy=10.0)  # motion ratio 10.0 > 4.0
    assert state == "active"


def test_baseline_updates_toward_new_quiet_readings():
    clf = BaselineClassifier(
        baseline_alpha=0.5,  # fast for test determinism
        initial_baseline_motion_energy=1.0,
    )
    clf.classify(variance=0.0, motion_energy=1.0)  # absent tick, baseline updates
    clf.classify(variance=0.0, motion_energy=2.0)  # still absent-ish, updates again
    assert clf.baseline_motion_energy == pytest.approx(1.5)


def test_baseline_does_not_update_on_active_tick():
    clf = BaselineClassifier(
        baseline_alpha=0.5,
        active_motion_ratio=4.0,
        initial_baseline_motion_energy=1.0,
    )
    clf.classify(variance=50.0, motion_energy=50.0)  # active — ratio blows past threshold
    assert clf.baseline_motion_energy == pytest.approx(1.0)


def test_epsilon_prevents_division_by_zero_when_baseline_is_zero():
    clf = BaselineClassifier(initial_baseline_motion_energy=0.0, epsilon=1e-6)
    state = clf.classify(variance=0.0, motion_energy=0.0)
    assert state == "absent"


def test_baseline_does_not_collapse_below_the_floor_during_a_long_quiet_run():
    # Constant integer RSSI readings produce exact-zero motion_energy. Without
    # a floor, the EMA baseline geometrically decays toward zero over a long
    # quiet run, and epsilon (1e-6) becomes the effective divisor -- so a
    # single-dBm flicker (routine radio noise) then reads as a huge ratio and
    # falsely triggers "active".
    clf = BaselineClassifier(min_baseline_motion_energy=0.1)
    for _ in range(5000):  # far more than enough ticks for unfloored EMA to collapse
        state = clf.classify(variance=0.0, motion_energy=0.0)
        assert state == "absent"
    assert clf.baseline_motion_energy == pytest.approx(0.1)

    # A one-dBm flicker after that long quiet run must not falsely read as motion.
    state = clf.classify(variance=0.027, motion_energy=0.029)
    assert state == "absent"


def test_default_hysteresis_ticks_confirms_immediately():
    # hysteresis_ticks=1 (the default) must behave exactly like no debounce
    # at all -- every other test in this file relies on that.
    clf = BaselineClassifier(
        active_motion_ratio=4.0, initial_baseline_motion_energy=1.0
    )
    assert clf.classify(variance=1.0, motion_energy=1.0) == "absent"
    assert clf.classify(variance=5.0, motion_energy=10.0) == "active"


def test_hysteresis_requires_consecutive_ticks_before_reporting_a_new_state():
    clf = BaselineClassifier(
        active_motion_ratio=4.0,
        initial_baseline_motion_energy=1.0,
        hysteresis_ticks=3,
    )
    active_reading = {"variance": 5.0, "motion_energy": 10.0}  # motion ratio 10.0 > 4.0
    assert clf.classify(**active_reading) == "absent"  # 1st: pending, not yet confirmed
    assert clf.classify(**active_reading) == "absent"  # 2nd: still pending
    assert clf.classify(**active_reading) == "active"  # 3rd: confirmed


def test_hysteresis_pending_count_resets_on_a_conflicting_reading():
    clf = BaselineClassifier(
        active_motion_ratio=4.0,
        initial_baseline_motion_energy=1.0,
        hysteresis_ticks=3,
    )
    active_reading = {"variance": 5.0, "motion_energy": 10.0}
    quiet_reading = {"variance": 1.0, "motion_energy": 1.0}
    assert clf.classify(**active_reading) == "absent"  # pending count -> 1
    assert clf.classify(**active_reading) == "absent"  # pending count -> 2
    assert clf.classify(**quiet_reading) == "absent"  # breaks the streak, resets to 0
    assert clf.classify(**active_reading) == "absent"  # pending count -> 1 again
    assert clf.classify(**active_reading) == "absent"  # pending count -> 2
    assert clf.classify(**active_reading) == "active"  # pending count -> 3, confirmed


def test_baseline_freeze_follows_confirmed_state_not_raw_state_during_hysteresis():
    # While a new "active" reading is still pending confirmation, the
    # confirmed/reported state is still "absent", so the baseline should
    # keep adapting -- it must not silently freeze before the state
    # actually flips.
    clf = BaselineClassifier(
        active_motion_ratio=4.0,
        baseline_alpha=0.5,
        initial_baseline_motion_energy=1.0,
        hysteresis_ticks=3,
    )
    clf.classify(variance=5.0, motion_energy=10.0)  # pending, confirmed state still "absent"
    assert clf.baseline_motion_energy == pytest.approx(0.5 * 10.0 + 0.5 * 1.0)
