"""agents/people - who is in the building, where, and what state each one is in.

**The load-bearing agent.** It is the only consumer of the CSI stream and it
answers every question about occupants: how many, in which room, whether each
one is a person at all, whether they are breathing, whether they are moving, and
how long it has been since a breathing signature was last resolvable on one of
them.

Merged on 2026-09-19 from what were three agents: occupancy, biometrics and
collapse. Fall detection was dropped later the same day, so what remains is
personhood, location and responsiveness.

The merge is the right shape, and the reason is not that three agents were too
many - it is that they were one question asked three ways:

- They read the **same CSI window**. Three agents meant three copies of the same
  frames and three chances for them to disagree about what the radio said.
- They share **one baseline**, and the baseline is the expensive, fragile,
  slow-to-warm piece. Splitting it bought three deployments and nothing else.
- The dependency chain ran one way and was total: occupancy could not name a
  presence without the personhood verdict, and collapse - which no longer
  exists - could not interpret a transient without knowing whether the thing
  that fell was breathing. Three agents in a fixed chain with no branch is one
  agent with three steps. That last one is history rather than a description
  of the code: nothing here reads falls any more.

What it is **not** is a reduction in what gets verified. The split that carries
the ANS story is between the agent that senses and the agent that decides, and
that line is `people` to `master` - it is untouched, and it is the hop where a
claim becomes something a dispatcher hears.

The two readers run in a fixed order each tick, because the second depends on
the first:

    respiration  ->  is this a person, breathing at what rate, moving or not
    presence     ->  which zone, how many, what coarse class

Everything the agent will not claim is on its card, published, and each line has
a test. See `docs/research/agent-briefs.md`.
"""

from __future__ import annotations

from hawkeye_backend.models.common import Provenance, Source

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation
from agents.core.ports import CsiFeed, RosterSource
from agents.people.presence import BASELINE_SEED_S, DISTURBANCE_WINDOW_S, PresenceReader
from agents.people.respiration import RESPIRATION_HI_HZ, WINDOW_S, RespirationReader


class PeopleAgent(Agent):
    """One CSI consumer, two readers, one observation."""

    interval_s = 1.0

    def __init__(self, feed: CsiFeed, roster: RosterSource) -> None:
        super().__init__(identity("people"))
        self._feed = feed
        self._roster = roster
        self._respiration = RespirationReader(self.identity.name)
        self._presence = PresenceReader(self.identity.name, self.identity.ansname)

    def tick(self) -> AgentObservation:
        frames = self._feed.window(WINDOW_S)
        if not frames:
            return self.blind(
                "people.personhood",
                "No CSI frames. Nothing to say about anybody, which is different from "
                "saying the building is empty.",
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
        if rate_hz < 2.0 * RESPIRATION_HI_HZ:
            return self.blind(
                "people.respiration",
                f"Frame rate {rate_hz:.1f} Hz is below Nyquist for a 30 BPM breath. "
                "Start the traffic generator; beacons alone are not enough.",
            )

        # 1. Personhood first. Everything below is conditioned on it.
        vitals, assertions, unknowns = self._respiration.analyse(frames, provenance)

        # 2. Zones, headcount, class.
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
            newest, window or frames, vitals, self._roster, provenance
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
                f"{len(occupied)} zone(s) resolved, {len(vitals)} zone(s) analysed, "
                f"{rate_hz:.1f} Hz"
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
