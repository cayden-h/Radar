# Hawk Eye Vision: Phase A, the camera path Implementation Plan

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone camera path for `vision/`: live Logitech Brio 101 capture, automatic three-state lighting detection, measured multi-person tracking with stable identities, and hash-chained segment recording, runnable as one script with no agents, no network and no Gemini.

**Architecture:** A new `vision/` Python package (`hawkeye_vision`) kept separate from `agents/` so that torch and ultralytics never enter the agents test suite. Every hardware-facing thing sits behind a Protocol with a stub implementation, following the `ShutterBackend` / `StubShutter` pattern already established in `agents/agents/shutter/backend.py`. The camera device is opened exactly once and frames fan out to the tracker, the recorder, and later the Gemini sampler.

**Tech Stack:** Python 3.13, OpenCV 4.12, ultralytics 8.3.222 (YOLO11m + BoT-SORT with ReID), PyTorch 2.9 on MPS, ffmpeg 9.0.1, pydantic 2, pytest 8.

**Source spec:** `docs/superpowers/specs/2026-09-19-vision-tracking-design.md`

**Out of scope for this plan:** the shutter attestation gate, Gemini Live narration, claim emission, and `master` wiring are Phase B. The client-side low-light enhancement and the iOS/web track overlay are Phase C. Each gets its own plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `vision/pyproject.toml` | Package metadata, CV dependencies, pytest config |
| `vision/hawkeye_vision/__init__.py` | Package marker, version |
| `vision/hawkeye_vision/config.py` | `VisionConfig`: every tuneable threshold, so none are constants |
| `vision/hawkeye_vision/frames.py` | `Frame` dataclass, `FrameSource` Protocol |
| `vision/hawkeye_vision/fixture.py` | `FileFixture`: an mp4 as a frame source, for tests and the venue fallback |
| `vision/hawkeye_vision/webcam.py` | `MacCamera`: the live Brio 101 over AVFoundation |
| `vision/hawkeye_vision/lighting.py` | `mean_luminance`, `LightingMode`, `LightingClassifier` with hysteresis and dwell |
| `vision/hawkeye_vision/profiles.py` | `CaptureProfile` per lighting mode |
| `vision/hawkeye_vision/enhance.py` | Greyscale plus CLAHE, applied before detection in low light only |
| `vision/hawkeye_vision/track.py` | `Track`, `Tracker` Protocol, `StubTracker`, `TrackBook` |
| `vision/hawkeye_vision/yolo_tracker.py` | `YoloBotSortTracker`, the real detector, lazily imported |
| `vision/hawkeye_vision/botsort_reid.yaml` | BoT-SORT config with ReID on and motion compensation off |
| `vision/hawkeye_vision/record.py` | `SegmentWriter`: rotating mp4 segments with per-segment SHA-256 |
| `vision/hawkeye_vision/__main__.py` | The live preview: window, boxes, track IDs, lighting readout |
| `vision/tests/conftest.py` | Synthetic mp4 fixture factory, no committed binaries |
| `vision/tests/test_frames.py` | Frame source contract |
| `vision/tests/test_lighting.py` | Luminance and the hysteresis that stops flapping |
| `vision/tests/test_enhance.py` | Detection input transform |
| `vision/tests/test_track.py` | Track bookkeeping against `StubTracker` |
| `vision/tests/test_yolo.py` | Real YOLO against real footage, marked `integration` |
| `vision/tests/test_record.py` | Segment rotation and hashing |
| `app/backend/hawkeye_backend/models/common.py` | Modified: three new camera `Source` values |
| `app/backend/tests/test_models.py` | Created: the classification map had no direct test |

Files that change together live together. The hardware seams (`fixture.py`, `webcam.py`, `yolo_tracker.py`) are separate from the logic they feed (`lighting.py`, `track.py`), so every piece of logic is testable with no camera and no model weights.

---

## Task 1: Scaffold the vision package

**Files:**
- Create: `vision/pyproject.toml`
- Create: `vision/hawkeye_vision/__init__.py`
- Create: `vision/tests/__init__.py`
- Test: `vision/tests/test_package.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_package.py`:

```python
"""The package imports and declares a version. The cheapest possible smoke test."""

import hawkeye_vision


def test_package_declares_a_version():
    assert hawkeye_vision.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_package.py -v`
Expected: FAIL, collection error, `ModuleNotFoundError: No module named 'hawkeye_vision'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/__init__.py`:

```python
"""The camera path. Capture, lighting, tracking and recording.

Deliberately a separate package from `agents/`. It pulls in torch, ultralytics
and OpenCV, and the agents test suite must stay fast and must stay runnable on a
machine with no model weights. `agents/agents/vision/` imports from here; the
dependency points one way and never back.
"""

__version__ = "0.1.0"
```

Create `vision/tests/__init__.py` as an empty file.

Create `vision/pyproject.toml`:

```toml
[project]
name = "hawkeye-vision"
version = "0.1.0"
description = "The camera path: capture, lighting, tracking, recording."
requires-python = ">=3.13"
dependencies = [
    "numpy>=2.0",
    "opencv-python>=4.10",
    "pydantic>=2.9",
]

# The detector is optional on purpose. `hawkeye_vision.track` and everything
# that consumes it run against `StubTracker` with no torch installed, which is
# what keeps the test suite fast and what lets CI run with no model weights.
# Only `yolo_tracker.py` needs these, and it imports them lazily.
[project.optional-dependencies]
detect = ["ultralytics>=8.3.200", "torch>=2.6"]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "integration: needs real model weights or real hardware. Deselect with -m 'not integration'.",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["hawkeye_vision"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd vision && python3 -m pytest tests/test_package.py -v`
Expected: PASS, 1 passed

- [ ] **Step 5: Commit**

```bash
git add vision/pyproject.toml vision/hawkeye_vision/__init__.py vision/tests/__init__.py vision/tests/test_package.py
git commit -m "Scaffold the vision package, with the detector as an optional extra"
```

---

## Task 2: Teach the honesty rule about cameras

`Source` in `app/backend/hawkeye_backend/models/common.py` is a closed enum and currently has no camera values. Adding them is a deliberate act, and each new value must be placed into the classification map. This is the enforcement point that stops a fixture mp4 presenting as a live camera.

**Files:**
- Modify: `app/backend/hawkeye_backend/models/common.py`
- Test: `app/backend/tests/test_models.py` (CREATE: it does not exist, and nothing currently tests `classify_source`)

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_models.py`. The honesty rule's classification map has no direct test today, so this file starts with one:

```python
def test_camera_sources_classify_by_how_much_weight_they_bear():
    """A fixture mp4 must not be presentable as the live Brio."""
    from hawkeye_backend.models.common import Source, SourceClass, classify_source

    assert classify_source(Source.CAMERA_UVC) is SourceClass.MEASURED_LIVE
    assert classify_source(Source.REPLAY_VIDEO) is SourceClass.MEASURED_REPLAY
    assert classify_source(Source.CAMERA_SIM) is SourceClass.SIMULATED


def test_synthetic_video_is_flagged_simulated_and_live_camera_is_not():
    from hawkeye_backend.models.common import Provenance, Source

    synthetic = Provenance(source=Source.CAMERA_SIM, producer="vision/fixture")
    live = Provenance(source=Source.CAMERA_UVC, producer="vision/webcam")

    assert synthetic.simulated is True
    assert live.simulated is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app/backend && python3 -m pytest tests/test_models.py -k camera -v`
Expected: FAIL with `AttributeError: CAMERA_UVC`

- [ ] **Step 3: Write minimal implementation**

In `app/backend/hawkeye_backend/models/common.py`, inside `class Source(StrEnum)`, after the `SERVO_STUB` member, add:

```python
    # The Logitech Brio 101 on USB, frames read live off the device. MEASURED_LIVE
    # because a person is in front of a lens and the sensor recorded them.
    CAMERA_UVC = "camera-uvc"
    # Real footage, captured at the house earlier, replayed through the same
    # pipeline. Mirrors REPLAY_CSI exactly: measured, but not live. The venue
    # fallback runs on this when the camera cannot be set up in the room.
    REPLAY_VIDEO = "replay-video"
    # A synthetic video fixture: flat colour fields, luminance ramps, generated
    # test footage. Not measured, and named separately so a test rig cannot
    # present as a camera.
    CAMERA_SIM = "camera-sim"
