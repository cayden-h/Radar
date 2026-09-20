# WiFi RSSI Motion/Presence Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained, Mac-only WiFi RSSI motion/presence detector (no external hardware) as a backup to the fragile Pi/CSI path — collector → feature extraction → threshold classifier → WebSocket broadcast → live HTML view, plus a labeled-calibration CLI.

**Architecture:** `MacWifiCollector` polls `CoreWLAN` RSSI on a background thread into a ring buffer. `features.py` computes rolling variance and frame-to-frame motion energy over a sliding window from pure functions. `classifier.py` maintains a slow EMA baseline and classifies via ratio thresholds (absent / present-still / active). `server.py` ticks this pipeline and broadcasts JSON over a local `websockets` server; `static/index.html` is a single dependency-free page that renders a status badge and RSSI sparkline. `calibrate.py` captures labeled still/walk windows and prints separated distributions so thresholds are chosen from data, not guessed.

**Tech Stack:** Python 3, `pyobjc-framework-CoreWLAN`, `websockets`, stdlib `asyncio`/`threading`/`collections.deque`, plain HTML/CSS/JS (canvas), `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-19-wifi-rssi-detector-design.md`

## Global Constraints

- Lives entirely under `wifi-rssi-detector/`. Must not modify anything in `sensor/`, `agents/`, `app/`, or any other existing directory.
- No ANS/agent-mesh integration — standalone tool.
- No FFT/spectral banding — use frame-to-frame Δrssi² motion energy. Only revisit if Task 6 calibration shows it fails to separate still vs. walk.
- No fixed absolute dBm thresholds in `classifier.py` — thresholds are ratios against a slow-adapting EMA baseline.
- No persistence/DB, no auth on the WebSocket server — localhost demo tool.
- Python deps isolated in a venv at `wifi-rssi-detector/.venv`, declared in `wifi-rssi-detector/requirements.txt`.
- Branch: `wifi-rssi-detector` (already created and checked out).

---

## File Structure

```
wifi-rssi-detector/
  requirements.txt
  collector.py           # MacWifiCollector
  features.py             # extract_features, sliding_window_features (pure functions)
  classifier.py            # BaselineClassifier
  server.py                # build_tick_payload + asyncio websockets server + tiny static file server
  static/index.html         # dependency-free frontend
  calibrate.py              # labeled capture + compare CLI
  README.md                 # setup + calibration walkthrough
  tests/
    __init__.py
    test_features.py
    test_classifier.py
    test_server.py
```

---

### Task 1: Project scaffolding and venv

**Files:**
- Create: `wifi-rssi-detector/requirements.txt`
- Create: `wifi-rssi-detector/README.md`
- Create: `wifi-rssi-detector/tests/__init__.py`
- Create: `wifi-rssi-detector/.gitignore`

**Interfaces:**
- Produces: a working venv at `wifi-rssi-detector/.venv` with `pyobjc-framework-CoreWLAN`, `websockets`, and `pytest` installed, activated for all later tasks.

- [ ] **Step 1: Create the directory and requirements file**

```bash
mkdir -p /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector/tests
mkdir -p /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector/static
```

Write `wifi-rssi-detector/requirements.txt`:

```
pyobjc-framework-CoreWLAN
websockets
pytest
```

