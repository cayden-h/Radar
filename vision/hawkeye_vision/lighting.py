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

        if not self._has_left_current_band(luminance):
            self._held = 0
            return self._current

        self._held += 1
        if self._held >= self._config.dwell_frames:
            # Read the destination at the moment of commitment rather than
            # tracking a candidate. Noise that keeps the reading outside the
            # band still accumulates dwell, which is what stops a lit room
            # sitting in TOO_DARK forever because its luminance jitters across
            # a threshold.
            self._current = classify(luminance, self._config)
            self._held = 0

        return self._current

    def _has_left_current_band(self, luminance: float) -> bool:
        """Has the reading cleared the edges of the state we are in?

        Hysteresis is applied to the band we are CURRENTLY in, not to the
        destination's threshold. Anchoring it on the destination was a bug: a
        jump from DAY straight to TOO_DARK was checked against the TOO_DARK
        boundary plus margin, which a genuinely dark frame never cleared, so a
        shield jammed over the lens was reported as a well-lit room forever.
        """
        lower, upper = _band_edges(self._current, self._config)
        margin = self._config.hysteresis

        if lower is not None and luminance < lower - margin:
            return True
        if upper is not None and luminance >= upper + margin:
            return True
        return False


def _band_edges(
    mode: LightingMode, config: VisionConfig
) -> tuple[float | None, float | None]:
    """The luminance edges of a state's band. None means unbounded that way."""
    if mode is LightingMode.TOO_DARK:
        return None, config.dark_threshold
    if mode is LightingMode.LOW:
        return config.dark_threshold, config.day_threshold
    return config.day_threshold, None