```

In the `_SOURCE_CLASS` dict, add:

```python
    Source.CAMERA_UVC: SourceClass.MEASURED_LIVE,
    Source.REPLAY_VIDEO: SourceClass.MEASURED_REPLAY,
    Source.CAMERA_SIM: SourceClass.SIMULATED,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app/backend && python3 -m pytest tests/ -q`
Expected: PASS, the whole backend suite green. If any test asserts on the number of `Source` members or iterates the enum exhaustively, update it to include the three new values rather than weakening the assertion.

- [ ] **Step 5: Commit**

```bash
git add app/backend/hawkeye_backend/models/common.py app/backend/tests/test_models.py
git commit -m "Add the three camera sources, so a fixture cannot present as the Brio"
```

---

## Task 3: The frame source seam

**Files:**
- Create: `vision/hawkeye_vision/frames.py`
- Create: `vision/hawkeye_vision/fixture.py`
- Create: `vision/tests/conftest.py`
- Test: `vision/tests/test_frames.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/conftest.py`:

```python
"""Synthetic video fixtures, generated at test time.

No mp4s are committed. A fixture that lives in git drifts from the code that
reads it and nobody notices, and a binary in a diff is unreviewable.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest


def _write_mp4(path, frames, fps: int = 15) -> str:
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened(), f"OpenCV could not open a writer for {path}"
    for frame in frames:
        writer.write(frame)
    writer.release()
    return str(path)


def _flat(value: int, count: int, size=(120, 160)) -> list[np.ndarray]:
    """`count` frames of a single grey level. BGR, so all three channels equal."""
    return [np.full((size[0], size[1], 3), value, dtype=np.uint8) for _ in range(count)]


@pytest.fixture
def bright_mp4(tmp_path) -> str:
    """A well-lit room, as far as the luminance guard is concerned."""
    return _write_mp4(tmp_path / "bright.mp4", _flat(200, 30))


@pytest.fixture
def dark_mp4(tmp_path) -> str:
    """Below any usable threshold. The shield-still-covering-the-lens case."""
    return _write_mp4(tmp_path / "dark.mp4", _flat(5, 30))


@pytest.fixture
def ramp_mp4(tmp_path) -> str:
    """Luminance falling smoothly from bright to black, then back up.

    This is the fixture the hysteresis test needs: a naive classifier changes
    state many times crossing the boundary, and a correct one does not.
    """
    down = [f for value in range(200, 0, -4) for f in _flat(value, 1)]
    up = [f for value in range(0, 200, 4) for f in _flat(value, 1)]
    return _write_mp4(tmp_path / "ramp.mp4", down + up)
```

Create `vision/tests/test_frames.py`:

```python
"""The frame source contract, proved against the fixture implementation."""

from datetime import datetime

from hawkeye_backend.models.common import Source
from hawkeye_vision.fixture import FileFixture


def test_fixture_yields_every_frame_in_the_file(bright_mp4):
    with FileFixture(bright_mp4) as source:
        frames = list(source.frames())

    assert len(frames) == 30


def test_frames_carry_a_monotonic_index_and_a_utc_timestamp(bright_mp4):
    with FileFixture(bright_mp4) as source:
        frames = list(source.frames())

    assert [f.index for f in frames] == list(range(30))
    assert all(isinstance(f.captured_at, datetime) for f in frames)
    assert all(f.captured_at.tzinfo is not None for f in frames)


def test_a_synthetic_fixture_declares_itself_simulated(bright_mp4):
    """The honesty rule, at the seam where it is cheapest to enforce."""
    with FileFixture(bright_mp4) as source:
        assert source.source is Source.CAMERA_SIM


def test_real_footage_replayed_declares_itself_measured_replay(bright_mp4):
    with FileFixture(bright_mp4, source=Source.REPLAY_VIDEO) as source:
        assert source.source is Source.REPLAY_VIDEO


def test_frames_are_bgr_images_with_three_channels(bright_mp4):
    with FileFixture(bright_mp4) as source:
        first = next(source.frames())

    assert first.image.ndim == 3
    assert first.image.shape[2] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_frames.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.fixture'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/frames.py`:

```python
"""One frame, and the interface anything that produces frames must satisfy.

The seam `docs/swapping-in-real-parts.md` asks every simulated thing to have.
`FileFixture` is what the tests and the venue fallback run on, `MacCamera` is
the Brio on this laptop, and a `PiV4L2` will be the Brio on the Pi. Nothing
downstream knows which one it has.

`source` is part of the interface rather than a detail of each implementation,
for the same reason `ShutterBackend.source` is: it is what stops a video file
presenting as a camera.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
from hawkeye_backend.models.common import Source


def utc_now() -> datetime:
    """Timezone-aware now. Every timestamp in this package is UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Frame:
    """One image off the camera, and when it was taken.

    `captured_at` is not decoration. A track overlay drawn on the client has to
    align to the video rather than drift against it, and a claim has to say
    which instant it describes.
    """

    image: np.ndarray
    index: int
    captured_at: datetime


class FrameSource(Protocol):
    """Something that produces frames and says what it is."""

    source: Source

    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source is exhausted or closed."""

    def close(self) -> None:
        """Release the device or file handle."""
```

Create `vision/hawkeye_vision/fixture.py`:

```python
"""An mp4 as a frame source.

Two jobs, and they are genuinely different. Every test in this package runs
against a synthetic fixture, which is `Source.CAMERA_SIM`. The venue fallback
replays real footage captured at the house, which is `Source.REPLAY_VIDEO` and
is measured-but-not-live. The caller says which, and the enum stops the two
being confused.
"""

from __future__ import annotations

from collections.abc import Iterator

import cv2
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now


class FileFixture(FrameSource):
    """Read a video file frame by frame, as fast as the consumer asks."""

    def __init__(self, path: str, *, source: Source = Source.CAMERA_SIM) -> None:
        self.source = source
        self._path = path
        self._capture = cv2.VideoCapture(path)
        if not self._capture.isOpened():
            raise FileNotFoundError(f"OpenCV could not open {path}")

    def frames(self) -> Iterator[Frame]:
        index = 0
        while True:
            ok, image = self._capture.read()
            if not ok:
                return
            yield Frame(image=image, index=index, captured_at=utc_now())
            index += 1

    def close(self) -> None:
        self._capture.release()

    def __enter__(self) -> "FileFixture":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_frames.py -v`
Expected: PASS, 5 passed

If `hawkeye_backend` is not importable, install it first: `pip install -e ../app/backend`

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/frames.py vision/hawkeye_vision/fixture.py vision/tests/conftest.py vision/tests/test_frames.py
git commit -m "Add the frame source seam and the mp4 fixture every test runs on"
```

---

## Task 4: Mean luminance and the three lighting states

**Files:**
- Create: `vision/hawkeye_vision/config.py`
- Create: `vision/hawkeye_vision/lighting.py`
- Test: `vision/tests/test_lighting.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_lighting.py`:

```python
"""Luminance measurement and the three states it maps onto."""

import numpy as np

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode, classify, mean_luminance


def _flat(value: int) -> np.ndarray:
    return np.full((120, 160, 3), value, dtype=np.uint8)


def test_mean_luminance_of_a_flat_field_is_that_value():
    assert mean_luminance(_flat(200)) == 200.0
    assert mean_luminance(_flat(0)) == 0.0


def test_mean_luminance_is_a_float_between_zero_and_255():
    value = mean_luminance(_flat(137))
    assert isinstance(value, float)
    assert 0.0 <= value <= 255.0


def test_a_bright_room_classifies_as_day():
    config = VisionConfig()
    assert classify(200.0, config) is LightingMode.DAY


def test_a_dim_room_classifies_as_low():
    config = VisionConfig()
    assert classify(50.0, config) is LightingMode.LOW


def test_a_black_frame_classifies_as_too_dark():
    """The shield-still-covering-the-lens case, and it must not be LOW."""
    config = VisionConfig()
    assert classify(5.0, config) is LightingMode.TOO_DARK


def test_thresholds_are_configurable_not_constants():
    """They must be calibrated at the venue, so they cannot be baked in."""
    strict = VisionConfig(day_threshold=220.0, dark_threshold=100.0)
    assert classify(200.0, strict) is LightingMode.LOW
    assert classify(50.0, strict) is LightingMode.TOO_DARK


def test_a_dark_video_classifies_as_too_dark_end_to_end(dark_mp4):
    """Straight off a file, the way the real pipeline sees it.

    This is the failure that looks like success: a working camera behind a
    shield that never moved produces exactly this, and the pipeline must call
    it too_dark rather than describe a dimly lit room.
    """
    from hawkeye_vision.fixture import FileFixture

    config = VisionConfig()
    with FileFixture(dark_mp4) as source:
        modes = [classify(mean_luminance(f.image), config) for f in source.frames()]

    assert set(modes) == {LightingMode.TOO_DARK}


def test_a_bright_video_classifies_as_day_end_to_end(bright_mp4):
    from hawkeye_vision.fixture import FileFixture

    config = VisionConfig()
    with FileFixture(bright_mp4) as source:
        modes = [classify(mean_luminance(f.image), config) for f in source.frames()]

    assert set(modes) == {LightingMode.DAY}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_lighting.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.config'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/config.py`:

```python
"""Every tuneable number in the camera path, in one place.

These are configuration rather than constants because they must be calibrated
at the location the demo runs in, and the value that works in one room is wrong
in another. A threshold hard-coded in a module is a threshold nobody can fix at
the venue at 2am.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionConfig(BaseModel):
    """Thresholds and rates for capture, lighting and tracking."""

    model_config = {"frozen": True}

    # --- lighting ---------------------------------------------------------
    day_threshold: float = Field(
        default=90.0,
        description="Mean luminance at or above this is DAY. Calibrate at the venue.",
    )
    dark_threshold: float = Field(
        default=25.0,
        description="Mean luminance below this is TOO_DARK: no detection, no narration.",
    )
    hysteresis: float = Field(
        default=8.0,
        description=(
            "Luminance a reading must move past a threshold by before the state is "
            "allowed to change back. Stops a value sitting on the boundary flapping."
        ),
    )
    dwell_frames: int = Field(
        default=45,
        description=(
            "Consecutive frames a candidate state must hold before it takes effect. "
            "At 15fps this is roughly three seconds, which is long enough that a "
            "passing shadow or a car headlight does not switch the pipeline."
        ),
    )

    # --- capture ----------------------------------------------------------
    day_fps: int = Field(default=15, description="Capture rate in good light.")
    low_fps: int = Field(default=8, description="Capture rate in low light, longer exposures.")
    detect_width: int = Field(default=640, description="Long edge fed to the detector.")

    # --- tracking ---------------------------------------------------------
    day_confidence: float = Field(default=0.35, description="Detection confidence floor in DAY.")
    low_confidence: float = Field(
        default=0.50,
        description=(
            "Higher floor in LOW. A noisy, gain-boosted frame produces confident "
            "nonsense, and a false person on a 911 call is worse than a missed one."
        ),
    )
    track_expiry_frames: int = Field(
        default=30,
        description="Frames a track survives unseen before it stops counting as present.",
    )
```

