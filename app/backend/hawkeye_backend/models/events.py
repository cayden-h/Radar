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

from hawkeye_backend.models.common import Source, utc_now
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
    FRAME = "frame"
    NARRATION = "narration"
    OCCUPANCY = "occupancy"
    SHIELD = "shield"
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
    """One instruction from agents/caller."""

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


class FrameEvent(BaseModel):
    """A camera thumbnail, for clients that cannot hold an MJPEG stream open.

    The watch is the reason this exists. It has no MJPEG decoder and no direct
    path to the hub, so it gets frames the way it gets everything else: as an
    envelope, relayed through the phone. `Notice.stillFrame` already proves a
    base64 JPEG survives that trip.

    One per second, and small. This is a wrist, not a monitor.
    """

    kind: Literal[EventKind.FRAME] = EventKind.FRAME
    jpeg_base64: str = Field(description="Base64 JPEG. A thumbnail, not a recording.")
    captured_at: datetime = Field(
        description="When the camera took it, not when it was published here."
    )
    source: Source = Field(
        description="What produced it. A video file must not read as a camera."
    )
    live: bool = Field(
        description=(
            "Whether this was current when published. False means the client must "
            "label it as the last thing seen rather than draw it as the room now."
        )
    )
    room: str | None = Field(
        default=None,
        description=(
            "The room this camera covers. One fixed camera sees one room, and every "
            "vision claim carries its scope rather than implying it has none."
        ),
    )


class NarrationEvent(BaseModel):
    """One line the camera produced about what it is seeing.

    **Not a `TranscriptLine`.** That type is documented as one line of the
    caller-to-911 conversation, and collapsing the two would let a camera
    observation render as something an operator was told. When `caller` quotes
    one of these to an operator, that becomes a `TranscriptLine` whose
    `claim_ids` point back here, which is the existing mechanism for exactly
    this and needs nothing new.

    `room` and `window_s` are both required and both load-bearing. One fixed
    camera sees one room, and Gemini samples at roughly one frame per second, so
    this is a sequence of observations rather than continuous tracking. The root
    CLAUDE.md requires both limits to be carried in the data rather than only
    stated in a comment.
    """

    kind: Literal[EventKind.NARRATION] = EventKind.NARRATION
    text: str = Field(min_length=1)
    room: str = Field(min_length=1, description="The room this camera covers. Never absent.")
    window_s: float = Field(
        default=1.0,
        gt=0,
        description=(
            "Seconds of observation this line summarizes. About one frame per "
            "second reaches the model, so this is a sequence of glances rather "
            "than continuous tracking, and a reader is entitled to know that."
        ),
    )
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.AGENT_INFERENCE


class OccupancyEvent(BaseModel):
    """Whether the camera can see anybody. What closes the shutter again.

    Personhood only. This never says who: we have no database and no lawful
    basis for one, and `intruder` answers identity separately by asking the
    router which devices are present.
    """

    kind: Literal[EventKind.OCCUPANCY] = EventKind.OCCUPANCY
    person_present: bool
    people: int = Field(ge=0, description="How many tracks are currently present.")
    room: str = Field(min_length=1)
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.CAMERA_UVC


class ShieldEvent(BaseModel):
    """Where the physical shield is, and what the shutter said about getting there.

    `position_basis` is `commanded` and never `measured`, and that is not a
    technicality. The SG92R is open-loop with no position feedback, so this is
    the angle the servo was told to reach and never the angle the shield
    actually reached. A jammed shield attests open while covering the lens, and
    the only thing that catches that is the frame itself being dark.

    `refused` is a first-class outcome. A shutter declining a grant it cannot
    verify is the system working, and it is the thing this project most wants to
    be able to put on a screen.
    """

    kind: Literal[EventKind.SHIELD] = EventKind.SHIELD
    position: str = Field(
        description="`open`, `closed`, or `unknown`. Unknown when the shutter did not answer."
    )
    position_basis: str = Field(
        default="commanded",
        description="Always `commanded`. The servo has no position feedback.",
    )
    commanded_angle: int | None = None
    requested_action: str = Field(description="What was asked for: `open` or `close`.")
    refused: bool = False
    refusal_reason: str = ""
    reason: str = Field(
        default="", description="Why the move was requested. Recorded, not trusted."
    )
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.SERVO_GPIO


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
    | FrameEvent
    | NarrationEvent
    | OccupancyEvent
    | ShieldEvent
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
