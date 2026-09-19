"""The seams. Everything an agent reads that it does not compute itself.

Each port is a Protocol with at least one honest implementation behind it. The
point of the indirection is stated in `docs/swapping-in-real-parts.md`: a
simulated input must be swappable for a real one without anything above the
interface changing, and it must be *visible* which one is in use.

`ObservationSource` is the one to look at twice. It is how an agent reads
another agent's output, and right now the only implementation is
`LocalMesh`, which hands over the object in memory. That is not the
architecture - the architecture is nine independently registered agents
verifying each other over ANS on every hop. `LocalMesh` exists so the
domain logic can be written and tested before that transport exists, and it is
named so that nobody mistakes it for the real thing.

**Do not let `LocalMesh` survive into the demo.** An in-process call
verifies nothing, and the submission is the verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from agents.core.observations import AgentObservation


@dataclass(frozen=True)
class CsiFrame:
    """One CSI measurement, reduced to what the agents actually reason over.

    Not raw subcarriers. `sensor/` owns the firmware, the capture, and the
    per-subcarrier amplitude series; what crosses this line is the derived
    per-zone channel energy, because that is the last point where the two sides
    can agree on units.

    `amplitude` is per-zone mean normalized channel amplitude, referenced to the
    rolling baseline where one exists. The dict is keyed by zone id.

    **The rate matters more than anything else here.** CSI only updates when
    frames cross the monitored channel. Without a traffic generator you get
    beacons at roughly 10 Hz, which barely resolves breathing and never resolves
    heart rate or a fall transient - with every component reporting healthy.
    `sequence` and `captured_at` are carried so an agent can notice that itself
    rather than trusting a health flag. See sensor/CLAUDE.md.
    """

    captured_at: datetime
    sequence: int
    amplitude: dict[str, float]
    """zone id -> normalized channel amplitude."""

    rate_hz: float
    """Observed frame rate. Below ~20 Hz, respiration is marginal and heart rate is gone."""

    source: str
    """`nexmon-csi`, `replay-csi` or `ruview-sim`. Becomes Provenance.source."""

    baseline_age_s: float | None = None
    """Age of the rolling baseline, where the producer maintains one. None means no baseline."""


@runtime_checkable
class CsiFeed(Protocol):
    """Where CSI frames come from. Implemented in `sensor/`, stubbed here."""

    def latest(self) -> CsiFrame | None:
        """The most recent frame, or None if nothing has arrived yet."""
        ...

    def window(self, seconds: float) -> list[CsiFrame]:
        """Frames from the last `seconds`, oldest first. Empty if none.

        Respiration needs a window, not a sample: a breath is 2 to 10 seconds
        long and the band of interest is 0.1-0.5 Hz, so the shortest useful
        window is around 30 seconds.
        """
        ...


@dataclass(frozen=True)
class GasReading:
    """One reading from whatever is measuring the air. Simulated today."""

    co_ppm: float
    smoke: bool
    captured_at: datetime
    source: str
    """`mq7-gpio` when a real sensor exists. `demo-trigger` today, which computes to simulated."""


@runtime_checkable
class GasSensor(Protocol):
    """A carbon monoxide sensor.

    No MQ-7 was purchased, so the only implementation ramps through the UL 2034
    bands. Swapping in the real part is writing one class here and changing the
    `source` string; nothing above this line moves. That is the whole claim, and
    it is checkable by reading the code, which is more than most demos offer.
    """

    def read(self) -> GasReading: ...


@dataclass(frozen=True)
class Resident:
    """A registered member of the household. Configuration, not discovery.

    A home system knows who lives there. That is what makes the intruder rule
    stateable on stage, and it is why there is no learning step here.
    """

    resident_id: str
    label: str
    """Never a real name. Card and log are world-readable; `resident_1` is not a privacy leak."""

    device_ids: tuple[str, ...]
    """Opaque device handles. Randomized MACs are stable per-network, so a phone
    presents a consistent address on the home router."""


@runtime_checkable
class RosterSource(Protocol):
    """The household roster, and which of its devices are on the network now.

    The count comes from here, not from the radio. Device association tells us
    two residents are home with certainty, because it comes from the network.
    The radio then only has to answer which room and whether that presence is
    breathing, which it can. See docs/research/identity.md.
    """

    def residents(self) -> tuple[Resident, ...]: ...

    def associated_devices(self) -> frozenset[str]:
        """Device ids currently associated to the router."""
        ...


@runtime_checkable
class ObservationSource(Protocol):
    """How one agent reads another's latest observation.

    **This is the transport seam and it is currently unbridged.** A real
    implementation verifies before it returns: mTLS handshake, JWS over the
    canonical payload, bindings, schema version, then the profile gate, in that
    order, and it discards rather than raising when a check fails. Nothing
    downstream ever sees an unverified field.

    `hawkeye_backend.verification.ClaimVerifier` already implements that
    pipeline, with all thirteen battery shapes as passing tests. Do not write a
    second verifier; the real implementation of this port wraps that one.
    """

    def observation(self, slug: str) -> AgentObservation | None:
        """The named agent's latest observation, or None if it has not produced one.

        None is a real answer and must stay distinguishable from an empty
        observation. An agent that is unreachable and an agent that has nothing
        to report are different facts, and the second one is not an emergency.
        """
        ...


class LocalMesh:
    """In-process stand-in for `ObservationSource`. Verifies nothing.

    Every agent writes its latest observation here and reads its dependencies
    from here, so the nine can run in one process and the domain logic can be
    exercised end to end before any wire exists.

    What this is not: the architecture. Nine agents sharing a dict have no
    identity, no certificates, no signatures and no discard path, which means
    they demonstrate exactly none of what this project is for. Replace before
    the demo, and until then treat a passing test against `LocalMesh` as
    evidence about the domain logic only.
    """

    def __init__(self) -> None:
        self._latest: dict[str, AgentObservation] = {}

    def publish(self, observation: AgentObservation) -> None:
        slug = observation.agent.removeprefix("agents/")
        self._latest[slug] = observation

    def observation(self, slug: str) -> AgentObservation | None:
        return self._latest.get(slug)
