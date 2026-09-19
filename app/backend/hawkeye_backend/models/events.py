"""The WS /v1/stream envelope. A tagged union, discriminated on `kind`.

Every frame on the websocket is an Envelope. `kind` is the discriminator, `seq`
is monotonic per connection-independent server sequence so a client can detect a
gap, and `payload` is the typed body. Swift decodes this by switching on `kind`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.incident import (
    ContextNote,
    Incident,
    Instruction,
    TranscriptLine,
)
from hawkeye_backend.models.notice import Notice
from hawkeye_backend.models.state import InteriorState
from hawkeye_backend.models.verification import VerificationResult


class EventKind(StrEnum):
    STATE = "state"
    INCIDENT = "incident"
    TRANSCRIPT = "transcript"
    INSTRUCTION = "instruction"
    VERIFICATION = "verification"
    CONTEXT = "context"
    NOTICE = "notice"
    HELLO = "hello"
    ERROR = "error"


class StateEvent(BaseModel):
    """An interior state tick. Roughly 2 Hz during an incident, 0.5 Hz otherwise."""

    kind: Literal[EventKind.STATE] = EventKind.STATE
    state: InteriorState


class IncidentPhase(StrEnum):
    RAISED = "raised"
    CLASSIFIED = "classified"
    UPDATED = "updated"
    RESOLVED = "resolved"
    REFUSED = "refused"


class IncidentEvent(BaseModel):
    """An incident was raised, classified, updated, resolved, or refused."""

    kind: Literal[EventKind.INCIDENT] = EventKind.INCIDENT
    phase: IncidentPhase
    incident: Incident


class TranscriptEvent(BaseModel):
    """One line of the caller <-> 911 conversation."""

    kind: Literal[EventKind.TRANSCRIPT] = EventKind.TRANSCRIPT
    line: TranscriptLine


class InstructionEvent(BaseModel):
    """One instruction from agents/guidance."""

    kind: Literal[EventKind.INSTRUCTION] = EventKind.INSTRUCTION
    instruction: Instruction


class VerificationEvent(BaseModel):
    """An ANS verification result: which claim, which agent, verified or DISCARDED and why.

    This event is the submission. A demo that escalates is unremarkable; one that
    correctly refuses an impostor is the point, and the app renders that refusal
    off this event.
    """

    kind: Literal[EventKind.VERIFICATION] = EventKind.VERIFICATION
    result: VerificationResult


class ContextEvent(BaseModel):
    """The resident's "what is happening" note, echoed back so the app can confirm delivery."""

    kind: Literal[EventKind.CONTEXT] = EventKind.CONTEXT
    note: ContextNote


class NoticeEvent(BaseModel):
    """A notice was raised: something the resident should know about.

    Does not create an incident and does not dial. `app/CLAUDE.md`: "An alert is
    information a person acts on. It is not a call."
    """

    kind: Literal[EventKind.NOTICE] = EventKind.NOTICE
    notice: Notice


class HelloEvent(BaseModel):
    """First frame on every connection. Tells the client what it just joined."""

    kind: Literal[EventKind.HELLO] = EventKind.HELLO
    hub_name: str
    hub_ansname: str
    mode: str
    stream_protocol_version: int = 1
    active_incident_id: str | None = None
    replay_from_seq: int | None = Field(
        default=None, description="Sequence of the oldest event still buffered, for gap recovery."
    )


class ErrorEvent(BaseModel):
    """Something went wrong. Never silently drops a frame."""

    kind: Literal[EventKind.ERROR] = EventKind.ERROR
    code: str
    message: str


EventPayload = Annotated[
    StateEvent
    | IncidentEvent
    | TranscriptEvent
    | InstructionEvent
    | VerificationEvent
    | ContextEvent
    | NoticeEvent
    | HelloEvent
    | ErrorEvent,
    Field(discriminator="kind"),
]


class Envelope(BaseModel):
    """Every websocket frame is one of these."""

    seq: int = Field(description="Monotonic, server-wide. A gap means the client missed a frame.")
    at: datetime = Field(default_factory=utc_now)
    incident_id: str | None = Field(
        default=None, description="Set when the event belongs to an incident."
    )
    payload: EventPayload

    @property
    def kind(self) -> EventKind:
        return self.payload.kind


EnvelopeAdapter: TypeAdapter[Envelope] = TypeAdapter(Envelope)


def envelope(seq: int, payload: EventPayload, incident_id: str | None = None) -> Envelope:
    """Wrap a payload. Kept as a function so the seq source stays in one place."""
    return Envelope(seq=seq, payload=payload, incident_id=incident_id)


__all__ = [
    "ContextEvent",
    "Envelope",
    "EnvelopeAdapter",
    "ErrorEvent",
    "EventKind",
    "EventPayload",
    "HelloEvent",
    "IncidentEvent",
    "IncidentPhase",
    "InstructionEvent",
    "Notice",
    "NoticeEvent",
    "StateEvent",
    "TranscriptEvent",
    "VerificationEvent",
    "envelope",
]
