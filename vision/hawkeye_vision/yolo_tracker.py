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
        except ImportError as exc:
            raise TrackerUnavailable(f"ultralytics or torch not installed: {exc}") from exc

        self._device = "mps" if torch.backends.mps.is_available() else "cpu"
        if self._device == "cpu":
            logger.warning(
                "MPS unavailable, running YOLO on CPU. Expect roughly 2fps; "
                "the claim rate is 1fps so this still works, but the preview will crawl."
            )
        try:
            self._model = YOLO(weights)
        except Exception as exc:
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
