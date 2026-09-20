"""The seams. Everything an agent reads that it does not compute itself.

Each port is a Protocol with at least one honest implementation behind it. The
point of the indirection is stated in `docs/swapping-in-real-parts.md`: a
simulated input must be swappable for a real one without anything above the
interface changing, and it must be *visible* which one is in use.

`ObservationSource` is the one to look at twice. It is how an agent reads
another agent's output, and right now the only implementation is
`LocalMesh`, which hands over the object in memory. That is not the
architecture - the architecture is five independently registered agents
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
    """`nexmon-csi`, `replay-csi`, `ruview-sim` or `wifi-rssi`. Becomes Provenance.source."""

    baseline_age_s: float | None = None
    """Age of the rolling baseline, where the producer maintains one. None means no baseline."""

    motion_state: str | None = None
    """Already-classified motion verdict, or None for a raw CSI frame.

    None on every CSI frame (nexmon, replay, ruview-sim), which keeps the
    existing amplitude-and-baseline path unchanged. On the `wifi-rssi` modality
    this carries the classifier's *confirmed* verdict - `"active"` or `"absent"`
    - rather than a raw amplitude to be re-thresholded downstream.

    The distinction is deliberate. The RSSI path already runs a full
    collector->features->classifier pipeline (EMA baseline, ratio threshold,
    hysteresis debounce) tuned for a single scalar link measured off CoreWLAN.
    `presence`'s own percentile baseline and OCCUPIED_EXCESS threshold are tuned
    for per-subcarrier CSI amplitude, and re-running that noise math on an RSSI
    energy figure it was never scaled against would just launder a good verdict
    through a wrong yardstick. So when this field is set, the reader trusts it
    and skips its own baseline; `amplitude` is still carried for the record and
    the feed, but it is not what decides the claim."""


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


@dataclass(frozen=True)
class TransportRejection:
    """A claim that arrived and did not survive verification.

    These never reach master's gate. They are carried anyway, because "it tells
    you what it discarded" is the sentence that carries the submission and a
    claim thrown away silently at the transport layer is exactly the kind of
    discard that would not appear in the feed.
    """

    issuer: str
    field: str
    check: str
    """The named check that failed: `claim_signature`, `proof_nonce`, `known_issuer`."""

    reason: str


@dataclass(frozen=True)
class FetchedObservation:
    """What came back from one agent, and what happened on the way.

    `envelope_verified` is per fetch, not per process. Trust is a property of an
    agent at an instant: one that answered a verified challenge a minute ago may
    fail the next one because its certificate drifted, and a flag set once at
    startup cannot express that.
    """

    observation: AgentObservation
    envelope_verified: bool
    """True only when every claim arrived signed and verified against the key
    the producer registered. False for an in-process handoff, which verifies
    nothing and must not be allowed to look like it did."""

    rejected: tuple[TransportRejection, ...] = ()


@runtime_checkable
class ObservationSource(Protocol):
    """How one agent reads another's latest observation.

    A real implementation verifies before it returns: mTLS handshake where it is
    enforced, then JWS over the canonical payload, bindings, schema version, the
    challenge, and the profile gate, in that order, discarding rather than
    raising when a check fails. Nothing downstream ever sees an unverified field.

    `hawkeye_backend.verification.ClaimVerifier` implements that pipeline, with
    all thirteen battery shapes plus the challenge probes as passing tests. Do
    not write a second verifier; an implementation of this port wraps that one.
    """

    def fetch(self, slug: str) -> FetchedObservation | None:
        """The named agent's current answer, or None if it has none.

        None is a real answer and must stay distinguishable from an empty
        observation. An agent that is unreachable and an agent that has nothing
        to report are different facts, and the second one is not an emergency.
        """
        ...


class LocalMesh:
    """In-process stand-in for `ObservationSource`. Verifies nothing.

    Every agent writes its latest observation here and reads its dependencies
    from here, so the five can run in one process and the domain logic can be
    exercised end to end with no network.

    What this is not: the architecture. Five agents sharing a dict have no
    identity, no certificates, no signatures and no discard path, which means
    they demonstrate exactly none of what this project is for.

    **It cannot quietly pass as the real thing**, and that is deliberate:
    `fetch` returns `envelope_verified=False`, master records that as a failed
    check on every claim, and `caller` then refuses to speak any of them. If a
    demo ever shows claims being spoken while this class is in use, something
    has been loosened that should not have been.
    """

    def __init__(self) -> None:
        self._latest: dict[str, AgentObservation] = {}

    def publish(self, observation: AgentObservation) -> None:
        slug = observation.agent.removeprefix("agents/")
        self._latest[slug] = observation

    def fetch(self, slug: str) -> FetchedObservation | None:
        observation = self._latest.get(slug)
        if observation is None:
            return None
        return FetchedObservation(observation=observation, envelope_verified=False)

    def observation(self, slug: str) -> AgentObservation | None:
        """Convenience for tests that only care about the domain logic."""
        return self._latest.get(slug)