Create `vision/hawkeye_vision/lighting.py`:

```python
"""How much light is reaching the sensor, and what to do about it.

This is the honest replacement for the night vision that was asked for and
which the hardware cannot do. The Logitech Brio 101 has no IR sensor and no
illuminator is owned, so there is no infrared path. What there is, is a measured
low-light mode, and the state it computes travels in the claim as
`vision.lighting` rather than only in a comment.

`TOO_DARK` does double duty. `shutter` is open-loop and attests the angle it
commanded rather than the angle the shield reached, so a jammed shield attests
open. A jammed shield produces a black frame, and this module is what catches
it. That is why the dark case is its own state and not merely a dim one.
"""

from __future__ import annotations

from enum import StrEnum

import cv2
import numpy as np

from hawkeye_vision.config import VisionConfig


class LightingMode(StrEnum):
    """The three states the camera path runs in."""

    DAY = "day"
    LOW = "low"
    TOO_DARK = "too_dark"


def mean_luminance(image: np.ndarray) -> float:
    """Mean luma of a BGR frame, 0 to 255.

    Computed on a downscaled copy: the mean of a quarter-size image is the
    number we need and costs a fraction of the full-resolution read, and this
    runs on every frame.
    """
    small = cv2.resize(image, (0, 0), fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return float(grey.mean())


def classify(luminance: float, config: VisionConfig) -> LightingMode:
    """Map a luminance onto a state, with no memory.

    Stateless on purpose. `LightingClassifier` owns the memory, so this function
    stays trivially testable at every boundary value.
    """
    if luminance < config.dark_threshold:
        return LightingMode.TOO_DARK
    if luminance < config.day_threshold:
        return LightingMode.LOW
    return LightingMode.DAY
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_lighting.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/config.py vision/hawkeye_vision/lighting.py vision/tests/test_lighting.py
git commit -m "Measure mean luminance and classify it into three lighting states"
```

---

## Task 5: Hysteresis, so the pipeline does not flap mid-incident

**Files:**
- Modify: `vision/hawkeye_vision/lighting.py`
- Test: `vision/tests/test_lighting.py`

- [ ] **Step 1: Write the failing test**

Append to `vision/tests/test_lighting.py`:

```python
from hawkeye_vision.fixture import FileFixture
from hawkeye_vision.lighting import LightingClassifier


def test_classifier_starts_in_the_state_of_its_first_reading():
    classifier = LightingClassifier(VisionConfig())
    assert classifier.update(200.0) is LightingMode.DAY


def test_a_single_dark_frame_does_not_change_state():
    """One frame is a shadow. Three seconds of frames is nightfall."""
    config = VisionConfig(dwell_frames=45)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    assert classifier.update(5.0) is LightingMode.DAY


def test_state_changes_once_the_candidate_holds_for_the_dwell():
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    results = [classifier.update(5.0) for _ in range(6)]

    assert results[:4] == [LightingMode.DAY] * 4
    assert results[-1] is LightingMode.TOO_DARK


def test_an_interrupted_candidate_resets_the_dwell():
    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)
    classifier.update(200.0)

    classifier.update(5.0)
    classifier.update(5.0)
    classifier.update(200.0)  # back to bright: the candidate is abandoned
    results = [classifier.update(5.0) for _ in range(4)]

    assert results == [LightingMode.DAY] * 4


def test_a_value_sitting_on_the_boundary_does_not_flap(ramp_mp4):
    """The test that matters. A naive classifier changes state on every jitter."""
    from hawkeye_vision.lighting import mean_luminance

    config = VisionConfig(dwell_frames=5)
    classifier = LightingClassifier(config)

    states = []
    with FileFixture(ramp_mp4) as source:
        for frame in source.frames():
            states.append(classifier.update(mean_luminance(frame.image)))

    transitions = sum(1 for a, b in zip(states, states[1:]) if a is not b)

    # The ramp falls from bright to black and climbs back, crossing both
    # thresholds twice. Six transitions is the physical truth of that signal;
    # anything substantially more is the classifier flapping on the boundary.
    assert transitions <= 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_lighting.py -v`
Expected: FAIL, `ImportError: cannot import name 'LightingClassifier'`

- [ ] **Step 3: Write minimal implementation**

Append to `vision/hawkeye_vision/lighting.py`:

```python
class LightingClassifier:
    """Stateful lighting detection: hysteresis plus a dwell requirement.

    Two separate defences against the same failure, because they catch
    different things.

    Hysteresis handles a reading sitting exactly on a threshold, where sensor
    noise alone flips the classification every frame.

    The dwell handles a real but brief change: a shadow crossing the lens, a
    car's headlights sweeping the room, someone walking past a lamp. Those are
    genuine luminance changes and hysteresis will not stop them. Only time does.

    Both matter because the consequence is not cosmetic. A state change alters
    the capture profile and the detection confidence floor, and doing that
    repeatedly during an incident produces narration that contradicts itself on
    a live 911 call.
    """

    def __init__(self, config: VisionConfig) -> None:
        self._config = config
        self._current: LightingMode | None = None
        self._candidate: LightingMode | None = None
        self._held = 0

    @property
    def mode(self) -> LightingMode | None:
        """The state in effect, or None before the first reading."""
        return self._current

    def update(self, luminance: float) -> LightingMode:
        """Feed one luminance reading and get the state currently in effect."""
        if self._current is None:
            self._current = classify(luminance, self._config)
            return self._current

        proposed = self._classify_with_hysteresis(luminance)

        if proposed is self._current:
            self._candidate = None
            self._held = 0
            return self._current

        if proposed is self._candidate:
            self._held += 1
        else:
            self._candidate = proposed
            self._held = 1

        if self._held >= self._config.dwell_frames:
            self._current = proposed
            self._candidate = None
            self._held = 0

        return self._current

    def _classify_with_hysteresis(self, luminance: float) -> LightingMode:
        """Classify, but require the reading to clear the threshold it is leaving.

        Moving to a brighter state demands the luminance exceed the boundary by
        the hysteresis margin. Moving darker demands it fall below by the same
        margin. A reading inside the margin keeps the state it already has.
        """
        margin = self._config.hysteresis
        naive = classify(luminance, self._config)

        if naive is self._current:
            return naive

        brighter = _ORDER[naive] > _ORDER[self._current]
        boundary = self._boundary_between(self._current, naive)

        if brighter and luminance < boundary + margin:
            return self._current
        if not brighter and luminance > boundary - margin:
            return self._current
        return naive

    def _boundary_between(self, a: LightingMode, b: LightingMode) -> float:
        """The threshold separating two states. Equal to the darker one's ceiling."""
        darker = a if _ORDER[a] < _ORDER[b] else b
        if darker is LightingMode.TOO_DARK:
            return self._config.dark_threshold
        return self._config.day_threshold


#: Brightness ordering, so the classifier can ask which direction a change is in.
_ORDER: dict[LightingMode, int] = {
    LightingMode.TOO_DARK: 0,
    LightingMode.LOW: 1,
    LightingMode.DAY: 2,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_lighting.py -v`
Expected: PASS, 13 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/lighting.py vision/tests/test_lighting.py
git commit -m "Hold a lighting state through noise and shadows with hysteresis and dwell"
```

---

## Task 6: Capture profiles per lighting state

**Files:**
- Create: `vision/hawkeye_vision/profiles.py`
- Test: `vision/tests/test_profiles.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_profiles.py`:

```python
"""What the capture settings become in each lighting state."""

import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.profiles import CaptureProfile, for_mode


def test_day_runs_at_full_rate_in_colour_without_enhancement():
    profile = for_mode(LightingMode.DAY, VisionConfig())

    assert profile.fps == 15
    assert profile.enhance is False
    assert profile.detect is True


def test_low_drops_the_rate_and_enhances_before_detection():
    profile = for_mode(LightingMode.LOW, VisionConfig())

    assert profile.fps == 8
    assert profile.enhance is True
    assert profile.detect is True


def test_low_raises_the_confidence_floor():
    """A gain-boosted frame produces confident nonsense. Demand more of it."""
    day = for_mode(LightingMode.DAY, VisionConfig())
    low = for_mode(LightingMode.LOW, VisionConfig())

    assert low.confidence > day.confidence


def test_too_dark_does_not_detect_at_all():
    profile = for_mode(LightingMode.TOO_DARK, VisionConfig())

    assert profile.detect is False


def test_a_profile_cannot_be_mutated_after_it_is_chosen():
    profile = for_mode(LightingMode.DAY, VisionConfig())

    with pytest.raises(Exception):
        profile.fps = 60


def test_every_lighting_mode_has_a_profile():
    """A new mode with no profile must fail loudly, not silently pick a default."""
    for mode in LightingMode:
        assert isinstance(for_mode(mode, VisionConfig()), CaptureProfile)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_profiles.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.profiles'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/profiles.py`:

