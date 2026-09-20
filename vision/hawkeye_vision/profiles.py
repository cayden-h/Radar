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
