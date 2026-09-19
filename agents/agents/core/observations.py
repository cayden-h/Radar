"""What an agent produces: assertions, and the things it could not determine.

This is deliberately one step short of a claim envelope. An `Assertion` carries
everything about *what is being said* - the field, the value, the zone it is
scoped to, the most it may ever trigger, and where the number came from. It
carries nothing about *who it is being said to*: no audience, no incident id, no
nonce, no expiry, no signature.

Those are the binding fields, and binding is a property of a conversation rather
than of an observation. When the transport lands, wrapping an `Assertion` in a
`ClaimEnvelope` is a constructor call with the bindings supplied by whoever is
sending it. Doing it in that order keeps the sensing logic from quietly
acquiring opinions about the wire.

`unknowns` is the other half and is not decoration. Every brief in
`docs/research/agent-briefs.md` has a "must not claim" section, and an agent
that has nothing to say about a zone needs somewhere to say so. An empty
assertion list with an empty `unknowns` list means "nothing is happening"; an
empty assertion list with a populated one means "I cannot tell", and those are
different facts that a dispatcher would act on differently.
"""

from __future__ import annotations

from datetime import datetime

from hawkeye_backend.models.common import Provenance, utc_now
from hawkeye_backend.verification.envelope import Severity
from pydantic import BaseModel, ConfigDict, Field


class Assertion(BaseModel):
    """One thing an agent is prepared to say about the building."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="Interior-state field, e.g. 'people.respiration'.")
    value: str = Field(description="The asserted value, as a string. Envelope carries strings.")
    zone_scope: str = Field(
        default="site",
        description=(
            "Room-level zone this is about, or 'site' for a building-wide fact. A kitchen "
            "claim cannot justify a bedroom dispatch, which is why scope is on the claim."
        ),
    )
    severity_ceiling: Severity = Field(
        default=Severity.INFORMATIONAL,
        description=(
            "The most this assertion may ever trigger. Set by the producing agent from "
            "what it actually knows, then capped again by master from the producer's "
            "trust profile. A ceiling is not a floor: the cap wins."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)
    basis: str = Field(
        description=(
            "Plain English: what this was derived from. Read aloud by caller when a "
            "dispatcher asks how we know, and shown in the app's verification feed."
        )
    )
    presence_id: str | None = Field(
        default=None,
        description="Stable within a session only. We do not do re-identification.",
    )
    provenance: Provenance = Field(
        description=(
            "Required, no default. `source_class` and `simulated` are computed from "
            "`source`, so a producer cannot mislabel a simulated number as a measured one."
        )
    )


class Unknown(BaseModel):
    """Something this agent was asked about and cannot answer.

    "I don't know" must be available and must be used. An agent that invents an
    answer for a dispatcher is worse than one that admits a gap, and the gap has
    to survive the trip from the sensing agent to the voice to be admitted.
    """

    model_config = ConfigDict(frozen=True)

    field: str
    zone_scope: str = "site"
    reason: str = Field(description="Why not. 'No baseline yet' and 'out of range' are different.")


class AgentObservation(BaseModel):
    """Everything one agent has to say at one instant.

    Produced on every tick by every agent, whether or not anything is happening.
    All five run continuously; that is a requirement rather than an
    optimisation, and it is what lets the system notice things nobody asked it
    to look for.
    """

    model_config = ConfigDict(frozen=True)

    agent: str = Field(description="Directory name, e.g. 'agents/people'.")
    ansname: str
    observed_at: datetime = Field(default_factory=utc_now)
    assertions: tuple[Assertion, ...] = ()
    unknowns: tuple[Unknown, ...] = ()
    healthy: bool = Field(
        default=True,
        description=(
            "False when the agent is running but cannot do its job - no frames, stale "
            "baseline, missing upstream verdict. A component that reports healthy while "
            "producing nothing is the failure mode sensor/CLAUDE.md warns about twice."
        ),
    )
    note: str | None = None

    def value(self, field: str) -> str | None:
        """First asserted value for a field, or None. Convenience for consumers."""
        for assertion in self.assertions:
            if assertion.field == field:
                return assertion.value
        return None