```python
"""What the pipeline does in each lighting state.

Kept as data rather than as branches scattered through the capture loop. A
profile is one object you can print, log into the record, and assert on, which
is what makes "the camera was in low-light mode at this moment" a checkable
fact rather than a claim about control flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode


@dataclass(frozen=True, slots=True)
class CaptureProfile:
    """The settings in force for one lighting state."""

    fps: int
    confidence: float
    enhance: bool
    detect: bool


def for_mode(mode: LightingMode, config: VisionConfig) -> CaptureProfile:
    """The profile for a lighting state.

    Exhaustive by construction: a new `LightingMode` with no branch here raises
    rather than silently inheriting someone else's settings.
    """
    match mode:
        case LightingMode.DAY:
            return CaptureProfile(
                fps=config.day_fps,
                confidence=config.day_confidence,
                enhance=False,
                detect=True,
            )
        case LightingMode.LOW:
            return CaptureProfile(
                fps=config.low_fps,
                confidence=config.low_confidence,
                enhance=True,
                detect=True,
            )
        case LightingMode.TOO_DARK:
            # Nothing usable is reaching the sensor. Detecting here produces a
            # description of a dark room, which is the failure that looks like
            # success and the one `vision/CLAUDE.md` calls out by name.
            return CaptureProfile(
                fps=config.low_fps,
                confidence=config.low_confidence,
                enhance=False,
                detect=False,
            )
    raise ValueError(f"No capture profile for lighting mode {mode!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_profiles.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/profiles.py vision/tests/test_profiles.py
git commit -m "Make the per-lighting-state capture settings data rather than branches"
```

---

## Task 7: The low-light detection input

This is the enhancement applied **before detection**, so the detector sees a usable image. It is a different thing from the client-side viewing enhancement in Phase C, and it never touches the recorded segments.

**Files:**
- Create: `vision/hawkeye_vision/enhance.py`
- Test: `vision/tests/test_enhance.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_enhance.py`:

```python
"""The transform applied to a frame before the detector sees it, in low light."""

import numpy as np

from hawkeye_vision.enhance import to_detection_input


def _noisy_dim(seed: int = 0) -> np.ndarray:
    """A dim frame with real structure in it, not a flat field."""
    rng = np.random.default_rng(seed)
    base = rng.integers(20, 70, size=(120, 160), dtype=np.uint8)
    return np.stack([base, base, base], axis=2)


def test_enhancement_returns_a_three_channel_image():
    """The detector wants BGR. Greyscale is stacked back to three channels."""
    result = to_detection_input(_noisy_dim(), enhance=True)

    assert result.shape == (120, 160, 3)
    assert result.dtype == np.uint8


def test_enhancement_widens_the_contrast_of_a_dim_frame():
    dim = _noisy_dim()
    result = to_detection_input(dim, enhance=True)

    assert result.std() > dim.std()


def test_enhancement_off_returns_the_frame_unchanged():
    dim = _noisy_dim()
    result = to_detection_input(dim, enhance=False)

    assert np.array_equal(result, dim)


def test_enhancement_does_not_mutate_the_frame_it_was_given():
    """The same frame goes to the recorder. Altering it in place alters evidence."""
    dim = _noisy_dim()
    before = dim.copy()

    to_detection_input(dim, enhance=True)

    assert np.array_equal(dim, before)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_enhance.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.enhance'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/enhance.py`:

```python
"""Making a dim frame legible to the detector.

Scope, because there are two enhancements in this system and confusing them
would be serious:

- **This one** runs before detection, on the Pi or the Mac, so YOLO has usable
  contrast in low light. It affects what is detected. It never touches the
  frame handed to the segment writer.
- **The client one** runs in the iOS app and the replay console, so a resident
  can see the room. It affects what a human sees and nothing else.

Neither one is ever applied to the recorded mp4. Those segments are hashed into
the chain and emailed to a police department, so brightening them is altering
evidence rather than adjusting a picture.
"""

from __future__ import annotations

import cv2
import numpy as np


def to_detection_input(image: np.ndarray, *, enhance: bool) -> np.ndarray:
    """Return the image the detector should run on.

    With `enhance` false this is the frame as captured, returned as-is.

    With `enhance` true the frame is converted to greyscale and put through
    CLAHE, which equalises contrast in local tiles rather than globally. That
    matters in a dark room, where a global stretch is dominated by one bright
    window or lamp and leaves the person in the corner as dark as they started.

    Greyscale rather than colour because colour in a gain-boosted low-light
    frame is mostly chroma noise, and the detector does better without it.

    Never mutates its argument. The same frame object goes to the recorder.
    """
    if not enhance:
        return image

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    equalised = clahe.apply(grey)
    return cv2.cvtColor(equalised, cv2.COLOR_GRAY2BGR)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_enhance.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/enhance.py vision/tests/test_enhance.py
git commit -m "Give the detector usable contrast in low light without touching the record"
```

---

## Task 8: Tracks, the tracker seam, and the stub

**Files:**
- Create: `vision/hawkeye_vision/track.py`
- Test: `vision/tests/test_track.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_track.py`:

```python
"""Track bookkeeping, proved with no model weights and no torch installed."""

import numpy as np
import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.track import BBox, StubTracker, Track, TrackBook


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


def test_a_track_exposes_the_fields_a_claim_needs():
    book = TrackBook(VisionConfig())
    tracker = StubTracker([[(7, BBox(x1=0.1, y1=0.2, x2=0.3, y2=0.9))]])
    book.ingest(tracker.update(_frame(0)), frame_index=0)

    track = book.active[0]

    assert isinstance(track, Track)
    assert track.track_id == 7
    assert track.bbox.x1 == 0.1
    assert track.confidence == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_track.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.track'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/track.py`:

```python
"""Who is in frame, and the bookkeeping that turns detections into a count.

The seam is the same one `shutter` uses for its GPIO pin. `Tracker` is a
Protocol, `StubTracker` is a first-class implementation that every test and the
whole mock demo path run against, and `YoloBotSortTracker` is the same interface
over real weights. Swapping them is a constructor argument.

Track identities are stable **within a session only**. That is not a limitation
we are apologising for, it is the same rule `Assertion.presence_id` already
states: we do not do re-identification across sessions and we have no database
to do it against. A track id says "the same person as a moment ago", never "this
particular person".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame


@dataclass(frozen=True, slots=True)
class BBox:
    """A box around a person, normalised to 0..1 of the frame.

    Normalised rather than in pixels because the consumer is a client drawing an
    overlay at whatever size its view happens to be, and because a claim that
    travels between agents should not carry this camera's resolution as a hidden
    assumption.
    """

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        for name in ("x1", "y1", "x2", "y2"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"BBox.{name} must be within 0..1, got {value}")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("BBox must have x2 > x1 and y2 > y1")


@dataclass(frozen=True, slots=True)
class Detection:
    """One person the tracker saw in one frame, with the identity it assigned."""

    track_id: int
    bbox: BBox
    confidence: float = 1.0


@dataclass(slots=True)
class Track:
    """One person, followed across frames."""

    track_id: int
    bbox: BBox
    confidence: float
    first_seen_frame: int
    last_seen_frame: int
    frames_held: int = field(default=1)


class Tracker(Protocol):
    """Something that finds people in a frame and keeps their identities."""

    def update(self, frame: Frame) -> Sequence[Detection]:
        """Detections for this frame, each carrying a stable identity."""


class StubTracker:
    """A tracker that replays a script. What the tests and the mock run on.

    A first-class implementation rather than a branch inside the real one, for
    the reason `StubShutter` is: the demo must never depend on hardware, or in
    this case on model weights and a working MPS backend, being alive.
    """

    def __init__(self, script: Sequence[Sequence[tuple[int, BBox]]]) -> None:
        self._script = list(script)
        self._calls = 0

    def update(self, frame: Frame) -> Sequence[Detection]:
        if self._calls >= len(self._script):
            return []
        entries = self._script[self._calls]
        self._calls += 1
        return [Detection(track_id=tid, bbox=box) for tid, box in entries]


class TrackBook:
    """Holds the tracks currently considered present.

    The detector loses people constantly: they turn side-on, they walk behind a
    sofa, the frame is noisy. BoT-SORT keeps a lost track alive in its buffer,
    and this mirrors that with an expiry, so a person who steps behind a doorway
    for half a second does not make `people_visible` drop to zero and back.

    A flickering count is not cosmetic here. It is the number a caller agent
    reads to a 911 operator.
    """

    def __init__(self, config: VisionConfig) -> None:
        self._config = config
        self._tracks: dict[int, Track] = {}
        self._last_frame = -1

    def ingest(self, detections: Sequence[Detection], *, frame_index: int) -> None:
        """Fold one frame's detections into the book."""
        self._last_frame = frame_index

        for detection in detections:
            existing = self._tracks.get(detection.track_id)
            if existing is None:
                self._tracks[detection.track_id] = Track(
                    track_id=detection.track_id,
                    bbox=detection.bbox,
                    confidence=detection.confidence,
                    first_seen_frame=frame_index,
                    last_seen_frame=frame_index,
                )
            else:
                existing.bbox = detection.bbox
                existing.confidence = detection.confidence
                existing.last_seen_frame = frame_index
                existing.frames_held += 1

        self._expire(frame_index)

    def _expire(self, frame_index: int) -> None:
        cutoff = self._config.track_expiry_frames
        self._tracks = {
            tid: track
            for tid, track in self._tracks.items()
            if frame_index - track.last_seen_frame <= cutoff
        }

    @property
    def active(self) -> list[Track]:
        """Tracks considered present, in the order they were first seen."""
        return sorted(self._tracks.values(), key=lambda t: t.first_seen_frame)

    @property
    def people_visible(self) -> int:
        """How many distinct people this camera can see in this room.

        A count of what is in frame, never a count of the building. When it is
        zero that is a fact about this room, and `master` must not turn it into
        an absence claim about the house.
        """
        return len(self._tracks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_track.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/track.py vision/tests/test_track.py
git commit -m "Track people across frames with a count that survives brief occlusion"
```

