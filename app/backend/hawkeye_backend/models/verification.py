"""The verification stream. A first-class API concept, not a log line.

"The agent that speaks to 911 only repeats claims it can cryptographically
verify. Everything else it discards, and it tells you what it discarded."

The app has to be able to show the refusal path, so DISCARDED carries the same
structure as ACCEPTED plus a stated reason. A discard is a product feature here,
not an error.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import utc_now


class TrustProfile(StrEnum):
    """Trust Index `recommendedProfile` policy hint.

    Consumed rather than reinvented. Using the track's own policy vocabulary is
    free credibility, and the mapping to what a claim may trigger is the table in
    agents/CLAUDE.md.
    """

    UNTRUSTED = "UNTRUSTED"
    READ_ONLY = "READ_ONLY"
    TRANSACTIONAL = "TRANSACTIONAL"
    FIDUCIARY = "FIDUCIARY"


class VerificationDecision(StrEnum):
    """What master did with a claim, given the source's profile.

    | Profile       | Decision            | Meaning                                        |
    |---------------|---------------------|------------------------------------------------|
    | UNTRUSTED     | DISCARDED           | Discards. Logs. Does not relay.                |
    | READ_ONLY     | CORROBORATION_ONLY  | Never the sole basis for a call.               |
    | TRANSACTIONAL | ATTRIBUTED          | Relayed as a reported observation, attributed. |
    | FIDUCIARY     | ASSERTED            | Relayed as an assertion the system stands behind. |

    DISCARDED is also the decision when any check fails, whatever the profile.
    """

    ASSERTED = "ASSERTED"
    ATTRIBUTED = "ATTRIBUTED"
    CORROBORATION_ONLY = "CORROBORATION_ONLY"
    DISCARDED = "DISCARDED"


# The profile-to-decision table above, as data.
PROFILE_DECISION: dict[TrustProfile, VerificationDecision] = {
    TrustProfile.FIDUCIARY: VerificationDecision.ASSERTED,
    TrustProfile.TRANSACTIONAL: VerificationDecision.ATTRIBUTED,
    TrustProfile.READ_ONLY: VerificationDecision.CORROBORATION_ONLY,
    TrustProfile.UNTRUSTED: VerificationDecision.DISCARDED,
}


class TrustIndexScore(BaseModel):
    """Trust Index scores at the instant the claim was verified.

    Only integrity and identity are implemented upstream. Solvency, behavior and
    safety are hardcoded to 0 in the reference implementation, so they are
    nullable here rather than silently zero: a 0 that means "not implemented"
    and a 0 that means "scored zero" are different facts and the app must not
    conflate them. ans/CLAUDE.md names safety as the dimension we intend to ship.
    """

    integrity: float | None = Field(default=None, ge=0.0, le=1.0)
    identity: float | None = Field(default=None, ge=0.0, le=1.0)
    solvency: float | None = Field(default=None, ge=0.0, le=1.0)
    behavior: float | None = Field(default=None, ge=0.0, le=1.0)
    safety: float | None = Field(default=None, ge=0.0, le=1.0)
    unimplemented_dimensions: list[str] = Field(
        default_factory=list,
        description="Dimensions the Trust Index does not yet score. Null above, named here.",
    )

    # TODO(ans): confirm the exact response shape and score range of the Trust
    # Index scoring endpoint against
    # https://github.com/agentnameservice/agent-trust-discovery. Specifically:
    # (a) are dimension scores 0-1 or 0-100, (b) what is the JSON key for
    # recommendedProfile, (c) is there an overall/composite score field, and
    # (d) does the response distinguish "unimplemented" from "scored 0"? The
    # 0-1 range and the nullable dimensions above are this service's choice, not
    # a verified fact, and must be reconciled before the live client ships.


class SourceAgent(BaseModel):
    """The agent that made the claim."""

    name: str = Field(description="Agent directory name, e.g. 'agents/people'.")
    ansname: str = Field(description="The ANSName the claim was presented under.")
    certificate_version: str | None = Field(
        default=None,
        description=(
            "Version-bound certificate recording the code running at registration. A "
            "fingerprint that drifted mid-run is how code drift becomes detectable."
        ),
    )
    trust_index: TrustIndexScore | None = None
    recommended_profile: TrustProfile


class Claim(BaseModel):
    """One assertion a sensing agent made about the building."""

    claim_id: str
    statement: str = Field(description="Plain English, as caller would say it out loud.")
    field: str = Field(description="Which part of interior state it asserts, e.g. 'people.respiration'.")
    value: str = Field(description="The asserted value, rendered as a string for display.")
    presence_id: str | None = None


class VerificationCheck(BaseModel):
    """One check performed, and whether it passed.

    These are what makes DISCARDED legible on screen. "Untrusted" is a verdict;
    "certificate fingerprint differs from the one registered" is a reason.
    """

    name: str
    passed: bool
    detail: str


class VerificationResult(BaseModel):
    """A claim, who made it, what was checked, and what was decided."""

    verification_id: str
    incident_id: str | None = None
    checked_at: datetime = Field(default_factory=utc_now)
    claim: Claim
    agent: SourceAgent
    decision: VerificationDecision
    reason: str = Field(
        description="Why this decision. Required even on ASSERTED, so the stream reads the same both ways."
    )
    checks: list[VerificationCheck] = Field(default_factory=list)
    will_be_spoken: bool = Field(
        description="Whether agents/caller is permitted to repeat this claim to the operator."
    )
