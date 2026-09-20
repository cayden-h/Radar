"""Incidents, the call transcript, guidance instructions, and the sealed replay."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import Provenance, utc_now
from hawkeye_backend.models.verification import VerificationResult


class IncidentType(StrEnum):
    """The two incident types. Nothing else classifies.

    Faint was the third until 2026-09-19. Fall detection was the weakest link
    in the chain - a debounce problem dressed as a clinical variable - and what
    a dispatcher actually needs is narrower and defensible: whether the people
    inside can respond. That is carried by respiration, per presence.
    """

    BURGLARY = "burglary"
    FIRE = "fire"


class RaisedBy(StrEnum):
    """Who raised it.

    USER is the only path to a call. Hawk Eye never dials 911 on its own;
    settled 2026-09-19. A human tap is what releases `agents/caller` to dial,
    and `agents/people` and `agents/master` surface their detections as
    interior state the resident acts on rather than as a call.

    SYSTEM is kept for wire compatibility and for records raised before that
    decision. It must never reach the dialing path: `assert_human_released` in
    `master/base.py` enforces that structurally rather than by convention.
    """

    USER = "user"
    SYSTEM = "system"


class IncidentStatus(StrEnum):
    RAISED = "raised"
    CLASSIFIED = "classified"
    CALLING = "calling"
    ON_CALL = "on_call"
    DISPATCHED = "dispatched"
    RESOLVED = "resolved"
    REFUSED = "refused"


class CallState(StrEnum):
    """State of the phone call to the 911 operator."""

    NOT_STARTED = "not_started"
    DIALING = "dialing"
    CONNECTED = "connected"
    ENDED = "ended"
    NOT_PLACED = "not_placed"


class IncidentClassification(BaseModel):
    """Why master called it what it called it.

    Classification is the interesting part and should be visible. Elevated CO
    plus a breathing signature that has gone missing is a fire with an occupant
    who may not be able to respond, and that is two independent modalities
    rather than one signal crossing a threshold.
    """

    incident_type: IncidentType
    reasoning: str = Field(description="Plain English, shown to the resident.")
    contributing_claim_ids: list[str] = Field(default_factory=list)
    discarded_claim_ids: list[str] = Field(
        default_factory=list,
        description="Claims that did not survive verification. Named, not hidden.",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ContextNote(BaseModel):
    """One line the resident typed into the "what is happening" box.

    Goes to master and becomes available to caller for the rest of the call.
    Provenance is `user-input`: it is a human statement, not a measurement, and
    caller must attribute it as such rather than asserting it as sensed fact.
    """

    note_id: str
    incident_id: str
    text: str = Field(min_length=1, max_length=2000)
    at: datetime = Field(default_factory=utc_now)
    provenance: Provenance
    delivered_to_caller: bool = False


class TranscriptSpeaker(StrEnum):
    """Who said a line.

    CALLER is our agent's synthesized voice. OPERATOR is the human dispatcher.
    RESIDENT appears when the resident speaks on the line directly.
    SYSTEM is a non-speech annotation, e.g. "call connected".
    """

    CALLER = "caller"
    OPERATOR = "operator"
    RESIDENT = "resident"
    SYSTEM = "system"


class TranscriptLine(BaseModel):
    """One line of the caller <-> 911 conversation, shown to the resident.

    The operator does not see this. It exists so the resident is not left in
    silence while a synthetic voice speaks on their behalf.
    """

    line_id: str
    incident_id: str
    speaker: TranscriptSpeaker
    text: str
    at: datetime = Field(default_factory=utc_now)
    final: bool = Field(
        default=True,
        description="False for a partial transcription being revised in place. Match on line_id.",
    )
    claim_ids: list[str] = Field(
        default_factory=list,
        description="Verified claims this line repeats. Lets the app link a spoken sentence to its proof.",
    )
    provenance: Provenance


class InstructionOrigin(StrEnum):
    """Where an instruction came from.

    The UI should not distinguish these, because the user does not care. The API
    does, because the safety rules differ: relayed operator instructions always
    win over generated first aid.
    """

    RELAYED_OPERATOR = "relayed_operator"
    FIRST_AID = "first_aid"
    SYSTEM_STATUS = "system_status"


class Instruction(BaseModel):
    """One thing agents/caller is telling the resident to do."""

    instruction_id: str
    incident_id: str
    text: str
    origin: InstructionOrigin
    at: datetime = Field(default_factory=utc_now)
    urgent: bool = False
    supersedes_instruction_id: str | None = None
    defers_to_operator: bool = Field(
        default=True,
        description=(
            "True when this instruction must be dropped the moment the dispatcher gives a "
            "competing one. Dispatchers are trained for this and the agent is not."
        ),
    )
    provenance: Provenance


class Incident(BaseModel):
    """One incident, from raised to resolved."""

    incident_id: str
    site_id: str
    incident_type: IncidentType
    status: IncidentStatus
    raised_by: RaisedBy
    raised_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    address: str = Field(description="What the caller will read to the dispatcher.")
    classification: IncidentClassification | None = None
    call_state: CallState = CallState.NOT_STARTED
    context_notes: list[ContextNote] = Field(default_factory=list)
    refusal_reason: str | None = Field(
        default=None,
        description="Set when status is REFUSED: why the system declined to escalate.",
    )


class RaiseIncidentRequest(BaseModel):
    """POST /v1/incident body."""

    incident_type: IncidentType
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional first line of context, same channel as the 'what is happening' box.",
    )


class IncidentAck(BaseModel):
    """POST /v1/incident response. Deliberately small; the stream carries the rest."""

    incident_id: str
    status: IncidentStatus
    accepted_at: datetime = Field(default_factory=utc_now)


class ContextRequest(BaseModel):
    """POST /v1/incident/{id}/context body."""

    text: str = Field(min_length=1, max_length=2000)
    speak_on_call: bool = Field(
        default=False,
        description=(
            "Also route this note to agents/caller so it is spoken on an "
            "already-running call, attributed to the resident. Best-effort: "
            "a failure to speak it must never fail storing the note itself. "
            "Context, never instruction - it cannot change what caller "
            "trusts or where the incident is directed."
        ),
    )


class ReplayEntry(BaseModel):
    """One sealed entry in the post-incident record."""

    seq: int
    at: datetime
    kind: str = Field(
        description=(
            "lifecycle | frame | incident | transcript | instruction | verification | "
            "context | notice | state"
        )
    )
    actor: str | None = Field(
        default=None,
        description=(
            "Who is responsible for this entry: an ANSName, 'hub', '911-operator', "
            "'resident'. Null on entries written before the recorder tracked it, which "
            "is why it is optional rather than required."
        ),
    )
    summary: str
    detail: dict[str, object] = Field(default_factory=dict)
    entry_hash: str = Field(description="SHA-256 over the canonical JSON of this entry.")
    prev_hash: str | None = Field(
        default=None, description="Hash chain. Ties this entry to the one before it."
    )


class ReplayRecord(BaseModel):
    """GET /v1/incident/{id}/replay response, from agents/replay.

    Two audiences: detectives after a burglary, and accountability for the system
    itself. The operator cannot verify us live; an investigator can verify this
    afterward, and swatting investigations are entirely post-hoc.
    """

    incident_id: str
    sealed: bool
    sealed_at: datetime | None = None
    caller_ansname: str
    site_address: str
    entries: list[ReplayEntry]
    verifications: list[VerificationResult] = Field(
        default_factory=list, description="Every verification, accepted and discarded alike."
    )
    root_hash: str | None = Field(
        default=None, description="Hash of the final entry. What gets submitted to SCITT."
    )
    scitt_receipt: str | None = Field(
        default=None,
        description="SCITT transparency log receipt. Null until the entry is sealed.",
    )
    # TODO(ans): the SCITT submission and receipt format is not implemented here.
    # Question to answer against https://github.com/agentnameservice/ans-registry:
    # what is the exact submit endpoint and receipt structure for an ANS SCITT
    # transparency log entry (ANS-4), and is a receipt a COSE object or a JSON
    # document? Until that is answered this field stays null and the README says
    # so. Do not fabricate a receipt: an unverifiable receipt is worse than none.
    hash_algorithm: str = "sha256"