---

## Task 9: The real detector behind the same interface

**Files:**
- Create: `vision/hawkeye_vision/botsort_reid.yaml`
- Create: `vision/hawkeye_vision/yolo_tracker.py`
- Create: `vision/tests/test_yolo.py`
- Modify: `.gitignore`

- [ ] **Step 1: Pre-download the model weights**

The venue may have no usable network, and ultralytics downloads weights on first use. Fetch them now and keep them out of git.

Run:

```bash
cd vision && python -c "from ultralytics import YOLO; YOLO('yolo11m.pt')" && ls -la yolo11m.pt
```

Expected: `yolo11m.pt` present, roughly 40MB.

Append to `.gitignore` at the repo root:

```
# YOLO weights. Roughly 40MB, downloaded by `vision/` on first use and
# pre-fetched before the demo because the venue network cannot be relied on.
*.pt
```

- [ ] **Step 2: Write the tracker config**

Create `vision/hawkeye_vision/botsort_reid.yaml`:

```yaml
# BoT-SORT for Hawk Eye, with two deliberate changes from the ultralytics
# default at ultralytics/cfg/trackers/botsort.yaml.
#
# 1. with_reid is True. The default ships it off. ReID is what keeps a track
#    identity across an occlusion, which is what makes "the same person moved
#    into the hallway, still carrying the bag" a sentence we can support rather
#    than a guess. `model: auto` reuses the detector's own features, so this
#    costs no second network and no extra download.
#
# 2. gmc_method is none. The default is sparseOptFlow, which compensates for a
#    moving camera. Our camera is bolted in place facing the entry point, so
#    global motion compensation is estimating a transform that is always
#    identity, and paying optical flow on every frame to do it.

tracker_type: botsort
track_high_thresh: 0.25
track_low_thresh: 0.1
new_track_thresh: 0.25
track_buffer: 30
match_thresh: 0.8
fuse_score: True

gmc_method: none

proximity_thresh: 0.5
appearance_thresh: 0.8
with_reid: True
model: auto
```

- [ ] **Step 3: Write the failing test**

Create `vision/tests/test_yolo.py`:

```python
"""The real detector. Marked integration: needs weights and a working MPS path.

Run with:     python -m pytest tests/test_yolo.py -v -m integration
Skip with:    python -m pytest tests/ -m 'not integration'
"""

import numpy as np
import pytest

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.track import BBox, Detection

pytestmark = pytest.mark.integration


def _frame(image: np.ndarray, index: int = 0) -> Frame:
    return Frame(image=image, index=index, captured_at=utc_now())


def test_the_yolo_tracker_satisfies_the_tracker_protocol():
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    result = tracker.update(_frame(np.zeros((480, 640, 3), dtype=np.uint8)))

    assert isinstance(result, list)
    assert all(isinstance(d, Detection) for d in result)


def test_an_empty_frame_produces_no_detections_rather_than_raising():
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())

    assert tracker.update(_frame(np.zeros((480, 640, 3), dtype=np.uint8))) == []


def test_detections_come_back_normalised(person_mp4):
    """Pixel coordinates leaking out of here would break every client overlay."""
    from hawkeye_vision.fixture import FileFixture
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    seen: list[Detection] = []

    with FileFixture(person_mp4) as source:
        for frame in source.frames():
            seen.extend(tracker.update(frame))

    assert seen, "expected at least one person detected in the recorded fixture"
    for detection in seen:
        assert isinstance(detection.bbox, BBox)


def test_track_identity_survives_a_crossing_occlusion(person_mp4):
    """The reason ReID is on. Two people crossing must not swap or multiply ids."""
    from hawkeye_vision.fixture import FileFixture
    from hawkeye_vision.yolo_tracker import YoloBotSortTracker

    tracker = YoloBotSortTracker(VisionConfig())
    ids: set[int] = set()

    with FileFixture(person_mp4) as source:
        for frame in source.frames():
            ids.update(d.track_id for d in tracker.update(frame))

    # Record the fixture with a known number of people and set this to match.
    # A count far above it means identities are being dropped and reissued.
    assert len(ids) <= 4
```

Add the recorded-footage fixture to `vision/tests/conftest.py`:

```python
import os


@pytest.fixture
def person_mp4() -> str:
    """Real footage of people, recorded from the Brio.

    Synthetic rectangles are not people and YOLO will not detect them, so this
    one fixture cannot be generated. Record it once with:

        python -m hawkeye_vision.record_fixture tests/footage/person.mp4

    and keep it out of git. It is the only test that needs it, and that test is
    marked integration for exactly this reason.
    """
    path = os.path.join(os.path.dirname(__file__), "footage", "person.mp4")
    if not os.path.exists(path):
        pytest.skip(f"recorded fixture missing: {path}")
    return path
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_yolo.py -v -m integration`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.yolo_tracker'`

- [ ] **Step 5: Write minimal implementation**

Create `vision/hawkeye_vision/yolo_tracker.py`:

```python
"""YOLO11 plus BoT-SORT, behind the `Tracker` interface.

`ultralytics` and `torch` are imported inside `__init__` rather than at module
scope on purpose. Importing torch costs seconds and a large amount of memory,
and nothing else in this package needs it. Every other module, every unit test
and the whole mock demo path run without it ever being imported.

Detection is restricted to COCO class 0, person. We are not building a general
object detector; we are answering "is there a person in this room", and every
other class is latency spent on an answer nobody asked for.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.frames import Frame
from hawkeye_vision.track import BBox, Detection

logger = logging.getLogger(__name__)

#: COCO class index for "person".
PERSON_CLASS = 0

#: Our BoT-SORT config: ReID on, global motion compensation off. See the yaml.
TRACKER_CONFIG = os.path.join(os.path.dirname(__file__), "botsort_reid.yaml")


class TrackerUnavailable(RuntimeError):
    """The detector could not be brought up.

    Raised at construction and never during a frame. Callers degrade to
    `Unknown(reason="tracker_unavailable")` and keep narrating and recording,
    because the tracker is a corroborating view and not a gate.
    """


class YoloBotSortTracker:
    """The real detector and tracker. Same interface as `StubTracker`."""

    def __init__(self, config: VisionConfig, *, weights: str = "yolo11m.pt") -> None:
        self._config = config
        self._confidence = config.day_confidence
        try:
            from ultralytics import YOLO
            import torch
        except ImportError as exc:  # pragma: no cover - exercised by Task 10
            raise TrackerUnavailable(f"ultralytics or torch not installed: {exc}") from exc

        self._device = "mps" if torch.backends.mps.is_available() else "cpu"
        if self._device == "cpu":
            logger.warning(
                "MPS unavailable, running YOLO on CPU. Expect roughly 2fps; "
                "the claim rate is 1fps so this still works, but the preview will crawl."
            )
        try:
            self._model = YOLO(weights)
        except Exception as exc:  # pragma: no cover - exercised by Task 10
            raise TrackerUnavailable(f"could not load weights {weights!r}: {exc}") from exc

    def set_confidence(self, confidence: float) -> None:
        """Raise or lower the detection floor when the lighting profile changes."""
        self._confidence = confidence

    def update(self, frame: Frame) -> list[Detection]:
        """Detections for this frame, normalised, person class only."""
        results = self._model.track(
            frame.image,
            persist=True,
            tracker=TRACKER_CONFIG,
            classes=[PERSON_CLASS],
            conf=self._confidence,
            imgsz=self._config.detect_width,
            device=self._device,
            verbose=False,
        )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            # No tracks this frame. Normal: an empty room, or detections below
            # the confidence floor. Not an error.
            return []

        detections: list[Detection] = []
        for xyxyn, track_id, confidence in zip(
            boxes.xyxyn.tolist(), boxes.id.tolist(), boxes.conf.tolist()
        ):
            x1, y1, x2, y2 = xyxyn
            detections.append(
                Detection(
                    track_id=int(track_id),
                    bbox=BBox(
                        x1=max(0.0, min(1.0, x1)),
                        y1=max(0.0, min(1.0, y1)),
                        x2=max(0.0, min(1.0, x2)),
                        y2=max(0.0, min(1.0, y2)),
                    ),
                    confidence=float(confidence),
                )
            )
        return detections
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_yolo.py -v -m integration`
Expected: PASS for the first two tests. The two needing `person_mp4` SKIP until the fixture is recorded in Task 12.

Run the fast suite too: `cd vision && python3 -m pytest tests/ -m 'not integration' -q`
Expected: PASS, all previous tests still green.

- [ ] **Step 7: Commit**

```bash
git add vision/hawkeye_vision/yolo_tracker.py vision/hawkeye_vision/botsort_reid.yaml vision/tests/test_yolo.py vision/tests/conftest.py .gitignore
git commit -m "Add YOLO11m with BoT-SORT ReID behind the tracker interface"
```

