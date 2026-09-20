import pytest
from calibrate import summarize, suggest_thresholds


def test_summarize_returns_min_mean_max_for_each_metric():
    samples = [(float(i), -60.0 + (i % 5)) for i in range(40)]
    result = summarize(samples, window_seconds=12.0)
    assert set(result.keys()) == {"variance", "motion_energy"}
    for metric in result.values():
        assert set(metric.keys()) == {"min", "mean", "max"}
        assert metric["min"] <= metric["mean"] <= metric["max"]


def test_suggest_thresholds_is_midpoint_of_means_expressed_as_a_ratio_of_the_still_baseline():
    # suggest_thresholds() must return the same dimensionless units
    # BaselineClassifier's present_variance_ratio / active_motion_ratio consume
    # (a ratio against the runtime EMA baseline), not raw absolute dBm^2 means.
    still_summary = {
        "variance": {"min": 0.1, "mean": 0.5, "max": 1.0},
        "motion_energy": {"min": 0.1, "mean": 0.4, "max": 0.9},
    }
    walk_summary = {
        "variance": {"min": 2.0, "mean": 4.5, "max": 8.0},
        "motion_energy": {"min": 3.0, "mean": 6.4, "max": 10.0},
    }
    thresholds = suggest_thresholds(still_summary, walk_summary)
    variance_midpoint = (0.5 + 4.5) / 2
    motion_midpoint = (0.4 + 6.4) / 2
    assert thresholds["present_variance_ratio"] == pytest.approx(variance_midpoint / 0.5)
    assert thresholds["active_motion_ratio"] == pytest.approx(motion_midpoint / 0.4)


def test_summarize_raises_clear_error_when_capture_span_is_shorter_than_window():
    # A 10-second capture (the old documented --seconds example) against the
    # default 12-second window produces zero sliding windows. That must fail
    # loudly, naming the durations involved, rather than silently returning
    # all-zero stats that look like "still and walk are identical".
    samples = [(float(i) * 0.5, -60.0 + (i % 3)) for i in range(20)]  # 9.5s span at 2Hz
    with pytest.raises(ValueError) as excinfo:
        summarize(samples, window_seconds=12.0)
    message = str(excinfo.value)
    assert "9.5" in message
    assert "12" in message
