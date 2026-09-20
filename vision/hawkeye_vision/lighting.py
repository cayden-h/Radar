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
