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


class NoticeFrame(BaseModel):
    """A still from the moment the shield cleared the lens.

    A thumbnail, not the recording. It crosses the socket to a phone and then
    WatchConnectivity to a wrist, so it is deliberately small; the full segment
    stays here and is sealed into the replay record with everything else.

    The frame is what makes a notice answerable. Before the camera pivot the
    resident was asked to judge an unlabelled blob on a floorplan; now they are
    looking at the person they are being asked about.
    """

    jpeg_base64: str = Field(
        description=(
            "Base64 JPEG bytes. A thumbnail sized for a watch, not a frame of the "
            "recording. Base64 rather than bytes because this shape is what the "
            "client decodes and the schema examples must show it."
        )
    )
    captured_at: datetime = Field(default_factory=utc_now)
    room: str | None = Field(
        default=None,
        description=(
            "The room the camera covers. One fixed camera sees one room, and every "
            "vision claim carries its scope rather than implying it has none."
        ),
    )


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
    room: str | None = Field(
        default=None,
        description=(
            "The floorplan's display name for `zone`, e.g. 'Living room'. Resolved "
            "once by the producer so no consumer has to re-derive it or parse it back "
            "out of `body`."
        ),
    )
    presence_id: str | None = Field(
        default=None,
        description="Session-scoped only. We do not do person re-identification.",
    )
    raised_at: datetime = Field(default_factory=utc_now)
    provenance: Provenance = Field(description="Required. See the honesty rule.")
    narration: str | None = Field(
        default=None,
        description=(
            "The camera's own first sentence about what it is looking at, from "
            "agents/vision. Optional because it did not exist before the camera "
            "pivot and a client that predates it must still decode. When it is "
            "present it is what the notification says: a generic 'motion detected' "
            "on a resident's wrist throws away the whole point of the camera, so "
            "the watch relay drops any notice that lacks one rather than "
            "substituting filler."
        ),
    )
    still_frame: NoticeFrame | None = Field(
        default=None,
        description=(
            "A still from the moment the shield opened. None until agents/vision "
            "produces one, and None forever if the shield refused to open, which is "
            "the honest answer rather than a placeholder image."
        ),
    )
    dismissed: bool = Field(
        default=False,
        description=(
            "Whether a human has cleared this notice. Server-side rather than "
            "per-client, so a notice cleared on the phone is cleared on the watch "
            "and in the browser too. Before this was carried here, each surface "
            "kept its own opinion and the resident had to dismiss the same alarm "
            "three times.\n\n"
            "Dismissing is *not* vouching. It clears a banner and nothing else: it "
            "does not suppress the next notice about this presence, and it does "
            "not add anyone to the roster. Those are `POST /v1/presences/{id}/"
            "approve` and `POST /v1/household/remember`, which are separate "
            "controls with separate words on purpose, because one control for "
            "both would persist strangers because somebody wanted a banner gone."
        ),
    )
    dismissed_at: datetime | None = None
