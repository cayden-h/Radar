"""agents/presence - something moved, and which room it moved in.

**Two facts, and deliberately no third.** The 2026-09-19 pivot cut respiration
sensing, and the 2026-09-20 shutter change moved personhood to the camera. What
is left of the radio is the part it could always support without a caveat
paragraph: a channel disturbance above a rolling quiet floor, resolved to a
room.

That is not a demotion, it is the correct scope. A 1x1 link answering "is this a
person" needed four caveats before a dispatcher could use it. A 1x1 link
answering "something moved in the living room" needs none, and it is enough to
open a shutter - which is the only thing this agent's output now triggers.

What used to be here and is not:

- **`respiration.py`**, deleted 2026-09-20. Personhood, breathing rate, heart
  rate and the responsiveness clock. The camera answers the one of those that
  mattered, and an officer can check the footage afterwards, which was never
  true of a breathing signature.
- **`people.headcount`**, which came from device association rather than from
  the radio. `intruder` does that arithmetic now, against the camera.
- **`people.presence_class`**, adult-versus-child from respiration rate. It had
  no input left once respiration went.

What it is **not** is a reduction in what gets verified. The split that carries
the ANS story is between the agent that senses and the agent that decides, and
that line is `presence` to `master` - untouched, and now the hop that decides
whether a lens is uncovered.

Everything the agent will not claim is on its card, published, and each line has
a test. See `docs/research/agent-briefs.md`.
"""

from __future__ import annotations

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion, Unknown
from agents.core.ports import CsiFeed, CsiFrame, RosterSource
from agents.presence.presence import (
    BASELINE_SEED_S,
    DISTURBANCE_WINDOW_S,
    MIN_RATE_HZ,
    WINDOW_S,
    PresenceReader,
)


