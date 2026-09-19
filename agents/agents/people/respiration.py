"""Respiration, heart rate, and the personhood verdict.

**This is the part of `people` everything else is conditioned on.** It is not a
reporting channel; it is what decides a presence is human. A perturbation
showing quasi-periodic modulation in a physiological band is a living body. A
fan, a curtain, a rolling cart, a swinging door: none of them produce that
signature.

Three properties make it load-bearing, and each shows up in the code:

1. **Calibration-free.** `band_peak` asks whether the window contains a narrow
   periodic component in the 0.1-0.5 Hz band. That question does not need to
   know what an empty room looks like, which is why this works on minute one
   and the zone baseline in `presence.py` does not.
2. **It discriminates human from non-human motion.** Nothing else in the stack
   can make that distinction.
3. **It works on someone who is not moving**, which is exactly where motion
   detection fails and exactly the case that matters.

The hard rule: **respiration carries the personhood decision, never heart
rate.** Breathing moves the chest wall 5-12mm; a heartbeat moves it a few tenths
of a millimetre, under respiration harmonics. Heart rate is a stretch goal and a
good number to say on a 911 call. It decides nothing.

The other hard rule: **absence of a respiration signature is not absence of a
person.** Shallow breathing, breath-holding and range limits all degrade toward
invisible. So a zone with no signature produces an `Unknown`, never an assertion
that the zone is empty, and a signature that *disappears* from a zone that had
one is escalated rather than resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from hawkeye_backend.models.common import Provenance
from hawkeye_backend.models.state import RespirationStatus
from hawkeye_backend.verification.envelope import Severity

from agents.core.observations import Assertion, Unknown
from agents.core.ports import CsiFrame
from agents.core.signals import band_peak, hz_to_bpm, rms

# RuView's stated respiration range, 6-30 BPM, in Hz. Outside it we report
# nothing rather than a number: reporting nothing is safer than reporting a
# value outside the supported range.
RESPIRATION_LO_HZ = 6.0 / 60.0
RESPIRATION_HI_HZ = 30.0 / 60.0

# RuView's heart-rate range. Attempted only when the frame rate can support it.
HEART_LO_HZ = 40.0 / 60.0
HEART_HI_HZ = 120.0 / 60.0

# A breath is 2 to 10 seconds long. Thirty seconds is the shortest window that
# holds three cycles of the slowest breath we will report, and three cycles is
# where a periodicity claim starts being a measurement rather than a guess.
WINDOW_S = 30.0

# Fraction of window power that must sit in the respiration peak before this is
# called a living body.
# TODO(sensor): set this from captured data. An empty room and an occupied room
# from the same link, same channel, same geometry, is all it takes. No CSI
# exists as of 2026-09-19, so this is a named placeholder with a rationale.
PERSONHOOD_STRENGTH = 0.25

# Below this frame rate, cardiac modulation is not recoverable and claiming it
# would be inventing a number for a dispatcher. Beacons alone are ~10 Hz, which
# is why `sudo ping -i 0.01 <gateway>` from the MacBook is not optional.
HEART_MIN_RATE_HZ = 20.0

# Above this RMS the zone is moving, which both confirms a person immediately
# and degrades the respiration estimate, because movement is broadband energy
# sitting on top of the band being measured.
MOVING_RMS = 0.15


@dataclass
class ZoneMemory:
    """What is remembered about one zone, for one session only.

    Session-scoped by design. `presence_id` is stable within a session and we do
    not do person re-identification, so nothing here persists across a restart
    and nothing here is written to disk.
    """

    presence_id: str
    last_breathing_at: datetime | None = None
    last_bpm: float | None = None


@dataclass(frozen=True)
class ZoneVitals:
    """What respiration found in one zone. Consumed by the rest of `people`."""

    zone: str
    presence_id: str | None
    breathing: bool
    bpm: float | None
    moving: bool
    strength: float
    """Peak band power as a fraction of total window power. Not a probability."""


class RespirationReader:
    """Reads the CSI window and answers personhood, respiration, heart rate."""

    def __init__(self, agent_name: str) -> None:
        self._agent = agent_name
        self._memory: dict[str, ZoneMemory] = {}
        self._seq = 0

    @property
    def known_zones(self) -> set[str]:
        return set(self._memory)

    def analyse(
        self, frames: list[CsiFrame], provenance: Provenance
    ) -> tuple[dict[str, ZoneVitals], list[Assertion], list[Unknown]]:
        """One pass over every zone in the newest frame."""
        newest = frames[-1]
        rate_hz = newest.rate_hz
        vitals: dict[str, ZoneVitals] = {}
        assertions: list[Assertion] = []
        unknowns: list[Unknown] = []

        for zone in sorted(newest.amplitude):
            series = [f.amplitude.get(zone, 0.0) for f in frames]
            memory = self._memory.get(zone)
            peak = band_peak(series, rate_hz, RESPIRATION_LO_HZ, RESPIRATION_HI_HZ)
            motion = rms(series)
            moving = motion >= MOVING_RMS

            if peak is None or peak.strength < PERSONHOOD_STRENGTH:
                vitals[zone] = ZoneVitals(
                    zone=zone,
                    presence_id=memory.presence_id if memory else None,
                    breathing=False,
                    bpm=None,
                    moving=moving,
                    strength=peak.strength if peak else 0.0,
                )
                unknowns.append(
                    Unknown(
                        field="people.personhood",
                        zone_scope=zone,
                        reason=(
                            "No periodicity in the 0.1-0.5 Hz band above threshold. This is "
                            "not evidence the zone is empty: shallow breathing, breath-holding "
                            "and range limits all look like this."
                        ),
                    )
                )
                if memory is not None and memory.last_breathing_at is not None:
                    # A signature that was there and is now gone is the one case
                    # where absence is worth escalating rather than shrugging
                    # at. It is still not a claim that the person is gone or
                    # dead; it is a claim that something changed and somebody
                    # should look. The collapse reader is the cross-check.
                    gone_s = (newest.captured_at - memory.last_breathing_at).total_seconds()
                    assertions.append(
                        Assertion(
                            field="people.respiration_lost",
                            value=f"{gone_s:.0f}",
                            zone_scope=zone,
                            severity_ceiling=Severity.ACTIONABLE,
                            confidence=0.5,
                            basis=(
                                f"A respiration signature was present in this zone {gone_s:.0f}s "
                                f"ago at {memory.last_bpm:.0f} BPM and is no longer resolvable. "
                                "Cross-check the collapse state before concluding anything."
                                if memory.last_bpm is not None
                                else (
                                    "A respiration signature was present here and is no longer "
                                    "resolvable."
                                )
                            ),
                            presence_id=memory.presence_id,
                            provenance=provenance,
                        )
                    )
                continue

            bpm = hz_to_bpm(peak.frequency_hz)
            if memory is None:
                self._seq += 1
                memory = ZoneMemory(presence_id=f"p{self._seq}")
                self._memory[zone] = memory
            memory.last_breathing_at = newest.captured_at
            memory.last_bpm = bpm
            confidence = round(min(0.99, peak.strength * 2.0), 2)
            vitals[zone] = ZoneVitals(
                zone=zone,
                presence_id=memory.presence_id,
                breathing=True,
                bpm=bpm,
                moving=moving,
                strength=peak.strength,
            )

            # Personhood. This is the assertion the rest of the system is built
            # on, so its basis is written to be read aloud on a phone call.
            assertions.append(
                Assertion(
                    field="people.personhood",
                    value="living_body",
                    zone_scope=zone,
                    # ACTIONABLE, not DISPATCHABLE: "there is a person here" is
                    # not by itself a reason to send anybody. It becomes one
                    # only in combination, which is master's job.
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=confidence,
                    basis=(
                        f"Quasi-periodic modulation at {bpm:.1f} breaths per minute carrying "
                        f"{peak.strength:.0%} of the window's power. A fan is periodic at the "
                        "wrong frequency and a curtain is not periodic at all."
                    ),
                    presence_id=memory.presence_id,
                    provenance=provenance,
                )
            )
            assertions.append(
                Assertion(
                    field="people.respiration",
                    value=RespirationStatus.BREATHING.value,
                    zone_scope=zone,
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=confidence,
                    basis=f"Respiration resolved at {bpm:.1f} BPM, +/-{hz_to_bpm(peak.resolution_hz):.1f}.",
                    presence_id=memory.presence_id,
                    provenance=provenance,
                )
            )
            assertions.append(
                Assertion(
                    field="people.breathing_bpm",
                    value=f"{bpm:.1f}",
                    zone_scope=zone,
                    # DISPATCHABLE when abnormal, because a respiration rate
                    # outside the normal band is what turns an occupancy report
                    # into a medical emergency. Normal is informational.
                    severity_ceiling=(
                        Severity.DISPATCHABLE if abnormal(bpm) else Severity.INFORMATIONAL
                    ),
                    confidence=confidence,
                    basis=(
                        f"{bpm:.1f} BPM. Normal resting adult is 12-20; this is "
                        + ("outside that band." if abnormal(bpm) else "within it.")
                        + (" Motion in this zone degrades the estimate." if moving else "")
                    ),
                    presence_id=memory.presence_id,
                    provenance=provenance,
                )
            )
            assertions.append(
                Assertion(
                    field="people.moving",
                    value="true" if moving else "false",
                    zone_scope=zone,
                    severity_ceiling=Severity.CORROBORATING,
                    confidence=0.8,
                    basis=(
                        f"Broadband RMS {motion:.3f} against a {MOVING_RMS} threshold. Movement "
                        "is broadband; breathing is narrowband. The two are separable, and the "
                        "difference is 'walking around' versus 'on the floor'."
                    ),
                    presence_id=memory.presence_id,
                    provenance=provenance,
                )
            )

            heart = self._heart_rate(series, rate_hz, moving)
            if heart is None:
                unknowns.append(
                    Unknown(
                        field="people.heart_bpm",
                        zone_scope=zone,
                        reason=(
                            f"Frame rate {rate_hz:.1f} Hz is below the {HEART_MIN_RATE_HZ:.0f} Hz "
                            "floor for cardiac modulation."
                            if rate_hz < HEART_MIN_RATE_HZ
                            else "No cardiac peak separable from respiration harmonics."
                        ),
                    )
                )
            else:
                assertions.append(
                    Assertion(
                        field="people.heart_bpm",
                        value=f"{heart:.0f}",
                        zone_scope=zone,
                        # Never above INFORMATIONAL. It is a good number to say
                        # on the call and it decides nothing, and the ceiling is
                        # where that is enforced rather than remembered.
                        severity_ceiling=Severity.INFORMATIONAL,
                        confidence=0.4,
                        basis=(
                            f"{heart:.0f} BPM, best effort. Chest wall displacement from a "
                            "heartbeat is a few tenths of a millimetre against 5-12mm for "
                            "breathing. Reported, never relied on."
                        ),
                        presence_id=memory.presence_id,
                        provenance=provenance,
                    )
                )

        # Zones remembered but no longer in the feed at all. Worth surfacing: a
        # zone dropping out of the capture is a sensor fault, not an empty room,
        # and the two must not look the same.
        for zone in sorted(self.known_zones - set(newest.amplitude)):
            unknowns.append(
                Unknown(
                    field="people.personhood",
                    zone_scope=zone,
                    reason="Zone is no longer present in the CSI feed. Sensor coverage, not vacancy.",
                )
            )

        return vitals, assertions, unknowns

    def _heart_rate(self, series: list[float], rate_hz: float, moving: bool) -> float | None:
        """Cardiac rate, or None. None is the common and correct answer.

        Refused outright while the zone is moving. Movement puts broadband
        energy across the entire spectrum including this band, and a peak found
        under those conditions is a peak in the movement, not in anybody's chest.
        """
        if rate_hz < HEART_MIN_RATE_HZ or moving:
            return None
        peak = band_peak(series, rate_hz, HEART_LO_HZ, HEART_HI_HZ)
        if peak is None or peak.strength < 0.12:
            return None
        return hz_to_bpm(peak.frequency_hz)


def abnormal(bpm: float) -> bool:
    """Outside the normal resting adult band of 12-20 BPM.

    Deliberately not "outside 6-30": that is the range of what we can *measure*,
    and this is the range of what is *normal*. Conflating the two would make
    every infant an emergency and every measurement limit a diagnosis.
    """
    return bpm < 12.0 or bpm > 20.0
