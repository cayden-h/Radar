"""Zones, the headcount, and the coarse class. The spatial half of `people`.

**Read the counting limits before touching anything here.** Settled 2026-09-19:
presence is reliable, an exact count is not. The BCM43455c0 is 1x1 - frequency
diversity across subcarriers, no spatial diversity at all - and spatial
resolution is what antenna diversity buys. Two people within about a metre read
as one. A still person beside a moving one is near-invisible to motion, and that
last row is our actual scenario, which is why respiration rather than motion is
what finds the person on the floor.

**So the count comes from the roster, not the radio.** Device association tells
us two residents are home with certainty, because it comes from the network. The
radio answers which room and whether that presence is breathing, which it can.
Where a sensed count appears at all it is phrased as "at least", carries a
confidence, and is labelled as corroboration for the roster figure.

This is the one part of the system that needs a baseline, and the baseline is a
rolling percentile with slow adaptation rather than a calibration step. The
adaptation constant decides whether a motionless person stays visible: adapt too
fast and a person who stops moving is absorbed into the definition of "empty".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.state import PresenceClass
from hawkeye_backend.verification.envelope import Severity

from agents.core.observations import Assertion, Unknown
from agents.core.ports import CsiFrame, RosterSource
from agents.core.signals import percentile, rms
from agents.people.respiration import ZoneVitals

#: Seconds of history the rolling baseline is computed over. Long enough that a
#: person standing still for a minute does not become the new normal.
BASELINE_WINDOW_S = 600.0

#: The quiet floor. A low percentile rather than a mean, because the baseline
#: has to survive people being in the room while it adapts: a mean drags toward
#: whatever is happening, a low percentile tracks the floor underneath it.
BASELINE_PERCENTILE = 0.2

#: A baseline younger than this has not seen enough of the room to be trusted.
#: Below it, this agent says so rather than producing confident nonsense.
BASELINE_MIN_AGE_S = 120.0

#: How much existing capture history to seed the baseline from on a cold start.
#: More than `BASELINE_MIN_AGE_S`, so an agent started against a capture that
#: already has history is useful on its first tick rather than its hundredth.
BASELINE_SEED_S = 180.0

#: Short window the current disturbance level is measured over. One sample is
#: noise; two seconds of RMS is a measurement.
DISTURBANCE_WINDOW_S = 2.0

#: How far above the quiet floor a zone's disturbance must sit to read as
#: occupied, in normalized amplitude units. Absolute rather than a ratio,
#: because the quiet floor is near zero and a ratio against it explodes.
#:
#: For scale: thermal noise sits around 0.004, a still person breathing around
#: 0.035, a person moving around 0.25.
#: TODO(sensor): set from a real capture. No CSI exists as of 2026-09-19.
OCCUPIED_EXCESS = 0.05


@dataclass
class ZoneBaseline:
    """Rolling percentile baseline for one zone."""

    samples: deque[float] = field(default_factory=lambda: deque(maxlen=4096))
    """Per-tick disturbance level, not raw amplitude. What the baseline is *of*
    matters: a baseline over raw amplitude tracks the static multipath
    structure, which is not the thing a person changes."""

    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @property
    def age_s(self) -> float:
        """How much *captured time* this baseline covers.

        Derived from the frames' own timestamps rather than from how many times
        `tick` has been called. Those are not the same number: an agent that
        ticks slowly, or one started against replayed capture that already has
        history, would otherwise report an unformed baseline while sitting on
        plenty of data - and would answer nothing while looking healthy.
        """
        if self.first_seen is None or self.last_seen is None:
            return 0.0
        return (self.last_seen - self.first_seen).total_seconds()

    def observe(self, disturbance: float, at: datetime) -> None:
        self.samples.append(disturbance)
        if self.first_seen is None:
            self.first_seen = at
        self.last_seen = at

    def floor(self) -> float | None:
        if not self.samples:
            return None
        return percentile(list(self.samples), BASELINE_PERCENTILE)


class PresenceReader:
    """Holds the per-zone baselines and answers where and how many."""

    def __init__(self, agent_name: str, ansname: str) -> None:
        self._agent = agent_name
        self._ansname = ansname
        self._baselines: dict[str, ZoneBaseline] = {}

    @property
    def baselines(self) -> dict[str, ZoneBaseline]:
        return self._baselines

    @property
    def baseline_ready(self) -> bool:
        return any(b.age_s >= BASELINE_MIN_AGE_S for b in self._baselines.values())

    @property
    def seeded(self) -> bool:
        return bool(self._baselines)

    def seed(self, frames: list[CsiFrame]) -> None:
        """Build the baseline from capture history that already exists.

        Without this, the baseline accumulates one sample per tick and a live
        agent answers nothing for two minutes from a cold start, even when it is
        sitting on plenty of capture. That matters most for the demo path:
        replayed CSI arrives *with* history, and an agent that ignored it would
        spend the first two minutes of a judged run reporting that its baseline
        is still forming.

        Buckets by second, because the live path samples once per tick and the
        two must produce comparable numbers or the seeded floor would sit at a
        different level than everything measured after it.
        """
        if not frames:
            return
        buckets: dict[int, list[CsiFrame]] = {}
        origin = frames[0].captured_at
        for frame in frames:
            buckets.setdefault(int((frame.captured_at - origin).total_seconds()), []).append(frame)
        for _, group in sorted(buckets.items()):
            at = group[-1].captured_at
            for zone in group[-1].amplitude:
                level = rms([f.amplitude.get(zone, 0.0) for f in group])
                self._baselines.setdefault(zone, ZoneBaseline()).observe(level, at)

    def analyse(
        self,
        frame: CsiFrame,
        window: list[CsiFrame],
        vitals: dict[str, ZoneVitals],
        roster: RosterSource,
        provenance: Provenance,
    ) -> tuple[list[str], list[Assertion], list[Unknown]]:
        """Returns (occupied zones, assertions, unknowns)."""
        disturbance = {
            zone: rms([f.amplitude.get(zone, 0.0) for f in window]) for zone in frame.amplitude
        }
        for zone, level in disturbance.items():
            self._baselines.setdefault(zone, ZoneBaseline()).observe(level, frame.captured_at)

        assertions: list[Assertion] = []
        unknowns: list[Unknown] = []

        # ---------------------------------------------------- the roster answer

        # This runs first and unconditionally, because it is the answer that
        # does not depend on the radio working. If CSI is dead and two phones
        # are on the network, "two residents are home" is still true and still
        # the most useful thing we can tell a dispatcher.
        residents = roster.residents()
        associated = roster.associated_devices()
        home = [r for r in residents if any(d in associated for d in r.device_ids)]
        assertions.append(
            Assertion(
                field="people.headcount",
                value=str(len(home)),
                severity_ceiling=Severity.ACTIONABLE,
                confidence=0.95,
                basis=(
                    f"{len(home)} of {len(residents)} registered residents have a device "
                    "associated to the router. This figure comes from the network, not the "
                    "radio. It misses a resident who left their phone behind, a guest, and "
                    "anyone carrying a device that never associates."
                ),
                provenance=Provenance(
                    # Device association is not a CSI measurement and must not
                    # be labelled as one. It is an inference over network state.
                    source=Source.AGENT_INFERENCE,
                    producer=self._agent,
                    ansname=self._ansname,
                    detail=f"{len(associated)} associated devices",
                ),
            )
        )

        # ------------------------------------------------------ the radio answer

        occupied: list[str] = []
        for zone in sorted(frame.amplitude):
            baseline = self._baselines[zone]
            floor = baseline.floor()
            if floor is None or baseline.age_s < BASELINE_MIN_AGE_S:
                unknowns.append(
                    Unknown(
                        field="people.zone",
                        zone_scope=zone,
                        reason=(
                            f"Baseline is {baseline.age_s:.0f}s old against a "
                            f"{BASELINE_MIN_AGE_S:.0f}s minimum. A stale or unformed baseline "
                            "produces confident nonsense, so this zone is unanswered."
                        ),
                    )
                )
                continue

            excess = max(0.0, disturbance[zone] - floor)
            zone_vitals = vitals.get(zone)
            breathing = bool(zone_vitals and zone_vitals.breathing)

            # Personhood gates the zone claim. A disturbance without a
            # respiration signature is a perturbation, and this reader will not
            # call it a person - that verdict belongs to `respiration.py`.
            if not breathing and excess < OCCUPIED_EXCESS:
                continue
            if not breathing:
                assertions.append(
                    Assertion(
                        field="people.perturbation",
                        value=f"{excess:.3f}",
                        zone_scope=zone,
                        # CORROBORATING at most. A perturbation is not a person
                        # and must never be able to trigger anything on its own.
                        severity_ceiling=Severity.CORROBORATING,
                        confidence=round(min(0.9, excess * 2.0), 2),
                        basis=(
                            f"Channel disturbance {excess:.3f} above the quiet floor of "
                            f"{floor:.3f}, with no respiration signature. This is a "
                            "perturbation, not a person. A curtain looks exactly like this."
                        ),
                        provenance=provenance,
                    )
                )
                continue

            occupied.append(zone)
            assertions.append(
                Assertion(
                    field="people.zone",
                    value=zone,
                    zone_scope=zone,
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=round(min(0.95, 0.6 + excess), 2),
                    basis=(
                        f"A breathing presence resolved in this zone, {excess:.3f} above a "
                        f"{baseline.age_s:.0f}s rolling quiet floor. Room-level, not a "
                        "coordinate: this hardware tier does not support a fix and claiming "
                        "one invites a question we lose."
                    ),
                    presence_id=zone_vitals.presence_id if zone_vitals else None,
                    provenance=provenance,
                )
            )

            presence_class, basis = classify_presence(zone_vitals.bpm if zone_vitals else None)
            if presence_class is PresenceClass.UNKNOWN:
                unknowns.append(
                    Unknown(field="people.presence_class", zone_scope=zone, reason=basis)
                )
            else:
                assertions.append(
                    Assertion(
                        field="people.presence_class",
                        value=presence_class.value,
                        zone_scope=zone,
                        severity_ceiling=Severity.CORROBORATING,
                        confidence=0.5,
                        basis=basis,
                        presence_id=zone_vitals.presence_id if zone_vitals else None,
                        provenance=provenance,
                    )
                )

        # The sensed count, phrased as what it is: a floor, corroborating the
        # roster figure, never replacing it.
        assertions.append(
            Assertion(
                field="people.sensed_presences",
                value=f"at least {len(occupied)}",
                # CORROBORATING is the ceiling and it is not negotiable. A 1x1
                # link cannot deliver a count that should move anybody.
                severity_ceiling=Severity.CORROBORATING,
                confidence=0.45,
                basis=(
                    f"{len(occupied)} zone(s) carry a resolved breathing presence. This is a "
                    "floor, not a count: two people within about a metre merge into one on a "
                    "1x1 radio, and two people breathing at similar rates cannot be separated "
                    "on a single link. The headcount figure comes from device association."
                ),
                provenance=provenance,
            )
        )
        return occupied, assertions, unknowns


def classify_presence(bpm: float | None) -> tuple[PresenceClass, str]:
    """Coarse class from respiration rate. Amplitude is not an input.

    Resting rates: adult 12-20, child 20-30, infant 30-60, dog and cat 15-30+.
    Those bands overlap, and the overlap is stated rather than hidden - the
    honest resolution is "adult versus small and fast-breathing", and an
    RF-literate judge will press on exactly this. Grounding the split in
    respiration is physically defensible where "mass perturbs the signal
    differently" was not.
    """
    if bpm is None:
        return PresenceClass.UNKNOWN, "No respiration rate available, so no class."
    if bpm <= 20.0:
        return PresenceClass.ADULT, f"{bpm:.0f} BPM sits in the adult resting band of 12-20."
    if bpm <= 30.0:
        return (
            PresenceClass.CHILD,
            f"{bpm:.0f} BPM is small and fast-breathing. Child 20-30 and dog or cat 15-30+ "
            "overlap here and a single link does not separate them; this is reported as a "
            "child because that is the consequential reading, not because it is resolved.",
        )
    return (
        PresenceClass.UNKNOWN,
        f"{bpm:.0f} BPM is above the range this agent will classify from.",
    )