class PresenceAgent(Agent):
    """One CSI consumer, one reader, one observation."""

    interval_s = 1.0

    def __init__(self, feed: CsiFeed, roster: RosterSource) -> None:
        super().__init__(identity("presence"))
        self._feed = feed
        self._roster = roster
        self._presence = PresenceReader(self.identity.name, self.identity.ansname)

    def tick(self) -> AgentObservation:
        frames = self._feed.window(WINDOW_S)
        if not frames:
            return self.blind(
                "presence.motion",
                "No CSI frames. Nothing to say about whether anything moved, which is "
                "different from saying nothing did.",
            )

        newest = frames[-1]

        # The RSSI modality arrives already classified. When the newest frame
        # carries a confirmed motion verdict, take it directly and skip both the
        # rate floor and the percentile baseline below: the wifi-rssi pipeline
        # (collector -> features -> classifier, with its own EMA baseline and
        # hysteresis) has already separated motion from noise on a signal our own
        # CSI-tuned math was never scaled against. Re-thresholding it here would
        # launder a good verdict through the wrong yardstick. A raw CSI frame
        # (nexmon, replay, ruview-sim) carries motion_state=None and falls
        # through to the unchanged path below.
        if newest.motion_state is not None:
            return self._rssi_tick(newest)

        rate_hz = newest.rate_hz
        provenance = Provenance(
            source=_source(newest.source),
            producer=self.identity.name,
            ansname=self.identity.ansname,
            detail=f"{len(frames)} frames over {WINDOW_S:.0f}s at {rate_hz:.1f} Hz",
        )

        # The rate check comes before any analysis. A slow feed produces a
        # confident-looking answer from data that cannot support it, and every
        # component downstream reports healthy while it happens. Name it here.
        if rate_hz < MIN_RATE_HZ:
            return self.blind(
                "presence.motion",
                f"Frame rate {rate_hz:.1f} Hz is below the {MIN_RATE_HZ:.0f} Hz floor this "
                "reader needs to separate motion from noise. Start the traffic generator; "
                "beacons alone are not enough.",
            )

        assertions: list[Assertion] = []
        unknowns: list[Unknown] = []

        #
        # On the first tick, seed the baseline from whatever capture already
        # exists rather than accumulating it one sample at a time. A cold start
        # against replayed CSI should be useful immediately; a cold start
        # against a live radio genuinely has no history and still waits.
        if not self._presence.seeded:
            self._presence.seed(self._feed.window(BASELINE_SEED_S))

        window = [
            f
            for f in frames
            if (newest.captured_at - f.captured_at).total_seconds() <= DISTURBANCE_WINDOW_S
        ]
        occupied, presence_assertions, presence_unknowns = self._presence.analyse(
            newest, window or frames, self._roster, provenance
        )
        assertions.extend(presence_assertions)
        unknowns.extend(presence_unknowns)

        return self.observe(
            assertions=tuple(assertions),
            unknowns=tuple(unknowns),
            # Unhealthy while the baseline is still forming. The zone answers
            # are unavailable until then and the agent says so rather than
            # reporting fine and answering nothing.
            healthy=self._presence.baseline_ready,
            note=(
                f"{len(occupied)} zone(s) with motion, {rate_hz:.1f} Hz"
                if self._presence.baseline_ready
                else "baseline still forming"
            ),
        )

    def _rssi_tick(self, newest: "CsiFrame") -> AgentObservation:
        """Emit a motion observation straight from the classifier's verdict.

        This is the RSSI modality's whole path. The `wifi-rssi` feed already ran
        the collector -> features -> classifier pipeline and handed us a confirmed
        `"active"`/`"absent"` state in `newest.motion_state`, so there is no
        baseline to seed, no rate floor to clear and no percentile to compute
        here. We translate the verdict into the same `presence.motion` shape the
        CSI path produces - one room, CORROBORATING ceiling, provenance stamped
        with the frame's source - so `master` cannot tell the two modalities apart
        by claim shape, only by the (honest) source label and confidence.

        `"active"` becomes a motion assertion scoped to the room. `"absent"`
        becomes an observation with no assertions and no unknowns, which is the
        protocol's way of saying "nothing is happening" - distinct from blind,
        which says "I cannot tell". The classifier separating motion from noise is
        exactly what lets us make that distinction confidently.
        """
        room = next(iter(newest.amplitude), "site")
        provenance = Provenance(
            source=_source(newest.source),
            producer=self.identity.name,
            ansname=self.identity.ansname,
            detail=f"wifi-rssi classifier verdict at {newest.rate_hz:.1f} Hz",
        )

        if newest.motion_state == "active":
            assertion = Assertion(
                field="presence.motion",
                value="true",
                zone_scope=room,
                # CORROBORATING at most, identical to the CSI path: a channel
                # perturbation is not a person and must never trigger anything on
                # its own. What it triggers is a shutter opening, and `master`
                # makes that call.
                severity_ceiling=Severity.CORROBORATING,
                # A confirmed, hysteresis-debounced verdict off a single link.
                # Fixed rather than derived: the classifier reports a state, not a
                # margin, and inventing a continuous confidence from a binary
                # would be dressing up precision the modality does not have. High
                # enough to reflect that the debounce already rejected a lone
                # noisy tick; short of the CSI path's ceiling because one RSSI
                # scalar cannot localise or corroborate the way subcarriers can.
                confidence=0.75,
                basis=(
                    "The WiFi-RSSI motion classifier reports a confirmed 'active' state: "
                    "link-quality variance and rate-of-change energy rose past its adaptive "
                    "baseline and held across the hysteresis window. Something moved in this "
                    "room. Whether it is a person is the camera's question, not the radio's."
                ),
                provenance=provenance,
            )
            return self.observe(
                assertions=(assertion,),
                healthy=True,
                note=f"motion in {room} (wifi-rssi, {newest.rate_hz:.1f} Hz)",
            )

        # "absent" (or any confirmed non-active verdict): the room is quiet. No
        # assertions, no unknowns - the classifier is telling us nothing is
        # happening, which is a different fact from being unable to tell.
        return self.observe(
            assertions=(),
            healthy=True,
            note=f"no motion in {room} (wifi-rssi, {newest.rate_hz:.1f} Hz)",
        )


def _source(feed_source: str) -> Source:
    """Feed's source string to the closed Source enum.

    `"wifi-rssi"` maps to `Source.WIFI_RSSI`, which classifies as MEASURED_LIVE:
    the RSSI feed genuinely measured the link. Every other known string resolves
    by its own value (`nexmon-csi`, `replay-csi`, `ruview-sim`).

    Unknown strings fall to RUVIEW_SIM, which classifies as simulated. Failing
    toward "simulated" is the only safe direction: mislabelling a synthetic
    reading as measured is the exact failure the honesty rule exists to prevent.
    """
    try:
        return Source(feed_source)
    except ValueError:
        return Source.RUVIEW_SIM
