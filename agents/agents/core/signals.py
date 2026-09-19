"""Small signal helpers shared by the sensing agents. No numpy.

Everything here is a few dozen lines of arithmetic over a list of floats, which
is the right size for what the agents actually need and avoids a wheel on the
Pi. If this file starts growing an FFT, move it into `sensor/` where the capture
path already owns the heavy lifting.

The one non-obvious choice is `band_peak`: it evaluates a direct DFT at a set of
candidate frequencies rather than taking an FFT and reading bins. In a 30-second
window the FFT bin spacing is 1/30 Hz, which over the 0.1-0.5 Hz respiration
band gives twelve bins to resolve 6 to 30 breaths a minute. That is too coarse
to report a rate. Evaluating a hundred candidate frequencies inside the band
costs a few hundred thousand multiply-adds and gives a resolution worth quoting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def detrend(samples: list[float]) -> list[float]:
    """Remove the mean and the linear trend.

    Not optional. Channel amplitude drifts with temperature, gain control and
    slow changes in the static multipath structure, and a drift across a
    30-second window puts energy at the very low frequencies that sit right
    under the respiration band. Left in, it reads as a very slow breath.
    """
    n = len(samples)
    if n < 2:
        return list(samples)
    mean_x = (n - 1) / 2.0
    mean_y = sum(samples) / n
    sxx = sum((i - mean_x) ** 2 for i in range(n))
    if sxx == 0.0:
        return [y - mean_y for y in samples]
    sxy = sum((i - mean_x) * (samples[i] - mean_y) for i in range(n))
    slope = sxy / sxx
    return [samples[i] - (mean_y + slope * (i - mean_x)) for i in range(n)]


@dataclass(frozen=True)
class BandPeak:
    """The strongest periodicity found inside a frequency band."""

    frequency_hz: float
    strength: float
    """Peak band power as a fraction of total signal power, 0-1.

    This is the number that decides personhood, so it is worth being precise
    about what it means. A body breathing in front of the link puts a large
    share of the window's energy into one narrow peak. A fan puts it at a much
    higher frequency, a curtain puts it nowhere in particular, and noise
    spreads it evenly. High strength inside the respiration band is the
    signature; it is not a probability and must not be rendered as one.
    """

    resolution_hz: float
    """Spacing of the candidate grid. The quoted rate is not finer than this."""


def band_peak(
    samples: list[float],
    sample_rate_hz: float,
    lo_hz: float,
    hi_hz: float,
    *,
    candidates: int = 128,
) -> BandPeak | None:
    """Strongest periodic component between `lo_hz` and `hi_hz`, or None.

    Returns None rather than a weak answer when the window is too short to
    resolve the band at all. Two cycles is the floor: below that, a "period" is
    indistinguishable from a trend, and reporting nothing is safer than
    reporting a number the data does not support.
    """
    n = len(samples)
    if n < 8 or sample_rate_hz <= 0.0 or hi_hz <= lo_hz:
        return None
    duration_s = n / sample_rate_hz
    if duration_s * lo_hz < 2.0:
        return None
    if hi_hz > sample_rate_hz / 2.0:
        # Above Nyquist there is nothing to find, only aliases of something else.
        hi_hz = sample_rate_hz / 2.0
        if hi_hz <= lo_hz:
            return None

    signal = detrend(samples)
    total = sum(v * v for v in signal)
    if total <= 0.0:
        return None

    step = (hi_hz - lo_hz) / (candidates - 1)
    best_freq = lo_hz
    best_power = -1.0
    for k in range(candidates):
        freq = lo_hz + k * step
        omega = 2.0 * math.pi * freq / sample_rate_hz
        real = 0.0
        imag = 0.0
        for i, value in enumerate(signal):
            angle = omega * i
            real += value * math.cos(angle)
            imag += value * math.sin(angle)
        # Normalized so power is comparable to `total` above: a pure sinusoid
        # at a candidate frequency puts essentially all of it into one peak.
        power = 2.0 * (real * real + imag * imag) / n
        if power > best_power:
            best_power = power
            best_freq = freq

    return BandPeak(
        frequency_hz=best_freq,
        strength=max(0.0, min(1.0, best_power / total)),
        resolution_hz=step,
    )


def rms(samples: list[float]) -> float:
    """Root mean square of the detrended window. The motion measure.

    Movement is a broadband disturbance rather than a periodic one, so it shows
    up here and not in `band_peak`. That split is the whole reason the two
    coexist: it is what separates "moving" from "still but breathing", and that
    difference is the difference between a person walking around and a person
    on the floor.
    """
    if not samples:
        return 0.0
    signal = detrend(samples)
    return math.sqrt(sum(v * v for v in signal) / len(signal))


def percentile(samples: list[float], q: float) -> float:
    """Linear-interpolated percentile, `q` in 0-1. Used for the rolling baseline.

    A percentile rather than a mean because the baseline has to survive people
    being in the room while it adapts. A mean drags toward whatever is
    happening; a low percentile tracks the quiet floor underneath it.
    """
    if not samples:
        raise ValueError("percentile of an empty window")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def hz_to_bpm(frequency_hz: float) -> float:
    """Cycles per second to cycles per minute. Respiration and heart rate both."""
    return frequency_hz * 60.0
