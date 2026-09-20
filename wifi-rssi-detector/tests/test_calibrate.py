import pytest
from calibrate import summarize, suggest_thresholds


def test_summarize_returns_min_mean_max_for_each_metric():
    samples = [(float(i), -60.0 + (i % 5)) for i in range(40)]
    result = summarize(samples, window_seconds=12.0)
    assert set(result.keys()) == {"variance", "motion_energy"}
    for metric in result.values():
        assert set(metric.keys()) == {"min", "mean", "max"}
        assert metric["min"] <= metric["mean"] <= metric["max"]


def test_suggest_thresholds_is_midpoint_of_means():
    still_summary = {
        "variance": {"min": 0.1, "mean": 0.5, "max": 1.0},
        "motion_energy": {"min": 0.1, "mean": 0.4, "max": 0.9},
    }
    walk_summary = {
        "variance": {"min": 2.0, "mean": 4.5, "max": 8.0},
        "motion_energy": {"min": 3.0, "mean": 6.4, "max": 10.0},
    }
    thresholds = suggest_thresholds(still_summary, walk_summary)
    assert thresholds["present_variance_ratio"] == pytest.approx((0.5 + 4.5) / 2)
    assert thresholds["active_motion_ratio"] == pytest.approx((0.4 + 6.4) / 2)
