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

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion, Unknown
from agents.core.ports import CsiFeed, RosterSource
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


def _source(feed_source: str) -> Source:
    """Feed's source string to the closed Source enum.

    Unknown strings fall to RUVIEW_SIM, which classifies as simulated. Failing
    toward "simulated" is the only safe direction: mislabelling a synthetic
    reading as measured is the exact failure the honesty rule exists to prevent.
    """
    try:
        return Source(feed_source)
    except ValueError:
        return Source.RUVIEW_SIM
