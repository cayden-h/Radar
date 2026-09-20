"""agents/vision - is there a person in this room.

The camera answers personhood. That is the question the radio used to answer
with a respiration signature, and which the 2026-09-19 pivot deleted for being
unsupportable on a 1x1 link. It does not answer identity, because identity needs
enrolment and a database we deliberately do not have.

This agent is thin on purpose. Detection, tracking, lighting and recording all
live in `vision/hawkeye_vision/`, which has its own suite. What is here is the
ANS surface: an identity, a scope, a provenance label, and the distinction
between not seeing anybody and not being able to see.

**The scope is carried in the data.** One fixed camera sees one room, and every
assertion carries that room in `zone_scope`. Root CLAUDE.md requires that a
scoped claim must not be presentable as an unscoped one by accident, and a field
on the assertion is the only version of that which survives being passed around.

**The source is supplied, not assumed.** `Source` distinguishes a live Logitech
on USB from replayed footage from a generated fixture, and the difference is
what the app renders a "simulated" badge from. An agent that hardcoded
`CAMERA_UVC` would let a test rig present as a camera, which is the exact
failure `Source` was made a closed set to prevent.
"""

from __future__ import annotations

from typing import Protocol

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity
from hawkeye_vision.occupancy import Occupancy

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion, Unknown

#: The only sources a vision claim may carry. A claim from this agent labelled
#: `nexmon-csi` or `servo-gpio` would be a lie about which sensor produced it,
#: so the set is checked at construction rather than trusted.
CAMERA_SOURCES: frozenset[Source] = frozenset(
    {Source.CAMERA_UVC, Source.REPLAY_VIDEO, Source.CAMERA_SIM}
)


class OccupancySource(Protocol):
    """The capture loop, reduced to the one question this agent asks it."""

    def occupancy(self) -> Occupancy:
        """The verdict for the most recent frame."""
        ...


class VisionAgent(Agent):
    """Personhood from the camera, scoped to the one room it covers."""

    interval_s = 1.0

    def __init__(self, source: OccupancySource, *, room: str, source_kind: Source) -> None:
        super().__init__(identity("vision"))
        if source_kind not in CAMERA_SOURCES:
            raise ValueError(
                f"{source_kind!r} is not a camera source. A vision claim must carry one of "
                f"{sorted(s.value for s in CAMERA_SOURCES)}, because the source is what the "
                "app renders a simulated badge from."
            )
        self._source = source
        self._room = room
        self._source_kind = source_kind

    def tick(self) -> AgentObservation:
        verdict = self._source.occupancy()

        if verdict is Occupancy.TRACKER_UNAVAILABLE:
            # Deliberately not an assertion. `tracker_unavailable` as a *value*
            # is something a careless consumer can compare against and get a
            # truthy answer from; an unknown cannot be mistaken for a reading.
            return AgentObservation(
                agent=self.identity.name,
                ansname=self.identity.ansname,
                unknowns=(
                    Unknown(
                        field="vision.occupancy",
                        zone_scope=self._room,
                        reason=(
                            "The detector could not look: no weights loaded or no frames "
                            "arriving. Zero detections from a blind camera is not evidence "
                            "that the room is empty."
                        ),
                    ),
                ),
            )

        return AgentObservation(
            agent=self.identity.name,
            ansname=self.identity.ansname,
            assertions=(
                Assertion(
                    field="vision.occupancy",
                    value=verdict.value,
                    zone_scope=self._room,
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=0.9,
                    basis=(
                        f"Object detection over the {self._room} camera. Personhood only: "
                        "this says a human is in frame, never which human, and never how "
                        "many."
                    ),
                    provenance=Provenance(
                        source=self._source_kind,
                        producer=self.identity.name,
                        ansname=self.identity.ansname,
                        detail=f"camera:{self._room}",
                    ),
                ),
            ),
        )