---

## Task 10: Degrade when the detector cannot come up

**Files:**
- Modify: `vision/hawkeye_vision/track.py`
- Test: `vision/tests/test_track.py`

- [ ] **Step 1: Write the failing test**

Append to `vision/tests/test_track.py`:

```python
def test_a_failed_detector_yields_a_tracker_that_finds_nothing_rather_than_raising():
    """The tracker is a corroborating view, not a gate.

    A missing weights file or an unavailable MPS backend must cost the measured
    count and nothing else. Narration and recording keep running, because the
    footage is the thing worth having when everything else fails.
    """
    from hawkeye_vision.track import UnavailableTracker

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
```

Add the import at the top of the test file:

```python
from hawkeye_vision.track import UnavailableTracker
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_track.py -v`
Expected: FAIL, `ImportError: cannot import name 'UnavailableTracker'`

- [ ] **Step 3: Write minimal implementation**

In `vision/hawkeye_vision/track.py`, add `available` and `reason` to the `Tracker` Protocol:

```python
class Tracker(Protocol):
    """Something that finds people in a frame and keeps their identities."""

    #: False when this tracker cannot actually detect anything. Consumers read
    #: it to decide between a measured count and `tracker_unavailable`.
    available: bool

    #: Why it is unavailable, or None. Carried into the claim, because "I could
    #: not look" and "I looked and saw nobody" are different facts.
    reason: str | None

    def update(self, frame: Frame) -> Sequence[Detection]:
        """Detections for this frame, each carrying a stable identity."""
```

Add to `StubTracker.__init__`:

```python
        self.available = True
        self.reason = None
```

Append the new class:

```python
class UnavailableTracker:
    """What you get when the detector could not be brought up.

    Deliberately not an exception at the call site. A camera path that crashes
    because a model failed to load loses the recording too, and the recording is
    the artifact that goes to the police. This degrades instead: the measured
    count becomes unavailable and stays honest about why, and every other path
    carries on.
    """

    available = False

    def __init__(self, *, reason: str) -> None:
        self.reason = reason

    def update(self, frame: Frame) -> Sequence[Detection]:
        return []
```

Add to `YoloBotSortTracker.__init__` in `vision/hawkeye_vision/yolo_tracker.py`, as the first lines of the body:

```python
        self.available = True
        self.reason: str | None = None
```

And add a factory at the end of `vision/hawkeye_vision/yolo_tracker.py`:

```python
def build_tracker(config: VisionConfig, *, weights: str = "yolo11m.pt"):
    """The real tracker, or an honest stand-in for it.

    The only place in the package that decides between them, so no caller has to
    remember to handle the failure.
    """
    from hawkeye_vision.track import UnavailableTracker

    try:
        return YoloBotSortTracker(config, weights=weights)
    except TrackerUnavailable as exc:
        logger.error("Tracker unavailable, continuing without measured counts: %s", exc)
        return UnavailableTracker(reason=str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/ -m 'not integration' -q`
Expected: PASS, 12 passed in test_track.py and all earlier tests still green

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/track.py vision/hawkeye_vision/yolo_tracker.py vision/tests/test_track.py
git commit -m "Degrade to an unavailable tracker rather than taking down the recording"
```

---

## Task 11: The segment writer and its hashes

**Files:**
- Create: `vision/hawkeye_vision/record.py`
- Test: `vision/tests/test_record.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_record.py`:

```python
"""Rotating mp4 segments, and the hash of each one as it closes."""

import hashlib
import os

import numpy as np
import pytest

from hawkeye_vision.frames import Frame, utc_now
from hawkeye_vision.record import SegmentWriter


def _frame(index: int, value: int = 120) -> Frame:
    return Frame(
        image=np.full((120, 160, 3), value, dtype=np.uint8),
        index=index,
        captured_at=utc_now(),
    )


def test_segments_land_under_the_incident_directory(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(10):
            writer.write(_frame(i))

    assert os.path.isdir(tmp_path / "inc-1")
    assert (tmp_path / "inc-1" / "seg-0000.mp4").exists()


def test_the_writer_rotates_at_the_segment_boundary(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(25):
            writer.write(_frame(i))

    names = sorted(p.name for p in (tmp_path / "inc-1").glob("*.mp4"))
    assert names == ["seg-0000.mp4", "seg-0001.mp4", "seg-0002.mp4"]


def test_a_closed_segment_reports_its_sha256(tmp_path):
    """A file still being written cannot be hashed. Only closed ones are sealed."""
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10) as writer:
        for i in range(10):
            writer.write(_frame(i))
        writer.write(_frame(10))  # forces the first segment closed

        sealed = writer.sealed

    assert len(sealed) == 1
    assert sealed[0].path.endswith("seg-0000.mp4")
    assert len(sealed[0].sha256) == 64


def test_the_reported_hash_matches_the_file_on_disk(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5) as writer:
        for i in range(10):
            writer.write(_frame(i))

    for segment in writer.sealed:
        with open(segment.path, "rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == segment.sha256


def test_closing_seals_the_final_partial_segment(tmp_path):
    """An incident that ends abruptly must not lose its last seconds."""
    writer = SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=10)
    for i in range(13):
        writer.write(_frame(i))
    writer.close()

    assert len(writer.sealed) == 2
    assert all(len(s.sha256) == 64 for s in writer.sealed)


def test_two_identical_segments_do_not_share_a_path(tmp_path):
    with SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5) as writer:
        for i in range(10):
            writer.write(_frame(i, value=120))

    paths = {s.path for s in writer.sealed}
    assert len(paths) == 2


