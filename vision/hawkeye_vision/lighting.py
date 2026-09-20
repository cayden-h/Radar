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