- [ ] **Step 2: Create the venv and install**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Expected: all three packages install cleanly (pyobjc-framework-CoreWLAN pulls in `pyobjc-core` and `pyobjc-framework-Cocoa` as transitive deps — that's fine).

- [ ] **Step 3: Verify CoreWLAN is readable from this venv**

```bash
.venv/bin/python3 -c "
import CoreWLAN
client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
iface = client.interface()
print('interface:', iface)
print('rssi:', iface.rssiValue())
"
```

Expected: prints an interface object and an integer RSSI (e.g. `-61`), no sudo prompt, no exception.

- [ ] **Step 4: Add `.gitignore`**

Write `wifi-rssi-detector/.gitignore`:

```
.venv/
__pycache__/
*.pyc
*.json
!package.json
```

(The `*.json` ignore covers calibration capture files from Task 6, which are throwaway local data, not source.)

- [ ] **Step 5: Create empty test package marker**

Write `wifi-rssi-detector/tests/__init__.py` (empty file).

- [ ] **Step 6: Write README skeleton**

Write `wifi-rssi-detector/README.md`:

```markdown
# WiFi RSSI Motion/Presence Detector

Mac-only, self-contained backup to the Pi/CSI presence-detection path. Polls
this laptop's WiFi RSSI via CoreWLAN, computes rolling variance and
frame-to-frame motion energy over a sliding window, and classifies
absent / present-still / active using thresholds calibrated against your
environment — not fixed dBm numbers.

## Setup

    cd wifi-rssi-detector
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Calibrate before trusting any threshold

    .venv/bin/python3 calibrate.py --label still --seconds 10 --out still.json
    # now walk between the laptop and the router
    .venv/bin/python3 calibrate.py --label walk --seconds 10 --out walk.json
    .venv/bin/python3 calibrate.py --compare still.json walk.json

Paste the printed suggested thresholds into `classifier.py`.

## Run

    .venv/bin/python3 server.py

Then open `static/index.html` in a browser.
```

- [ ] **Step 7: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/requirements.txt wifi-rssi-detector/README.md wifi-rssi-detector/.gitignore wifi-rssi-detector/tests/__init__.py
git commit -m "$(cat <<'EOF'
Scaffold wifi-rssi-detector: venv, deps, README

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Feature extraction (`features.py`)

**Files:**
- Create: `wifi-rssi-detector/features.py`
- Test: `wifi-rssi-detector/tests/test_features.py`

**Interfaces:**
- Produces:
  - `extract_features(samples: list[tuple[float, float]], window_seconds: float = 12.0) -> dict` — returns `{"variance": float, "motion_energy": float, "n": int}` computed over the samples whose timestamp falls within `window_seconds` of the latest sample. `samples` is a list of `(timestamp, rssi)` sorted ascending by timestamp. Empty or single-sample input returns `{"variance": 0.0, "motion_energy": 0.0, "n": len(samples)}`.
  - `sliding_window_features(samples: list[tuple[float, float]], window_seconds: float, step_seconds: float = 1.0) -> list[dict]` — slides a window of `window_seconds` across the full `samples` array in `step_seconds` increments, calling `extract_features` on each slice, and returns the list of resulting dicts (used by `calibrate.py` in Task 6).

- [ ] **Step 1: Write failing tests for `extract_features`**

Write `wifi-rssi-detector/tests/test_features.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector
.venv/bin/python3 -m pytest tests/test_features.py -v
```

Expected: `ModuleNotFoundError: No module named 'features'` (or collection error) — nothing implemented yet.

- [ ] **Step 3: Implement `features.py`**

```python
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

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    motion_energy = sum(d ** 2 for d in deltas) / len(deltas)

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_features.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/features.py wifi-rssi-detector/tests/test_features.py
git commit -m "$(cat <<'EOF'
Add RSSI feature extraction: rolling variance + frame-to-frame motion energy

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Threshold classifier (`classifier.py`)

**Files:**
- Create: `wifi-rssi-detector/classifier.py`
- Test: `wifi-rssi-detector/tests/test_classifier.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (operates on `variance`/`motion_energy` floats, the output shape of `extract_features`).
- Produces:
  - `class BaselineClassifier`, constructor `BaselineClassifier(present_variance_ratio: float = 3.0, active_motion_ratio: float = 4.0, baseline_alpha: float = 0.02, epsilon: float = 1e-6, initial_baseline_variance: float = 0.5, initial_baseline_motion_energy: float = 0.5)`.
  - `.classify(variance: float, motion_energy: float) -> str` — returns one of `"absent"`, `"present-still"`, `"active"`. Updates the internal EMA baselines for `variance` and `motion_energy` on every call *except* when the tick is classified `"active"` (so real motion doesn't drag the baseline upward).
  - `.baseline_variance` and `.baseline_motion_energy` readable attributes (floats), for the server payload and calibration output.

- [ ] **Step 1: Write failing tests**

Write `wifi-rssi-detector/tests/test_classifier.py`:

```python
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
    assert clf.baseline_variance == pytest.approx(1.0 * 0.5 + (1.0 * 0.5 + 2.0 * 0.5) * 0.5)


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'classifier'`.

- [ ] **Step 3: Implement `classifier.py`**

```python
"""Ratio-based motion/presence classifier against a slow-adapting baseline."""


class BaselineClassifier:
    def __init__(
        self,
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        baseline_alpha=0.02,
        epsilon=1e-6,
        initial_baseline_variance=0.5,
        initial_baseline_motion_energy=0.5,
    ):
        self.present_variance_ratio = present_variance_ratio
        self.active_motion_ratio = active_motion_ratio
        self.baseline_alpha = baseline_alpha
        self.epsilon = epsilon
        self.baseline_variance = initial_baseline_variance
        self.baseline_motion_energy = initial_baseline_motion_energy

    def classify(self, variance, motion_energy):
        variance_ratio = variance / max(self.baseline_variance, self.epsilon)
        motion_ratio = motion_energy / max(self.baseline_motion_energy, self.epsilon)

        if motion_ratio > self.active_motion_ratio:
            state = "active"
        elif variance_ratio > self.present_variance_ratio:
            state = "present-still"
        else:
            state = "absent"

        if state != "active":
            self.baseline_variance = (
                self.baseline_alpha * variance + (1 - self.baseline_alpha) * self.baseline_variance
            )
            self.baseline_motion_energy = (
                self.baseline_alpha * motion_energy + (1 - self.baseline_alpha) * self.baseline_motion_energy
            )

        return state
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_classifier.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/classifier.py wifi-rssi-detector/tests/test_classifier.py
git commit -m "$(cat <<'EOF'
Add ratio-based BaselineClassifier for absent/present-still/active states

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `MacWifiCollector`

**Files:**
- Create: `wifi-rssi-detector/collector.py`
- Test: `wifi-rssi-detector/tests/test_collector.py`

**Interfaces:**
- Produces:
  - `class MacWifiCollector`, constructor `MacWifiCollector(poll_hz: float = 3.0, buffer_seconds: float = 15.0, rssi_reader: callable | None = None, clock: callable = time.time)`. `rssi_reader` defaults to a real CoreWLAN reader; tests inject a fake.
  - `.poll_once() -> tuple[float, float] | None` — reads one RSSI sample via `rssi_reader()`, and if not `None`, appends `(clock(), rssi)` to the internal buffer and returns it; if `rssi_reader()` returns `None` (read failure), appends nothing and returns `None`.
  - `.snapshot() -> list[tuple[float, float]]` — returns a copy of the current buffer contents, oldest first.
  - `.start()` / `.stop()` — start/stop a background thread that calls `poll_once()` every `1/poll_hz` seconds.

- [ ] **Step 1: Write failing tests (using a fake `rssi_reader`, no real hardware, no thread timing)**

Write `wifi-rssi-detector/tests/test_collector.py`:

```python
import pytest
from collector import MacWifiCollector


def make_fake_clock(times):
    it = iter(times)
    return lambda: next(it)


def test_poll_once_appends_sample_and_returns_it():
    clock = make_fake_clock([100.0])
    collector = MacWifiCollector(rssi_reader=lambda: -60, clock=clock)
    result = collector.poll_once()
    assert result == (100.0, -60)
    assert collector.snapshot() == [(100.0, -60)]


def test_poll_once_skips_sample_on_read_failure():
    clock = make_fake_clock([100.0])
    collector = MacWifiCollector(rssi_reader=lambda: None, clock=clock)
    result = collector.poll_once()
    assert result is None
    assert collector.snapshot() == []


def test_buffer_is_bounded_by_poll_hz_and_buffer_seconds():
    # poll_hz=2, buffer_seconds=1 -> maxlen 2
    times = iter(float(i) for i in range(10))
    clock = lambda: next(times)
    collector = MacWifiCollector(poll_hz=2.0, buffer_seconds=1.0, rssi_reader=lambda: -60, clock=clock)
    for _ in range(5):
        collector.poll_once()
    snapshot = collector.snapshot()
    assert len(snapshot) == 2


def test_snapshot_returns_samples_oldest_first():
    times = iter([1.0, 2.0, 3.0])
    clock = lambda: next(times)
    collector = MacWifiCollector(poll_hz=10.0, buffer_seconds=100.0, rssi_reader=lambda: -60, clock=clock)
    for _ in range(3):
        collector.poll_once()
    snapshot = collector.snapshot()
    assert [ts for ts, _ in snapshot] == [1.0, 2.0, 3.0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_collector.py -v
```

Expected: `ModuleNotFoundError: No module named 'collector'`.

- [ ] **Step 3: Implement `collector.py`**

```python
"""Polls WiFi RSSI via CoreWLAN into a bounded ring buffer."""

import threading
import time
from collections import deque


def _read_rssi_via_corewlan():
    import CoreWLAN

    client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
    iface = client.interface()
    if iface is None:
        return None
    value = iface.rssiValue()
    if value == 0:
        # CoreWLAN returns 0 when there's no valid reading (e.g. disassociated)
        return None
    return value


class MacWifiCollector:
    def __init__(self, poll_hz=3.0, buffer_seconds=15.0, rssi_reader=None, clock=time.time):
        self.poll_hz = poll_hz
        self.poll_interval = 1.0 / poll_hz
        self.rssi_reader = rssi_reader or _read_rssi_via_corewlan
        self.clock = clock
        maxlen = max(1, int(poll_hz * buffer_seconds))
        self._buffer = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()

    def poll_once(self):
        rssi = self.rssi_reader()
        if rssi is None:
            return None
        sample = (self.clock(), rssi)
        with self._lock:
            self._buffer.append(sample)
        return sample

    def snapshot(self):
        with self._lock:
            return list(self._buffer)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                pass  # a single failed read shouldn't kill the poll loop
            self._stop_event.wait(self.poll_interval)

    def start(self):
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_collector.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Manual hardware check (not part of automated suite — confirms the real CoreWLAN reader works end-to-end)**

```bash
.venv/bin/python3 -c "
import time
from collector import MacWifiCollector

c = MacWifiCollector(poll_hz=3.0, buffer_seconds=5.0)
c.start()
time.sleep(3)
print(c.snapshot())
c.stop()
"
```

Expected: a list of several `(timestamp, rssi)` tuples with real dBm values (e.g. around `-61`).

- [ ] **Step 6: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/collector.py wifi-rssi-detector/tests/test_collector.py
git commit -m "$(cat <<'EOF'
Add MacWifiCollector: threaded CoreWLAN RSSI polling into a bounded buffer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Tick payload + WebSocket server (`server.py`)

**Files:**
- Create: `wifi-rssi-detector/server.py`
- Test: `wifi-rssi-detector/tests/test_server.py`

**Interfaces:**
- Consumes: `extract_features` and `sliding_window_features` from `features.py` (Task 2); `BaselineClassifier` from `classifier.py` (Task 3); `MacWifiCollector` from `collector.py` (Task 4).
- Produces:
  - `build_tick_payload(snapshot: list[tuple[float, float]], classifier: BaselineClassifier, window_seconds: float, clock: callable = time.time) -> dict` — returns `{"ts": float, "rssi": float | None, "variance": float, "motion_energy": float, "state": str}`. `rssi` is the last sample's value, or `None` if `snapshot` is empty.
  - `async def serve(host: str = "localhost", port: int = 8765, static_dir: str = "static", poll_hz: float = 3.0, window_seconds: float = 12.0)` — starts the collector, an `websockets` server broadcasting `build_tick_payload(...)` as JSON to all connected clients once per poll tick, and a tiny `http.server`-based static file server for `static/index.html` on `port + 1`. Runs until cancelled.
  - `if __name__ == "__main__":` entry point calling `asyncio.run(serve())`.

- [ ] **Step 1: Write failing tests for `build_tick_payload` (pure function, no asyncio/network needed)**

Write `wifi-rssi-detector/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'server'`.

- [ ] **Step 3: Implement `server.py`**

```python
"""Ticks the collector -> features -> classifier pipeline and broadcasts
the result over a local WebSocket server; also serves the static frontend."""

import asyncio
import functools
import http.server
import json
import threading
import time

import websockets

from classifier import BaselineClassifier
from collector import MacWifiCollector
from features import extract_features


def build_tick_payload(snapshot, classifier, window_seconds, clock=time.time):
    features = extract_features(snapshot, window_seconds=window_seconds)
    state = classifier.classify(features["variance"], features["motion_energy"])
    latest_rssi = snapshot[-1][1] if snapshot else None
    return {
        "ts": clock(),
        "rssi": latest_rssi,
        "variance": features["variance"],
        "motion_energy": features["motion_energy"],
        "state": state,
    }


def _serve_static_dir(static_dir, port):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=static_dir)
    httpd = http.server.ThreadingHTTPServer(("localhost", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


async def serve(host="localhost", port=8765, static_dir="static", poll_hz=3.0, window_seconds=12.0):
    collector = MacWifiCollector(poll_hz=poll_hz, buffer_seconds=window_seconds + 3.0)
    classifier = BaselineClassifier()
    collector.start()

    connections = set()

    async def handler(websocket):
        connections.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            connections.discard(websocket)

    async def broadcast_loop():
        poll_interval = 1.0 / poll_hz
        while True:
            payload = build_tick_payload(collector.snapshot(), classifier, window_seconds=window_seconds)
            message = json.dumps(payload)
            for ws in list(connections):
                try:
                    await ws.send(message)
                except websockets.exceptions.ConnectionClosed:
                    connections.discard(ws)
            await asyncio.sleep(poll_interval)

    static_httpd = _serve_static_dir(static_dir, port + 1)
    print(f"WebSocket server on ws://{host}:{port}")
    print(f"Static frontend on http://{host}:{port + 1}/index.html")

    try:
        async with websockets.serve(handler, host, port):
            await broadcast_loop()
    finally:
        collector.stop()
        static_httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(serve())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_server.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/server.py wifi-rssi-detector/tests/test_server.py
git commit -m "$(cat <<'EOF'
Add tick payload builder and asyncio WebSocket + static file server

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Frontend (`static/index.html`)

**Files:**
- Create: `wifi-rssi-detector/static/index.html`

**Interfaces:**
- Consumes: the JSON payload shape produced by `build_tick_payload` in Task 5 (`{ts, rssi, variance, motion_energy, state}`), delivered over `ws://localhost:8765`.

- [ ] **Step 1: Write the single-file frontend**

Write `wifi-rssi-detector/static/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WiFi RSSI Presence</title>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    background: #111;
    color: #eee;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem;
  }
  #badge {
    font-size: 2.5rem;
    font-weight: 700;
    padding: 1.5rem 3rem;
    border-radius: 1rem;
    margin-bottom: 1.5rem;
    transition: background-color 0.3s ease;
  }
  #badge.absent { background: #2d3748; color: #a0aec0; }
  #badge.present-still { background: #975a16; color: #fefcbf; }
  #badge.active { background: #9b2c2c; color: #fed7d7; }
  #meta { font-size: 0.9rem; color: #999; margin-bottom: 1rem; }
  canvas { background: #1a1a1a; border-radius: 0.5rem; }
</style>
</head>
<body>
  <div id="badge" class="absent">CONNECTING…</div>
  <div id="meta">rssi: -- dBm | variance: -- | motion: --</div>
  <canvas id="sparkline" width="600" height="150"></canvas>

<script>
  const badge = document.getElementById("badge");
  const meta = document.getElementById("meta");
  const canvas = document.getElementById("sparkline");
  const ctx = canvas.getContext("2d");
  const MAX_POINTS = 60;
  const rssiHistory = [];

  const STATE_LABEL = {
    "absent": "ABSENT",
    "present-still": "PRESENT",
    "active": "MOTION",
  };

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (rssiHistory.length < 2) return;

    const min = Math.min(...rssiHistory);
    const max = Math.max(...rssiHistory);
    const range = Math.max(max - min, 1);

    ctx.strokeStyle = "#63b3ed";
    ctx.lineWidth = 2;
    ctx.beginPath();
    rssiHistory.forEach((rssi, i) => {
      const x = (i / (MAX_POINTS - 1)) * canvas.width;
      const y = canvas.height - ((rssi - min) / range) * canvas.height;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function connect() {
    const ws = new WebSocket(`ws://${location.hostname}:8765`);

    ws.onopen = () => {
      badge.textContent = "ABSENT";
      badge.className = "absent";
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const label = STATE_LABEL[data.state] || data.state;
      badge.textContent = label;
      badge.className = data.state;
      meta.textContent = `rssi: ${data.rssi ?? "--"} dBm | variance: ${data.variance.toFixed(2)} | motion: ${data.motion_energy.toFixed(2)}`;

      if (data.rssi !== null) {
        rssiHistory.push(data.rssi);
        if (rssiHistory.length > MAX_POINTS) rssiHistory.shift();
        draw();
      }
    };

    ws.onclose = () => {
      badge.textContent = "DISCONNECTED";
      badge.className = "absent";
      setTimeout(connect, 2000);
    };
  }

  connect();
</script>
</body>
</html>
```

- [ ] **Step 2: Manual verification**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector
.venv/bin/python3 server.py
```

In a browser, open `http://localhost:8766/index.html`. Expected: badge shows ABSENT shortly after load, updates live, sparkline draws recent RSSI. Walk between the laptop and the router — expected: badge transitions toward PRESENT/MOTION and back. (This is the qualitative check; Task 7's calibration is what actually picks the thresholds that make this transition correctly.)

- [ ] **Step 3: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/static/index.html
git commit -m "$(cat <<'EOF'
Add dependency-free frontend: status badge and RSSI sparkline

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Calibration CLI (`calibrate.py`)

**Files:**
- Create: `wifi-rssi-detector/calibrate.py`
- Test: `wifi-rssi-detector/tests/test_calibrate.py`

**Interfaces:**
- Consumes: `MacWifiCollector` (Task 4), `sliding_window_features` (Task 2).
- Produces:
  - `capture(seconds: float, label: str, poll_hz: float = 3.0) -> dict` — runs a `MacWifiCollector` for `seconds` seconds using the real reader, returns `{"label": label, "samples": [[ts, rssi], ...]}`.
  - `summarize(samples: list[tuple[float, float]], window_seconds: float = 12.0) -> dict` — runs `sliding_window_features` over `samples` and returns `{"variance": {"min": .., "mean": .., "max": ..}, "motion_energy": {"min": .., "mean": .., "max": ..}}`.
  - `suggest_thresholds(still_summary: dict, walk_summary: dict) -> dict` — returns `{"present_variance_ratio": float, "active_motion_ratio": float}` as the midpoint between the still and walk `mean` values for each metric (a simple, explainable separator — not a statistical classifier).
  - CLI via `argparse` with subcommands `capture` (`--label`, `--seconds`, `--out`) and `compare` (two positional file paths).

- [ ] **Step 1: Write failing tests for the pure summarize/suggest logic (capture itself needs real hardware, so it's excluded from the automated suite and covered by Step 5's manual check)**

Write `wifi-rssi-detector/tests/test_calibrate.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_calibrate.py -v
```

Expected: `ModuleNotFoundError: No module named 'calibrate'`.

- [ ] **Step 3: Implement `calibrate.py`**

```python
"""Labeled RSSI capture and still-vs-walk comparison, so classifier
thresholds come from data instead of a guess."""

import argparse
import json
import time

from collector import MacWifiCollector
from features import sliding_window_features


def capture(seconds, label, poll_hz=3.0):
    collector = MacWifiCollector(poll_hz=poll_hz, buffer_seconds=seconds + 5.0)
    collector.start()
    time.sleep(seconds)
    collector.stop()
    samples = collector.snapshot()
    return {"label": label, "samples": [[ts, rssi] for ts, rssi in samples]}


def summarize(samples, window_seconds=12.0):
    windows = sliding_window_features(samples, window_seconds=window_seconds, step_seconds=1.0)
    windows = [w for w in windows if w["n"] >= 2]

    def stats(key):
        values = [w[key] for w in windows]
        if not values:
            return {"min": 0.0, "mean": 0.0, "max": 0.0}
        return {"min": min(values), "mean": sum(values) / len(values), "max": max(values)}

    return {"variance": stats("variance"), "motion_energy": stats("motion_energy")}


def suggest_thresholds(still_summary, walk_summary):
    return {
        "present_variance_ratio": (still_summary["variance"]["mean"] + walk_summary["variance"]["mean"]) / 2,
        "active_motion_ratio": (still_summary["motion_energy"]["mean"] + walk_summary["motion_energy"]["mean"]) / 2,
    }


def _cmd_capture(args):
    result = capture(seconds=args.seconds, label=args.label, poll_hz=args.poll_hz)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Captured {len(result['samples'])} samples labeled '{args.label}' -> {args.out}")


def _cmd_compare(args):
    with open(args.still) as f:
        still = json.load(f)
    with open(args.walk) as f:
        walk = json.load(f)

    still_summary = summarize([tuple(s) for s in still["samples"]])
    walk_summary = summarize([tuple(s) for s in walk["samples"]])

    print("=== still ===")
    print(json.dumps(still_summary, indent=2))
    print("=== walk ===")
    print(json.dumps(walk_summary, indent=2))

    thresholds = suggest_thresholds(still_summary, walk_summary)
    print("=== suggested thresholds (paste into classifier.py) ===")
    print(json.dumps(thresholds, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Labeled RSSI calibration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--label", required=True)
    capture_parser.add_argument("--seconds", type=float, default=10.0)
    capture_parser.add_argument("--poll-hz", type=float, default=3.0)
    capture_parser.add_argument("--out", required=True)
    capture_parser.set_defaults(func=_cmd_capture)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("still")
    compare_parser.add_argument("walk")
    compare_parser.set_defaults(func=_cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

Note: the README's usage examples (`--label still --seconds 10 --out still.json`) map to `calibrate.py capture --label still --seconds 10 --out still.json` and `calibrate.py compare still.json walk.json` with this subcommand structure — update the README in Step 6 to match exactly.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_calibrate.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Manual end-to-end calibration (real hardware, the actual point of this tool)**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector
.venv/bin/python3 calibrate.py capture --label still --seconds 10 --out still.json
# now walk back and forth between the laptop and the router
.venv/bin/python3 calibrate.py capture --label walk --seconds 10 --out walk.json
.venv/bin/python3 calibrate.py compare still.json walk.json
```

Expected: printed `still` and `walk` summaries with visibly separated `mean` values (walk's variance/motion_energy means clearly higher than still's), and a suggested-thresholds block. If the distributions are *not* separated, that's a real finding — note it, and only then consider adding spectral banding (out of scope for this plan; flag for a follow-up spec).

- [ ] **Step 6: Update README with the exact subcommand syntax and paste in real threshold values from Step 5**

Edit `wifi-rssi-detector/README.md`, replacing the "Calibrate before trusting any threshold" section:

```markdown
## Calibrate before trusting any threshold

    .venv/bin/python3 calibrate.py capture --label still --seconds 10 --out still.json
    # now walk between the laptop and the router
    .venv/bin/python3 calibrate.py capture --label walk --seconds 10 --out walk.json
    .venv/bin/python3 calibrate.py compare still.json walk.json

Paste the printed suggested thresholds into `classifier.py`'s
`BaselineClassifier` defaults (`present_variance_ratio`, `active_motion_ratio`).
```

- [ ] **Step 7: Apply the calibrated thresholds to `classifier.py` defaults**

Edit `wifi-rssi-detector/classifier.py`, replacing the `present_variance_ratio=3.0, active_motion_ratio=4.0` placeholder defaults in `BaselineClassifier.__init__` with the real values printed by Step 5's `compare` command.

- [ ] **Step 8: Re-run the full test suite to confirm the threshold edit didn't break classifier tests**

```bash
.venv/bin/python3 -m pytest tests/ -v
```

Expected: all tests still PASS (the classifier tests pass explicit thresholds per-test, so they're unaffected by default changes; this just confirms nothing else broke).

- [ ] **Step 9: Commit**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git add wifi-rssi-detector/calibrate.py wifi-rssi-detector/tests/test_calibrate.py wifi-rssi-detector/README.md wifi-rssi-detector/classifier.py
git commit -m "$(cat <<'EOF'
Add calibration CLI and apply data-derived thresholds to the classifier

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Full end-to-end manual verification

**Files:** none (verification only).

**Interfaces:** none — this task exercises the fully wired system from Tasks 1–7.

- [ ] **Step 1: Run the full automated test suite one more time**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks/wifi-rssi-detector
.venv/bin/python3 -m pytest tests/ -v
```

Expected: all tests across `test_features.py`, `test_classifier.py`, `test_collector.py`, `test_server.py`, `test_calibrate.py` PASS.

- [ ] **Step 2: Start the server**

```bash
.venv/bin/python3 server.py
```

Expected console output: `WebSocket server on ws://localhost:8765` and `Static frontend on http://localhost:8766/index.html`.

- [ ] **Step 3: Open the frontend and confirm live state transitions**

Open `http://localhost:8766/index.html` in a browser. Stand still near the laptop for ~10s — expect ABSENT or PRESENT (not flickering to MOTION). Walk between the laptop and the router — expect the badge to transition to MOTION within a couple of seconds, and back down after you stop.

- [ ] **Step 4: Confirm no other part of the repo was touched**

```bash
cd /Users/ericlee/Coding/Personal/VTHacks
git status
git diff --stat main -- . ':!wifi-rssi-detector' ':!docs/superpowers'
```

Expected: the second command shows no output — nothing outside `wifi-rssi-detector/` and the spec/plan docs changed.

- [ ] **Step 5: Final commit if any cleanup was needed**

If Step 3 or 4 surfaced fixes, commit them following the same pattern as prior tasks. Otherwise, no commit needed — this task is verification-only.

---

## Self-Review Notes

- **Spec coverage:** collector (Task 4), feature extractor (Task 2), classifier (Task 3), WebSocket server (Task 5), frontend (Task 6), calibration workflow (Task 7) — all six spec components have a task. Ratio-based-not-absolute threshold requirement is enforced by `classifier.py`'s design and re-checked in Task 7 Step 7. "Don't guess at a threshold" requirement is enforced by Task 7's capture→compare→apply flow.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code or exact commands.
- **Type consistency:** `extract_features` return shape (`variance`/`motion_energy`/`n`) is consistent across `features.py`, `server.py`'s `build_tick_payload`, and `calibrate.py`'s `summarize`. `BaselineClassifier.classify(variance, motion_energy) -> str` signature is consistent across Tasks 3, 5. Sample shape `(timestamp, rssi)` / `[ts, rssi]` (JSON) is consistent across `collector.py`, `features.py`, `calibrate.py`.
