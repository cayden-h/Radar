"""Regenerate app/backend/schema/ from the live Pydantic models.

Every file in schema/ is produced by this script, so the examples cannot drift
from the code. The iOS agent matches its Codable types against these files.

    uv run python tools/gen_schema.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hawkeye_backend.master.scenario import ANSNAME, build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import (
    ContextEvent,
    Envelope,
    ErrorEvent,
    HelloEvent,
    IncidentEvent,
    IncidentPhase,
    InstructionEvent,
    NoticeEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.models.hub import AgentReachability, HubStatus, Reachability, SensorLiveness
from hawkeye_backend.models.incident import (
    CallState,
    ContextNote,
    ContextRequest,
    Incident,
    IncidentAck,
    IncidentClassification,
    IncidentStatus,
    IncidentType,
    Instruction,
    InstructionOrigin,
    RaiseIncidentRequest,
    RaisedBy,
    ReplayEntry,
    ReplayRecord,
    TranscriptLine,
    TranscriptSpeaker,
)
from hawkeye_backend.models.notice import Notice, NoticeSeverity
from hawkeye_backend.models.state import (
    Calibration,
    EnvironmentReading,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.models.verification import (
    Claim,
    SourceAgent,
    TrustIndexScore,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)

OUT = Path(__file__).resolve().parent.parent / "schema"

T0 = datetime(2026, 9, 20, 4, 12, 33, tzinfo=UTC)


def at(offset: float) -> datetime:
    return datetime.fromtimestamp(T0.timestamp() + offset, tz=UTC)


CSI = Provenance(
    source=Source.RUVIEW_SIM,
    producer="sensor/",
    ansname="sensor.hawkeye.invalid",
    detail="Synthetic CSI. No capture file is wired in; these numbers were not measured.",
)
GAS = Provenance(
    source=Source.DEMO_TRIGGER,
    producer="agents/master",
    ansname=ANSNAME["agents/master"],
    detail="no gas sensor was purchased; an MQ-7 on GPIO through an MCP3008 drops in behind this",
)
CALLER_VOICE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/caller", ansname=ANSNAME["agents/caller"]
)
OPERATOR = Provenance(source=Source.OPERATOR_AUDIO, producer="911 PSAP operator")
GUIDANCE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/caller", ansname=ANSNAME["agents/caller"]
)
RESIDENT = Provenance(source=Source.USER_INPUT, producer="app/ios")


def presence(
    pid: str,
    zone: str,
    x: float,
    y: float,
    state: PresenceState,
    moving: bool,
    respiration: RespirationStatus,
    bpm: float | None,
    heart: float | None,
    klass: PresenceClass,
    confidence: float,
    person_confidence: float,
    respiration_lost_s: float | None = None,
) -> Presence:
    return Presence(
        presence_id=pid,
        state=state,
        position=Position(zone=zone, x=x, y=y, zone_confidence=confidence),
        moving=moving,
        confidence=confidence,
        vitals=Vitals(
            respiration=respiration,
            breathing_bpm=bpm,
            heart_bpm=heart,
            person_confidence=person_confidence,
        ),
        presence_class=klass,
        class_basis="respiration_rate" if bpm is not None else None,
        expected=True,
        respiration_lost_s=respiration_lost_s,
        provenance=CSI,
    )


# The three states the app must render, one example each.
P_MOVING = presence(
    "p2", "second_bedroom", 5.3, 4.9, PresenceState.CONFIRMED_MOVING, True,
    RespirationStatus.BREATHING, 24.0, 98.0, PresenceClass.CHILD, 0.78, 0.81,
)
P_STILL = presence(
    "p1", "main_bedroom", 1.85, 4.35, PresenceState.CONFIRMED_STILL, False,
    RespirationStatus.NO_SIGNATURE, None, None, PresenceClass.ADULT, 0.71, 0.92,
    respiration_lost_s=96.0,
)
P_UNCONFIRMED = presence(
    "p3", "laundry", 8.85, 6.1, PresenceState.UNCONFIRMED, True,
    RespirationStatus.NO_SIGNATURE, None, None, PresenceClass.UNKNOWN, 0.44, 0.12,
)

STATE = InteriorState(
    site_id="site-demo-01",
    captured_at=T0,
    sensor_identity="sensor.hawkeye.invalid",
    calibration=Calibration(
        baseline_age_s=612.0,
        healthy=True,
        note="Rolling percentile baseline, slow adaptation. No calibration ritual.",
    ),
    presences=[P_STILL, P_MOVING, P_UNCONFIRMED],
    environment=EnvironmentReading(
        co_ppm=186.0, smoke_detected=False, confidence=0.88, provenance=GAS
    ),
    floorplan=build_floorplan("site-demo-01"),
    active_incident_id="inc-0001",
)

CLASSIFICATION = IncidentClassification(
    incident_type=IncidentType.FIRE,
    reasoning=(
        "Carbon monoxide at 180 ppm with a breathing signature in the main bedroom that "
        "was resolvable four minutes ago and is not now. Two independent modalities."
    ),
    contributing_claim_ids=["clm-001", "clm-002", "clm-003", "clm-004"],
    discarded_claim_ids=["clm-005"],
    confidence=0.86,
)

CONTEXT_NOTE = ContextNote(
    note_id="note-001",
    incident_id="inc-0001",
    text="My mother has COPD and there is a space heater in that bedroom.",
    at=at(31.0),
    provenance=RESIDENT,
    delivered_to_caller=True,
)

INCIDENT = Incident(
    incident_id="inc-0001",
    site_id="site-demo-01",
    incident_type=IncidentType.FIRE,
    status=IncidentStatus.ON_CALL,
    raised_by=RaisedBy.USER,
    raised_at=at(0.0),
    updated_at=at(34.0),
    address="1872 Ridgeview Lane, Blacksburg VA 24060",
    classification=CLASSIFICATION,
    call_state=CallState.CONNECTED,
    context_notes=[CONTEXT_NOTE],
)

PASSING_CHECKS = [
    VerificationCheck(
        name="ans.resolve",
        passed=True,
        detail="people.hawkeye.invalid resolved to the registered certificate.",
    ),
    VerificationCheck(
        name="cert.version_binding",
        passed=True,
        detail="Code fingerprint matches the version-bound certificate issued at registration.",
    ),
    VerificationCheck(
        name="trust_index.profile",
        passed=True,
        detail="Trust Index recommendedProfile = FIDUCIARY.",
    ),
]

VERIFIED = VerificationResult(
    verification_id="ver-001",
    incident_id="inc-0001",
    checked_at=at(6.0),
    claim=Claim(
        claim_id="clm-001",
        statement=(
            "A breathing signature on the adult in the main bedroom was resolvable and is "
            "not resolvable now. Not a finding that they have stopped breathing."
        ),
        field="people.respiration_lost",
        value="96 (seconds since last resolvable, zone=main_bedroom)",
        presence_id="p1",
    ),
    agent=SourceAgent(
        name="agents/people",
        ansname="people.hawkeye.invalid",
        certificate_version="v1.4.2+sha256:9f1c...a30b",
        trust_index=TrustIndexScore(
            integrity=0.94,
            identity=0.97,
            unimplemented_dimensions=["solvency", "behavior", "safety"],
        ),
        recommended_profile=TrustProfile.FIDUCIARY,
    ),
    decision=VerificationDecision.ASSERTED,
    reason=(
        "Source is FIDUCIARY and every check passed. Spoken as an assertion the system stands behind."
    ),
    checks=PASSING_CHECKS,
    will_be_spoken=True,
)

DISCARDED = VerificationResult(
    verification_id="ver-005",
    incident_id="inc-0001",
    checked_at=at(12.0),
    claim=Claim(
        claim_id="clm-005",
        statement="A third adult is unresponsive in the corridor outside the front door and is not breathing.",
        field="people.respiration",
        value="no respiration, building corridor",
        presence_id=None,
    ),
    agent=SourceAgent(
        name="agents/people",
        ansname="people.hawkeye-secure.invalid",
        certificate_version="v1.4.2+sha256:4d77...0e91",
        trust_index=TrustIndexScore(
            integrity=0.0,
            identity=0.0,
            unimplemented_dimensions=["solvency", "behavior", "safety"],
        ),
        recommended_profile=TrustProfile.UNTRUSTED,
    ),
    decision=VerificationDecision.DISCARDED,
    reason=(
        "DISCARDED. The claim would have sent an armed response into a room where no sensor "
        "sees anybody. It was not relayed to the operator and it was not used in classification."
    ),
    checks=[
        VerificationCheck(
            name="ans.resolve",
            passed=False,
            detail=(
                "people.hawkeye-secure.invalid is not the ANSName registered for "
                "agents/people. The registered name is people.hawkeye.invalid."
            ),
        ),
        VerificationCheck(
            name="cert.version_binding",
            passed=False,
            detail=(
                "Code fingerprint differs from the version-bound certificate issued at "
                "registration. The agent presenting this claim is not running the code it registered."
            ),
        ),
        VerificationCheck(
            name="trust_index.profile",
            passed=False,
            detail="Trust Index recommendedProfile = UNTRUSTED.",
        ),
        VerificationCheck(
            name="corroboration.sensor",
            passed=False,
            detail=(
                "The corridor outside the front door is not part of the unit and is outside "
                "the sensed volume, so no agent in this mesh can see it, and no other agent "
                "reports a third occupant."
            ),
        ),
    ],
    will_be_spoken=False,
)

TRANSCRIPT = TranscriptLine(
    line_id="line-004",
    incident_id="inc-0001",
    speaker=TranscriptSpeaker.CALLER,
    text=(
        "This is an automated call from a monitoring system at 1872 Ridgeview Lane, Blacksburg "
        "VA 24060. An adult occupant collapsed in the main bedroom about ninety seconds ago and "
        "has not gotten up. They are breathing, shallowly, at nine breaths a minute. Carbon "
        "monoxide in the building is elevated at 186 parts per million and rising."
    ),
    at=at(28.0),
    final=True,
    claim_ids=["clm-001", "clm-002", "clm-004"],
    provenance=CALLER_VOICE,
)

INSTRUCTION = Instruction(
    instruction_id="ins-002",
    incident_id="inc-0001",
    text="Fire and an ambulance are on the way, about four minutes out.",
    origin=InstructionOrigin.RELAYED_OPERATOR,
    at=at(58.0),
    urgent=True,
    supersedes_instruction_id=None,
    defers_to_operator=False,
    provenance=GUIDANCE,
)

HUB = HubStatus(
    hub_name="Hawk Eye Hub",
    hub_ansname="hub.hawkeye.invalid",
    master_ansname="master.hawkeye.invalid",
    site_id="site-demo-01",
    site_address="1872 Ridgeview Lane, Blacksburg VA 24060",
    mode="simulated",
    version="0.1.0",
    healthy=True,
    server_time=T0,
    uptime_s=812.4,
    sensor=SensorLiveness(
        source=Source.RUVIEW_SIM,
        simulated=True,
        live=True,
        frame_rate_hz=137.4,
        min_useful_frame_rate_hz=100.0,
        last_frame_at=T0,
        baseline_healthy=True,
        baseline_age_s=612.0,
        detail="Synthetic, not a radio. Nothing in this reading was measured.",
    ),
    agents=[
        AgentReachability(
            name="agents/people",
            ansname="people.hawkeye.invalid",
            tier=1,
            reachability=Reachability.REACHABLE,
            last_seen_at=T0,
            latency_ms=18.4,
            detail=None,
        ),
        AgentReachability(
            name="agents/master",
            ansname="master.hawkeye.invalid",
            tier=3,
            reachability=Reachability.DEGRADED,
            last_seen_at=T0,
            latency_ms=412.0,
            detail="Responding slowly. Tier 3; does not block the app.",
        ),
    ],
    active_incident_id="inc-0001",
)

REPLAY = ReplayRecord(
    incident_id="inc-0001",
    sealed=True,
    sealed_at=at(180.0),
    caller_ansname="caller.hawkeye.invalid",
    site_address="1872 Ridgeview Lane, Blacksburg VA 24060",
    entries=[
        ReplayEntry(
            seq=1,
            at=at(0.0),
            kind="incident",
            summary="fire raised by user",
            detail={"incident_id": "inc-0001", "incident_type": "fire", "raised_by": "user"},
            entry_hash="9a1e26430b4002eb059215c2a1e0a0f0f6d8f3bbd4c6a5f0b2e9a7c1d3f5e7a9",
            prev_hash=None,
        ),
        ReplayEntry(
            seq=2,
            at=at(6.0),
            kind="verification",
            summary="ASSERTED: An adult occupant went down in the main bedroom (people.hawkeye.invalid)",
            detail={"verification_id": "ver-001", "decision": "ASSERTED"},
            entry_hash="6192e3c8d12e7d7a90181d14c0b7e2d9a4f81c6b0e3d5a7f9c1b3d5f7a9c1e3d",
            prev_hash="9a1e26430b4002eb059215c2a1e0a0f0f6d8f3bbd4c6a5f0b2e9a7c1d3f5e7a9",
        ),
    ],
    verifications=[VERIFIED, DISCARDED],
    root_hash="eaf7ca3e574f961b00140de7931ca09fbfad04e0727a0ccd4462019bc5223227",
    scitt_receipt=None,
    hash_algorithm="sha256",
)


def write(name: str, model: BaseModel, note: str) -> None:
    body: dict[str, Any] = {
        "$note": note,
        "$generated_by": "tools/gen_schema.py",
        "example": model.model_dump(mode="json"),
    }
    path = OUT / name
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent)}")


def write_raw(name: str, body: dict[str, Any]) -> None:
    path = OUT / name
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent)}")


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # --- REST payloads
    write("hub.json", HUB, "GET /v1/hub response.")
    write("state.json", STATE, "GET /v1/state response. Carries all three renderable presence states.")
    write("incident.json", INCIDENT, "An Incident, as it appears inside an incident event.")
    write("replay.json", REPLAY, "GET /v1/incident/{id}/replay response.")
    write(
        "request-raise-incident.json",
        RaiseIncidentRequest(incident_type=IncidentType.BURGLARY, note="Someone is in the kitchen."),
        "POST /v1/incident request body.",
    )
    write(
        "response-raise-incident.json",
        IncidentAck(incident_id="inc-0002", status=IncidentStatus.RAISED, accepted_at=T0),
        "POST /v1/incident 202 response body.",
    )
    write(
        "request-context.json",
        ContextRequest(text="My mother has COPD and there is a space heater in that bedroom."),
        "POST /v1/incident/{id}/context request body.",
    )
    write(
        "response-context.json",
        CONTEXT_NOTE,
        "POST /v1/incident/{id}/context 202 response body.",
    )

    # --- Stream envelopes, one per event kind
    envelopes: list[tuple[str, Envelope, str]] = [
        (
            "event-hello.json",
            Envelope(
                seq=0,
                at=T0,
                incident_id=None,
                payload=HelloEvent(
                    hub_name="Hawk Eye Hub",
                    hub_ansname="hub.hawkeye.invalid",
                    mode="simulated",
                    stream_protocol_version=1,
                    active_incident_id="inc-0001",
                    replay_from_seq=1204,
                ),
            ),
            "First frame on every websocket connection.",
        ),
        (
            "event-state.json",
            Envelope(seq=1205, at=T0, incident_id="inc-0001", payload=StateEvent(state=STATE)),
            "An interior state tick. Roughly 2 Hz.",
        ),
        (
            "event-incident.json",
            Envelope(
                seq=1206,
                at=at(14.0),
                incident_id="inc-0001",
                payload=IncidentEvent(phase=IncidentPhase.CLASSIFIED, incident=INCIDENT),
            ),
            "Incident raised, classified, updated, resolved, or refused. `phase` says which.",
        ),
        (
            "event-verification-asserted.json",
            Envelope(
                seq=1207,
                at=at(6.0),
                incident_id="inc-0001",
                payload=VerificationEvent(result=VERIFIED),
            ),
            "A claim that verified. FIDUCIARY source, every check passed, caller may speak it.",
        ),
        (
            "event-verification-discarded.json",
            Envelope(
                seq=1208,
                at=at(12.0),
                incident_id="inc-0001",
                payload=VerificationEvent(result=DISCARDED),
            ),
            (
                "The refusal path. An impostor at a lookalike ANSName made a claim that would have "
                "escalated the response, and it was DISCARDED. The app must be able to render this. "
                "A dispatch demo that correctly refuses an impostor is the submission."
            ),
        ),
        (
            "event-transcript.json",
            Envelope(
                seq=1209,
                at=at(28.0),
                incident_id="inc-0001",
                payload=TranscriptEvent(line=TRANSCRIPT),
            ),
            "One line of the caller <-> 911 conversation, shown to the resident.",
        ),
        (
            "event-instruction.json",
            Envelope(
                seq=1210,
                at=at(58.0),
                incident_id="inc-0001",
                payload=InstructionEvent(instruction=INSTRUCTION),
            ),
            "One instruction from agents/caller.",
        ),
        (
            "event-context.json",
            Envelope(
                seq=1211,
                at=at(31.0),
                incident_id="inc-0001",
                payload=ContextEvent(note=CONTEXT_NOTE),
            ),
            "The resident's 'what is happening' note, echoed back so the app can confirm delivery.",
        ),
        (
            "event-notice.json",
            Envelope(
                seq=48,
                at=at(48.0),
                incident_id="inc-0001",
                payload=NoticeEvent(
                    notice=Notice(
                        notice_id="ntc-p4",
                        severity=NoticeSeverity.ATTENTION,
                        title="Unexpected person",
                        body="Not accounted for. Living room.",
                        zone="living_room",
                        room="Living room",
                        presence_id="p4",
                        raised_at=datetime(2026, 9, 19, 21, 4, 11, 142000, tzinfo=UTC),
                        provenance=Provenance(
                            source=Source.AGENT_INFERENCE,
                            producer="agents/intruder",
                            ansname=ANSNAME["agents/intruder"],
                            detail="presence surplus against roster and device association",
                        ),
                    )
                ),
            ),
            "A notice: something the resident should know about. Does not create an incident.",
        ),
        (
            "event-error.json",
            Envelope(
                seq=1212,
                at=T0,
                incident_id=None,
                payload=ErrorEvent(
                    code="master_unavailable",
                    message="agents/master stopped answering. The hub is not inventing state.",
                ),
            ),
            "Something went wrong. Never a silently dropped frame.",
        ),
    ]
    for name, env, note in envelopes:
        write(name, env, note)

    # --- The JSON Schema for the whole envelope union, for the Swift side to check against.
    write_raw(
        "envelope.schema.json",
        {
            "$note": (
                "JSON Schema for WS /v1/stream frames. Tagged union discriminated on "
                "payload.kind. Generated from the Pydantic Envelope model."
            ),
            "$generated_by": "tools/gen_schema.py",
            "schema": Envelope.model_json_schema(mode="serialization"),
        },
    )
    write_raw(
        "enums.json",
        {
            "$note": (
                "Every closed enum on the API, in one place, so the Swift side can mirror them "
                "exactly. Any value not in these lists is a bug, not something to tolerate."
            ),
            "$generated_by": "tools/gen_schema.py",
            "source": [s.value for s in Source],
            "source_class": ["measured-live", "measured-replay", "simulated", "human", "derived"],
            "presence_state": [s.value for s in PresenceState],
            "respiration_status": [s.value for s in RespirationStatus],
            "presence_class": [s.value for s in PresenceClass],
            "incident_type": [s.value for s in IncidentType],
            "incident_status": [s.value for s in IncidentStatus],
            "incident_phase": [s.value for s in IncidentPhase],
            "raised_by": [s.value for s in RaisedBy],
            "call_state": [s.value for s in CallState],
            "transcript_speaker": [s.value for s in TranscriptSpeaker],
            "instruction_origin": [s.value for s in InstructionOrigin],
            "trust_profile": [s.value for s in TrustProfile],
            "verification_decision": [s.value for s in VerificationDecision],
            "reachability": [s.value for s in Reachability],
            "event_kind": [
                "hello",
                "state",
                "incident",
                "transcript",
                "instruction",
                "verification",
                "context",
                "error",
            ],
        },
    )


if __name__ == "__main__":
    main()
