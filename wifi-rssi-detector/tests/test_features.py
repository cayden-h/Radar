import pytest
from features import extract_features, sliding_window_features


def test_extract_features_empty_samples():
    result = extract_features([], window_seconds=12.0)
    assert result == {"variance": 0.0, "motion_energy": 0.0, "n": 0}


def test_extract_features_single_sample():
    result = extract_features([(0.0, -60.0)], window_seconds=12.0)
    assert result == {"variance": 0.0, "motion_energy": 0.0, "n": 1}


def test_extract_features_constant_rssi_has_zero_variance_and_motion():
    samples = [(float(i), -60.0) for i in range(10)]
    result = extract_features(samples, window_seconds=12.0)
    assert result["variance"] == pytest.approx(0.0)
    assert result["motion_energy"] == pytest.approx(0.0)
    assert result["n"] == 10


def test_extract_features_only_uses_samples_within_window():
    old = [(0.0, -80.0), (1.0, -20.0)]  # outside the 12s window, would skew stats
    recent = [(20.0, -60.0), (21.0, -60.0), (22.0, -60.0)]
    result = extract_features(old + recent, window_seconds=12.0)
    assert result["n"] == 3
    assert result["variance"] == pytest.approx(0.0)


def test_extract_features_variance_matches_population_variance():
    samples = [(0.0, -60.0), (1.0, -62.0), (2.0, -58.0)]
    result = extract_features(samples, window_seconds=12.0)
    values = [-60.0, -62.0, -58.0]
    mean = sum(values) / 3
    expected_variance = sum((v - mean) ** 2 for v in values) / 3
    assert result["variance"] == pytest.approx(expected_variance)


def test_extract_features_motion_energy_is_mean_squared_delta():
    samples = [(0.0, -60.0), (1.0, -65.0), (2.0, -60.0)]
    result = extract_features(samples, window_seconds=12.0)
    deltas = [-65.0 - -60.0, -60.0 - -65.0]  # -5, +5
    expected_motion = sum(d ** 2 for d in deltas) / len(deltas)
    assert result["motion_energy"] == pytest.approx(expected_motion)


def test_sliding_window_features_returns_one_dict_per_step():
    samples = [(float(i), -60.0 + (i % 3)) for i in range(30)]
    windows = sliding_window_features(samples, window_seconds=12.0, step_seconds=5.0)
    assert len(windows) > 0
    assert all({"variance", "motion_energy", "n"} <= set(w.keys()) for w in windows)
