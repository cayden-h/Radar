"""Pure feature-extraction functions over (timestamp, rssi) sample windows."""


def extract_features(samples, window_seconds=12.0):
    if not samples:
        return {"variance": 0.0, "motion_energy": 0.0, "n": 0}

    latest_ts = samples[-1][0]
    cutoff = latest_ts - window_seconds
    window = [s for s in samples if s[0] >= cutoff]

    if len(window) < 2:
        return {"variance": 0.0, "motion_energy": 0.0, "n": len(window)}

    values = [rssi for _, rssi in window]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)

    # Rate of change (dBm/s) rather than a raw per-sample delta, so a dropped
    # read that widens the gap between two consecutive buffer entries doesn't
    # get treated as a bigger swing than it is.
    rates = []
    for i in range(1, len(window)):
        dt = window[i][0] - window[i - 1][0]
        if dt <= 0:
            continue
        rates.append((values[i] - values[i - 1]) / dt)

    motion_energy = sum(r ** 2 for r in rates) / len(rates) if rates else 0.0

    return {"variance": variance, "motion_energy": motion_energy, "n": len(window)}


def sliding_window_features(samples, window_seconds, step_seconds=1.0):
    if not samples:
        return []

    start_ts = samples[0][0]
    end_ts = samples[-1][0]

    results = []
    cursor = start_ts + window_seconds
    while cursor <= end_ts:
        slice_samples = [s for s in samples if cursor - window_seconds <= s[0] <= cursor]
        results.append(extract_features(slice_samples, window_seconds=window_seconds))
        cursor += step_seconds

    return results