def test_writing_after_close_is_refused(tmp_path):
    writer = SegmentWriter(tmp_path / "inc-1", fps=15, segment_frames=5)
    writer.write(_frame(0))
    writer.close()

    with pytest.raises(RuntimeError):
        writer.write(_frame(1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_record.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.record'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/record.py`:

```python
"""The record. Rotating mp4 segments, each hashed as it closes.

Three consumers, one artifact: the resident watches these in the iOS app,
`replay` folds each hash into the chain, and `replay` attaches them to the
police email. That is why the hash is taken here, at the moment the file is
closed, rather than later by whoever happens to read it.

Ten-second segments rather than one long file, for two reasons that are both
about failure. A file still being written cannot be hashed, so a single growing
file could never be sealed until the incident ended. And an incident that ends
abruptly, because the power went or the process was killed, should lose ten
seconds rather than everything.

**Nothing in this module enhances, brightens or filters a frame.** These files
are evidence. The low-light work happens in `enhance.py` before detection, and
in the client before display, and neither touches what lands here.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

from hawkeye_vision.frames import Frame

logger = logging.getLogger(__name__)

#: Read the file in chunks rather than whole: a segment is a few megabytes now,
#: but the hash must not become the thing that runs the Pi out of memory.
_HASH_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class SealedSegment:
    """One closed segment file and the hash of its bytes."""

    path: str
    sha256: str
    frames: int


def sha256_of(path: str | Path) -> str:
    """SHA-256 of a file's bytes, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class SegmentWriter:
    """Write frames into rotating, hashable mp4 segments."""

    def __init__(
        self,
        directory: str | Path,
        *,
        fps: int,
        segment_frames: int,
    ) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._fps = fps
        self._segment_frames = segment_frames

        self._writer: cv2.VideoWriter | None = None
        self._current_path: Path | None = None
        self._frames_in_segment = 0
        self._segment_index = 0
        self._closed = False
        self.sealed: list[SealedSegment] = []

    def write(self, frame: Frame) -> None:
        """Append one frame, rotating first if the current segment is full."""
        if self._closed:
            raise RuntimeError("SegmentWriter is closed")

        if self._writer is None:
            self._open_segment(frame)
        elif self._frames_in_segment >= self._segment_frames:
            self._seal_segment()
            self._open_segment(frame)

        assert self._writer is not None
        self._writer.write(frame.image)
        self._frames_in_segment += 1

    def _open_segment(self, frame: Frame) -> None:
        height, width = frame.image.shape[:2]
        self._current_path = self._directory / f"seg-{self._segment_index:04d}.mp4"
        writer = cv2.VideoWriter(
            str(self._current_path),
            cv2.VideoWriter.fourcc(*"mp4v"),
            self._fps,
            (width, height),
        )
        if not writer.isOpened():
            # Loud, per vision/CLAUDE.md: a sealed record missing its video is
            # worse than a visible failure.
            raise OSError(f"could not open a video writer at {self._current_path}")
        self._writer = writer
        self._frames_in_segment = 0

    def _seal_segment(self) -> None:
        """Close the current file and hash it. The only place a hash is taken."""
        if self._writer is None or self._current_path is None:
            return
        self._writer.release()
        self.sealed.append(
            SealedSegment(
                path=str(self._current_path),
                sha256=sha256_of(self._current_path),
                frames=self._frames_in_segment,
            )
        )
        logger.info("sealed %s (%d frames)", self._current_path.name, self._frames_in_segment)
        self._writer = None
        self._current_path = None
        self._segment_index += 1

    def close(self) -> None:
        """Seal the segment in progress and stop accepting frames."""
        if self._closed:
            return
        self._seal_segment()
        self._closed = True

    def __enter__(self) -> "SegmentWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_record.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/record.py vision/tests/test_record.py
git commit -m "Write rotating mp4 segments and hash each one as it closes"
```

---

## Task 12: The live Brio

**Files:**
- Create: `vision/hawkeye_vision/webcam.py`
- Create: `vision/hawkeye_vision/record_fixture.py`
- Test: manual, against the attached camera

- [ ] **Step 1: Write the camera source**

There is no automated test here, and that is deliberate rather than an omission. A test that needs a specific USB device attached is a test that fails on every other machine, and the logic this class wraps is one OpenCV call. Everything downstream is already proved against `FileFixture`.

Create `vision/hawkeye_vision/webcam.py`:

```python
"""The Logitech Brio 101 on this laptop, over AVFoundation.

The Pi will get a `PiV4L2` alongside this with the `v4l2-ctl` exposure and
white balance pinning from `docs/hardware/logitech-camera.md`. Both satisfy
`FrameSource`, so nothing downstream changes.

**Open the device once.** Two processes opening the same camera is the classic
device-busy failure, and it will happen the first time someone runs the
recorder and the preview separately. One reader, fan out in software.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import cv2
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now

logger = logging.getLogger(__name__)


class CameraUnavailable(RuntimeError):
    """The camera could not be opened. Consumers report `no_camera`."""


class MacCamera(FrameSource):
    """A UVC camera on macOS.

    `index` is the AVFoundation device index, which is ordering-dependent: the
    built-in FaceTime camera is usually 0 and an external USB camera usually 1,
    but plugging in an iPhone via Continuity Camera shifts them. Check with
    `system_profiler SPCameraDataType` and pass the index explicitly.
    """

    source = Source.CAMERA_UVC

    def __init__(self, index: int = 1, *, width: int = 1280, height: int = 720) -> None:
        self._capture = cv2.VideoCapture(index)
        if not self._capture.isOpened():
            raise CameraUnavailable(f"could not open camera at index {index}")

        # MJPG, per docs/hardware/logitech-camera.md. A YUYV stream at 720p is
        # roughly 27MB/sec over USB 2.0 and the Pi drops frames or refuses to
        # open the stream at all.
        self._capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        actual_w = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (actual_w, actual_h) != (width, height):
            logger.warning(
                "camera gave %dx%d rather than the requested %dx%d",
                actual_w, actual_h, width, height,
            )

    def frames(self) -> Iterator[Frame]:
        index = 0
        while True:
            ok, image = self._capture.read()
            if not ok:
                logger.error("camera read failed; stream has ended")
                return
            yield Frame(image=image, index=index, captured_at=utc_now())
            index += 1

    def close(self) -> None:
        self._capture.release()

    def __enter__(self) -> "MacCamera":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
```

- [ ] **Step 2: Verify it sees the Brio**

Run:

```bash
cd vision && python -c "
from hawkeye_vision.webcam import MacCamera
with MacCamera(index=1) as cam:
    f = next(cam.frames())
    print('frame', f.image.shape, 'source', cam.source)
"
```

Expected: `frame (720, 1280, 3) source camera-uvc`

If the shape is wrong or the image is from the built-in FaceTime camera, try `index=0` and `index=2`. Confirm which is the Brio with `system_profiler SPCameraDataType`.

- [ ] **Step 3: Write the fixture recorder**

Create `vision/hawkeye_vision/record_fixture.py`:

```python
"""Record a short clip off the Brio, for the tests that need real people in them.

Synthetic rectangles are not people and YOLO will not detect them, so the
tracking integration tests need genuine footage. This records it.

    python -m hawkeye_vision.record_fixture tests/footage/person.mp4 --seconds 10

Walk in and out of frame while it runs. For the occlusion test, have two people
cross paths in front of the lens.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hawkeye_vision.record import SegmentWriter
from hawkeye_vision.webcam import MacCamera


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Where to write the mp4.")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--camera", type=int, default=1, help="AVFoundation device index.")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    wanted = args.seconds * args.fps

    with MacCamera(index=args.camera) as camera:
        # One segment holding the whole clip: this is a fixture, not a record.
        with SegmentWriter(output.parent, fps=args.fps, segment_frames=wanted + 1) as writer:
            for frame in camera.frames():
                writer.write(frame)
                if frame.index + 1 >= wanted:
                    break

    written = Path(writer.sealed[0].path)
    written.rename(output)
    print(f"wrote {output} ({wanted} frames)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Record the fixture and run the integration tests**

Run:

```bash
cd vision && python -m hawkeye_vision.record_fixture tests/footage/person.mp4 --seconds 10
```

Walk in and out of frame while it records. Get a second person to cross in front of you if one is available.

Append to `.gitignore` at the repo root:

```
# Recorded test footage. Real people, so it does not belong in a public repo,
# and a binary fixture in git drifts from the code that reads it.
vision/tests/footage/
```

Run: `cd vision && python3 -m pytest tests/test_yolo.py -v -m integration`
Expected: PASS, 4 passed. If `test_track_identity_survives_a_crossing_occlusion` reports more ids than people who were in shot, the fixture is short or the lighting is poor - re-record before tuning thresholds.

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/webcam.py vision/hawkeye_vision/record_fixture.py .gitignore
git commit -m "Open the Brio once, and record the real footage the tracker tests need"
```

---

## Task 13: The live preview

The deliverable of Phase A: one command, a window, boxes with track ids, the lighting state and the luminance reading, and segments landing on disk.

**Files:**
- Create: `vision/hawkeye_vision/overlay.py`
- Create: `vision/hawkeye_vision/__main__.py`
- Test: `vision/tests/test_overlay.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_overlay.py`:

```python
"""Drawing tracks onto a frame. Pure pixels, no camera."""

import numpy as np

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.overlay import draw
from hawkeye_vision.track import BBox, TrackBook, Detection


def _blank() -> np.ndarray:
    return np.zeros((240, 320, 3), dtype=np.uint8)


def _book_with_one_track() -> TrackBook:
    book = TrackBook(VisionConfig())
    book.ingest(
        [Detection(track_id=3, bbox=BBox(x1=0.2, y1=0.2, x2=0.6, y2=0.9), confidence=0.9)],
        frame_index=0,
    )
    return book


def test_drawing_does_not_mutate_the_frame_it_was_given():
    """The recorder gets the same frame. An overlay burned into evidence is fatal."""
    frame = _blank()
    before = frame.copy()

    draw(frame, _book_with_one_track(), LightingMode.DAY, 200.0)

    assert np.array_equal(frame, before)


def test_drawing_puts_pixels_on_the_returned_copy():
    result = draw(_blank(), _book_with_one_track(), LightingMode.DAY, 200.0)

    assert result.sum() > 0


def test_an_empty_book_still_renders_the_status_line():
    result = draw(_blank(), TrackBook(VisionConfig()), LightingMode.TOO_DARK, 4.0)

    assert result.sum() > 0


def test_boxes_are_scaled_from_normalised_coordinates_to_the_frame():
    """A 0.2..0.6 box on a 320-wide frame must land at x 64..192, not at 0..1."""
    result = draw(_blank(), _book_with_one_track(), LightingMode.DAY, 200.0)
    column_has_ink = result[:, :, :].sum(axis=(0, 2)) > 0

    assert column_has_ink[64]
    assert not column_has_ink[20]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd vision && python3 -m pytest tests/test_overlay.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'hawkeye_vision.overlay'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/overlay.py`:

```python
"""Drawing what the tracker measured onto a copy of the frame.

**A copy, always.** The frame object handed to this function is the same one
going to the segment writer, and an overlay burned into a file that gets emailed
to a police department is evidence with graphics drawn on it.

This is the local preview. The iOS and replay-console overlays are Phase C and
draw from `vision.tracks[]` over the video element, which is why the boxes are
normalised: the same numbers work at any view size.
"""

from __future__ import annotations

import cv2
import numpy as np

from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.track import TrackBook

_MODE_COLOUR: dict[LightingMode, tuple[int, int, int]] = {
    LightingMode.DAY: (120, 220, 120),
    LightingMode.LOW: (80, 180, 255),
    LightingMode.TOO_DARK: (80, 80, 240),
}


def draw(
    image: np.ndarray,
    book: TrackBook,
    mode: LightingMode,
    luminance: float,
) -> np.ndarray:
    """Return a copy of the frame with tracks and the status line drawn on it."""
    canvas = image.copy()
    height, width = canvas.shape[:2]
    colour = _MODE_COLOUR[mode]

    for track in book.active:
        x1 = int(track.bbox.x1 * width)
        y1 = int(track.bbox.y1 * height)
        x2 = int(track.bbox.x2 * width)
        y2 = int(track.bbox.y2 * height)

        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 2)
        cv2.putText(
            canvas,
            f"id {track.track_id}  {track.confidence:.2f}",
            (x1, max(14, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            colour,
            1,
            cv2.LINE_AA,
        )

    status = f"{mode.value}  luma {luminance:5.1f}  people {book.people_visible}"
    cv2.putText(
        canvas, status, (8, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA,
    )
    return canvas
```

Create `vision/hawkeye_vision/__main__.py`:

```python
"""The camera path, standalone. No agents, no network, no Gemini.

    python -m hawkeye_vision                        # live Brio
    python -m hawkeye_vision --fixture clip.mp4     # replay a file
    python -m hawkeye_vision --record out/inc-1     # also write segments

Press q to stop.

This is Phase A's deliverable and the thing to run when something looks wrong
later: it exercises capture, lighting, tracking and recording with nothing else
in the way.
"""

from __future__ import annotations

import argparse
import logging

import cv2

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.enhance import to_detection_input
from hawkeye_vision.frames import Frame, FrameSource
from hawkeye_vision.lighting import LightingClassifier, mean_luminance
from hawkeye_vision.overlay import draw
from hawkeye_vision.profiles import for_mode
from hawkeye_vision.record import SegmentWriter
from hawkeye_vision.track import TrackBook

logger = logging.getLogger(__name__)


def _source(args: argparse.Namespace) -> FrameSource:
    if args.fixture:
        from hawkeye_vision.fixture import FileFixture

        return FileFixture(args.fixture)

    from hawkeye_vision.webcam import MacCamera

    return MacCamera(index=args.camera)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", help="Replay this mp4 instead of opening the camera.")
    parser.add_argument("--camera", type=int, default=1, help="AVFoundation device index.")
    parser.add_argument("--record", help="Directory to write mp4 segments into.")
    parser.add_argument("--headless", action="store_true", help="No window; log only.")
    args = parser.parse_args()

    config = VisionConfig()
    classifier = LightingClassifier(config)
    book = TrackBook(config)

    from hawkeye_vision.yolo_tracker import build_tracker

    tracker = build_tracker(config)
    if not tracker.available:
        logger.error("running without measured counts: %s", tracker.reason)

    source = _source(args)
    writer = (
        SegmentWriter(args.record, fps=config.day_fps, segment_frames=config.day_fps * 10)
        if args.record
        else None
    )

    try:
        for frame in source.frames():
            luminance = mean_luminance(frame.image)
            mode = classifier.update(luminance)
            profile = for_mode(mode, config)

            # The recorder gets the frame exactly as it came off the sensor,
            # before any enhancement and before any overlay.
            if writer is not None:
                writer.write(frame)

            if profile.detect and tracker.available:
                if hasattr(tracker, "set_confidence"):
                    tracker.set_confidence(profile.confidence)
                detection_input = to_detection_input(frame.image, enhance=profile.enhance)
                detections = tracker.update(
                    Frame(
                        image=detection_input,
                        index=frame.index,
                        captured_at=frame.captured_at,
                    )
                )
            else:
                detections = []

            book.ingest(detections, frame_index=frame.index)

            if args.headless:
                if frame.index % 15 == 0:
                    logger.info(
                        "frame %d  %s  luma %.1f  people %d",
                        frame.index, mode.value, luminance, book.people_visible,
                    )
                continue

            cv2.imshow("Hawk Eye vision", draw(frame.image, book, mode, luminance))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        if writer is not None:
            writer.close()
            logger.info("sealed %d segments", len(writer.sealed))
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd vision && python3 -m pytest tests/test_overlay.py -v`
Expected: PASS, 4 passed

Run the whole fast suite: `cd vision && python3 -m pytest tests/ -m 'not integration' -q`
Expected: PASS, everything green

- [ ] **Step 5: Verify against the live camera**

Run:

```bash
cd vision && python -m hawkeye_vision --record /tmp/hawkeye-inc-1
```

Expected, watching the window: a green box follows you with a stable `id`, the status line reads `day`, the luminance sits well above 90, and `people` reads 1. Turn the room lights off: within roughly three seconds the status turns to `low` and then `too_dark`, boxes stop, and the colour changes. Turn them back on and it recovers, without flickering between states on the way.

Then confirm the record:

```bash
ls -la /tmp/hawkeye-inc-1/
```

Expected: several `seg-NNNN.mp4` files, each playable, each roughly ten seconds.

If the boxes lag badly, confirm MPS was picked up rather than CPU: the startup log warns when it falls back.

- [ ] **Step 6: Commit**

```bash
git add vision/hawkeye_vision/overlay.py vision/hawkeye_vision/__main__.py vision/tests/test_overlay.py
git commit -m "Run the whole camera path from one command, with boxes and a lighting readout"
```

---

## Task 14: Record the finding about night vision

The hardware finding must be written down where someone will look for it, or it will be re-proposed.

**Files:**
- Modify: `docs/swapping-in-real-parts.md`
- Modify: `vision/CLAUDE.md`

- [ ] **Step 1: Add the finding to the switchboard**

Append to `docs/swapping-in-real-parts.md`:

```markdown
## There is no night vision, and there is no path to one

The camera is a Logitech Brio 101, USB `046d:094d`.
It has no IR sensor, unlike the original Brio 4K which carried one for Windows Hello, and no IR illuminator is owned.
Root `CLAUDE.md` states no further hardware is being purchased.

So there is no infrared capability to swap in, and no seam for one, because the missing part is a physical sensor rather than a mocked implementation.
X-ray imaging is not a capability any camera has and is not a thing to look for a seam for.

What exists instead is two separate, real things, and neither is ever called night vision:

- **Low-light capture mode**, in `vision/hawkeye_vision/lighting.py` and `profiles.py`.
  Measured mean luminance selects one of three states, and the state travels in the claim as `vision.lighting`.
  Below `dark_threshold` the system stops describing the room rather than describing a dark one.
- **Client-side viewing enhancement**, in the iOS app and the replay console.
  CLAHE, gamma and temporal denoise applied at display time so a resident can see the room.
  It never touches the recorded segments, which are hashed and emailed to a police department.

**How to tell the flip worked:** run `python -m hawkeye_vision` and turn the room lights off.
The status line must move `day` to `low` to `too_dark` within roughly three seconds of each change, and must not flicker between them on the way.

**The half-flipped state that looks like something else:** a shield still covering the lens produces the same black frame as an unlit room.
Both correctly report `too_dark`, and that is deliberate: `shutter` is open-loop and attests the angle it commanded rather than the angle the shield reached, so the luminance guard is the only thing that catches a jammed shield.
Distinguishing the two cases means checking whether a shutter attestation is held, not looking at the picture.
```

- [ ] **Step 2: Update the vision contract**

In `vision/CLAUDE.md`, in the claims table, change the `vision.people_visible` row to note it is measured, and add rows for the new fields:

```markdown
| `vision.people_visible` | How many distinct people are in frame. **Measured**, from the local tracker, not from the narration. A count of what the camera sees, not of the building |
| `vision.tracks` | **Measured.** Per person: `track_id`, normalised `bbox`, `first_seen_frame`, `last_seen_frame`, `frames_held`. Identities are stable within a session only |
| `vision.lighting` | **Measured.** `day`, `low` or `too_dark`. There is no IR capability; see `docs/swapping-in-real-parts.md` |
| `vision.mean_luminance` | **Measured.** Mean luma 0..255 of the frame the claim was made from |
```

Add to the limits section:

```markdown
**6. There is no night vision.**
The Brio 101 has no IR sensor and no illuminator is owned.
`vision.lighting: low` means the frame was contrast-stretched before detection and the confidence floor was raised, and nothing more.
Do not write a pitch sentence implying the camera sees in the dark. It does not; below `dark_threshold` it says so and stops describing the room.
```

- [ ] **Step 3: Commit**

```bash
git add docs/swapping-in-real-parts.md vision/CLAUDE.md
git commit -m "Record that there is no IR path, and what replaces it"
```

---

## Verification: the whole of Phase A

- [ ] Run the fast suite: `cd vision && python3 -m pytest tests/ -m 'not integration' -q`
- [ ] Run the integration suite: `cd vision && python3 -m pytest tests/ -m integration -q`
- [ ] Run the agents suite, confirming nothing regressed: `cd agents && python3 -m pytest -q`
- [ ] Run the backend suite, confirming the new `Source` values broke nothing: `cd app/backend && python3 -m pytest -q`
- [ ] Run the live path: `python -m hawkeye_vision --record /tmp/hawkeye-check`, walk through frame, turn the lights off and on, confirm the state transitions and the segment files
- [ ] Confirm the fast suite passes on a machine with NO torch and NO ultralytics installed.

This is the property that matters, and it is NOT the same as "torch is never imported".
`build_tracker` reaches for the real tracker first, so the fast suite does import torch whenever torch happens to be present.
Simulate its absence instead:

```bash
cd vision && python3 -c "
import sys, builtins, pytest
_real = builtins.__import__
def blocked(name, *a, **k):
    if name.split('.')[0] in {'torch', 'ultralytics'}:
        raise ImportError('simulated: not installed')
    return _real(name, *a, **k)
builtins.__import__ = blocked
sys.exit(pytest.main(['tests/','-m','not integration','-q','-p','no:cacheprovider']))
"
```

Expected: every fast test passes, because `build_tracker` catches the ImportError and returns an `UnavailableTracker`.
Measured 2026-09-19: 91 passed in 0.92s.

Phase A is done when all six pass.

---

## What Phase B needs from this

Stated here so the next plan does not have to rediscover it.

- `TrackBook.people_visible` and `TrackBook.active` are the measured inputs to `vision.people_visible` and `vision.tracks`.
- `LightingClassifier.mode` and `mean_luminance` are the inputs to `vision.lighting` and `vision.mean_luminance`.
- `LightingMode.TOO_DARK` is the trigger for `Unknown(reason="frame_too_dark")`.
- `Tracker.available` and `Tracker.reason` are the trigger for `Unknown(reason="tracker_unavailable")`.
- `SegmentWriter.sealed` is what `replay` folds into the hash chain.
- Phase B must add `Source.GEMINI_LIVE` and a new `SourceClass.GENERATED`, and add the matching case to `app/ios/HawkEye/Models/Provenance.swift`, or the iOS app will fail to decode a claim carrying it.
