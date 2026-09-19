"""Someone was upright, is now down, and has not gotten up.

This is where the project's strongest statistics live, and they are the reason
the design looks the way it does:

- A **long lie** is clinically defined as being unable to get up for more than
  one hour. That definition is the literature's, not ours.
- **53% of older fall patients are still on the floor when the ambulance
  arrives.**
- **Half of those down over an hour die within six months**, even where the fall
  caused no injury.

So `still_down_s` is not a diagnostic detail, it is the clinical variable, and
every minute below sixty is outcome being bought back. It is stamped from the
**transient**, not from the moment this became confident, because the sentence
that matters to a dispatcher is "she went down four minutes ago", not "we
decided twenty seconds ago".

**Debounce is the whole engineering problem.** Sitting down fast, lying down to
sleep and a child playing all look like a fall for an instant. The signature is
a collapse **followed by** absence of normal movement, cross-checked against the
respiration verdict. A system that calls 911 when someone flops onto a couch is
worse than no system - and note that nothing here calls anything: it surfaces
the detection so a person can act on it, and stamps `still_down_s` onto the
incident record so that when a human does call, the dispatcher learns the fall
happened four minutes ago rather than being told "I found her like this".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from hawkeye_backend.models.common import Provenance
from hawkeye_backend.verification.envelope import Severity

from agents.core.observations import Assertion, Unknown
from agents.core.ports import CsiFrame
from agents.core.signals import rms
from agents.people.respiration import ZoneVitals

#: Window the transient is looked for in. A fall is fast - RuView detects at
#: sub-200ms - so this only has to be long enough to contain one.
TRANSIENT_WINDOW_S = 2.0

#: Window the stillness is measured over, after the transient.
STILLNESS_WINDOW_S = 10.0

#: RMS above this is a large, fast disturbance: the transient itself.
TRANSIENT_RMS = 0.45

#: RMS below this is absence of normal movement.
STILL_RMS = 0.06

#: How long stillness must hold after a transient before this is a collapse.
#: The single most important number in the file. Too short and a couch is a
#: fall; too long and the clinical variable starts late.
#: TODO(sensor): set from real captures of a sit, a lie-down and a fall. No CSI
#: exists as of 2026-09-19 and these are placeholders with a stated rationale.
DEBOUNCE_S = 20.0

#: The literature's threshold, not ours. Sixty minutes.
LONG_LIE_S = 3600.0


@dataclass
class Candidate:
    """A transient that has happened, waiting to be confirmed or discarded."""

    zone: str
    at: datetime
    peak_rms: float
    still_since: datetime | None = None
    confirmed: bool = False


class CollapseReader:
    """Transient, then stillness, then a clock that keeps running."""

    def __init__(self) -> None:
        self._candidates: dict[str, Candidate] = {}

    @property
    def candidates(self) -> dict[str, Candidate]:
        return self._candidates

    def analyse(
        self,
        recent: list[CsiFrame],
        vitals: dict[str, ZoneVitals],
        provenance: Provenance,
    ) -> tuple[list[Assertion], list[Unknown]]:
        now = recent[-1].captured_at
        rate_hz = recent[-1].rate_hz
        transient_frames = [
            f for f in recent if (now - f.captured_at) <= timedelta(seconds=TRANSIENT_WINDOW_S)
        ]
        assertions: list[Assertion] = []
        unknowns: list[Unknown] = []

        for zone in sorted(recent[-1].amplitude):
            fast = rms([f.amplitude.get(zone, 0.0) for f in transient_frames])
            candidate = self._candidates.get(zone)

            # Stillness is measured over frames **after** the transient, never
            # over a window that still contains it. Measuring across it reads
            # the fall itself as movement, which drops the candidate one tick
            # after it is created - the person is on the floor and the agent
            # has just concluded they got up.
            if candidate is None:
                post = recent
            else:
                post = [f for f in recent if f.captured_at > candidate.at]
                if len(post) < max(4, int(rate_hz * TRANSIENT_WINDOW_S)):
                    # Too soon to judge. Nothing is said during this gap, which
                    # is the point of the debounce.
                    continue
            still = rms([f.amplitude.get(zone, 0.0) for f in post])

            # 1. A new transient. Recorded, not announced. At this instant a
            #    fall, a sit and a flop onto a bed are the same measurement.
            if candidate is None and fast >= TRANSIENT_RMS:
                self._candidates[zone] = Candidate(zone=zone, at=now, peak_rms=fast)
                continue
            if candidate is None:
                continue

            # 2. Movement resumed. They got up, or they were never down. Drop
            #    it silently: a retracted alert is a trust cost and there was
            #    never anything to retract.
            if still > STILL_RMS and not candidate.confirmed:
                del self._candidates[zone]
                continue

            # 3. Stillness holding. Start the debounce clock on the first still
            #    tick after the transient, not on the transient itself.
            if candidate.still_since is None and still <= STILL_RMS:
                candidate.still_since = now
            if candidate.still_since is None:
                continue

            held_s = (now - candidate.still_since).total_seconds()
            if not candidate.confirmed and held_s < DEBOUNCE_S:
                # Deliberately silent. The whole point of the debounce is that
                # nothing leaves this agent during it.
                continue

            # 4. Confirmed. The clinical clock runs from the transient.
            candidate.confirmed = True
            down_s = (now - candidate.at).total_seconds()
            breathing = bool(vitals.get(zone) and vitals[zone].breathing)

            if not breathing:
                # The cross-check failed, and this is the case to be most
                # careful with. Absence of a respiration signature is not
                # absence of a person, so this does not become "not breathing" -
                # it becomes an escalated uncertainty, which is what the brief
                # asks for.
                unknowns.append(
                    Unknown(
                        field="people.respiration",
                        zone_scope=zone,
                        reason=(
                            "A confirmed collapse in a zone where no respiration signature is "
                            "currently resolvable. This is NOT a finding that the person is not "
                            "breathing - shallow breathing and range limits look identical. It "
                            "is the most urgent uncertainty this system can produce."
                        ),
                    )
                )

            assertions.append(
                Assertion(
                    field="people.collapse_detected",
                    value="true",
                    zone_scope=zone,
                    severity_ceiling=Severity.DISPATCHABLE,
                    confidence=0.8 if breathing else 0.6,
                    basis=(
                        f"A {candidate.peak_rms:.2f} RMS transient followed by {held_s:.0f}s "
                        f"below the {STILL_RMS} movement floor. The 'followed by' is the "
                        "detection: the transient alone is also a person sitting down fast. "
                        + (
                            "Respiration is still resolvable in this zone."
                            if breathing
                            else "No respiration signature is currently resolvable here."
                        )
                    ),
                    provenance=provenance,
                )
            )
            assertions.append(
                Assertion(
                    field="people.still_down_s",
                    value=f"{down_s:.0f}",
                    zone_scope=zone,
                    severity_ceiling=Severity.DISPATCHABLE,
                    confidence=0.9,
                    basis=(
                        f"{down_s:.0f} seconds since the transient, measured from the fall and "
                        "not from the detection. 53% of older fall patients are still on the "
                        "floor when the ambulance arrives; this is the number that changes that."
                    ),
                    provenance=provenance,
                )
            )
            if down_s >= LONG_LIE_S:
                assertions.append(
                    Assertion(
                        field="people.long_lie",
                        value="true",
                        zone_scope=zone,
                        severity_ceiling=Severity.DISPATCHABLE,
                        confidence=0.9,
                        basis=(
                            f"Down {down_s / 60.0:.0f} minutes. A long lie is clinically defined "
                            "as being unable to get up for more than one hour, and half of "
                            "those who lie that long die within six months even absent injury "
                            "from the fall itself."
                        ),
                        provenance=provenance,
                    )
                )

        if not any(a.field == "people.collapse_detected" for a in assertions):
            assertions.append(
                Assertion(
                    field="people.collapse_detected",
                    value="false",
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=0.7,
                    basis=(
                        f"No transient followed by sustained stillness in any zone. "
                        f"{len(self._candidates)} candidate(s) in debounce."
                    ),
                    provenance=provenance,
                )
            )
        return assertions, unknowns
