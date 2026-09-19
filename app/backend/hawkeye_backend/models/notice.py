"""A notice: something the resident should know, that is not an incident.

`app/CLAUDE.md` already reserves the word - detections from the sensing agents
"surface here as alerts... An alert is information a person acts on. It is not a
call." An unexpected person is the clearest case of it.

This is on-thesis rather than a departure from it. Hawk Eye never calls 911 on
its own; the sensing agents detect, classify and *inform*, and a human decides
whether emergency services are needed. A notice is the inform step made to
actually arrive somewhere.

A notice carries `Provenance` like every other claim in this service, for the
same reason: a compromised sensing agent must not be able to buzz a resident's
phone at 3am any more than it can dial 911.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import Provenance, utc_now


class NoticeSeverity(StrEnum):
    """How loudly the app should render it. Never a dispatch decision."""

    INFO = "info"
    ATTENTION = "attention"


class Notice(BaseModel):
    """One thing the resident should know about."""

    notice_id: str
    severity: NoticeSeverity
    title: str = Field(description="Short, factual, e.g. 'Unexpected person'.")
    body: str = Field(
        description=(
            "One line, composed by the producer from the zone and the floorplan's "
            "room name. Never the street address: the dispatch address is bound at "
            "registration and does not travel in a claim or in a notice. Enforced by "
            "construction in hawkeye_backend/notices/detector.py (Task 2), and "
            "asserted in the Twilio sink's tests (Task 3), rather than by a validator "
            "here - a heuristic content scan would fail on real room names."
        )
    )
    zone: str | None = Field(default=None, description="Floorplan zone key, when there is one.")
    presence_id: str | None = Field(
        default=None,
        description="Session-scoped only. We do not do person re-identification.",
    )
    raised_at: datetime = Field(default_factory=utc_now)
    provenance: Provenance = Field(description="Required. See the honesty rule.")
