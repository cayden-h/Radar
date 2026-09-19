"""The recording lifecycle: what opens a record, what goes in it, what seals it.

The properties under test here are the ones the record's value rests on. A
record that opens without a human tap, grows after it was sealed, or verifies
after being edited is worse than no record, because it would be believed.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from datetime import timedelta

import pytest

from hawkeye_backend.models.common import (
    Provenance,
    Source,
    utc_now,
)
from hawkeye_backend.models.events import (
    ContextEvent,
    IncidentEvent,
    IncidentPhase,
    StateEvent,
    TranscriptEvent,
)
from hawkeye_backend.models.hub import SensorLiveness
from hawkeye_backend.models.incident import (
    CallState,
    ContextNote,
    Incident,
    IncidentStatus,
    IncidentType,
    RaisedBy,
    TranscriptLine,
    TranscriptSpeaker,
)
from hawkeye_backend.models.state import (
    Calibration,
    InteriorState,
    Position,
    Presence,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.replay import RecordSealed, ReplayRecorder, build_export

SITE = "site-test"
ADDRESS = "1872 Ridgeview Lane, Blacksburg VA 24060"
CALLER = "caller.hawkeye.invalid"
SIM = Provenance(source=Source.RUVIEW_SIM, producer="agents/people", ansname="people.hawkeye.invalid")


# ------------------------------------------------------------------- fixtures


def incident(
    *,
    raised_by: RaisedBy = RaisedBy.USER,
    status: IncidentStatus = IncidentStatus.RAISED,
    call_state: CallState = CallState.NOT_STARTED,
    incident_id: str = "inc-0001",
) -> Incident:
    return Incident(
        incident_id=incident_id,
        site_id=SITE,
        incident_type=IncidentType.FIRE,
        status=status,
        raised_by=raised_by,
        address=ADDRESS,
        call_state=call_state,
    )


def state(
    *,
    presence_state: PresenceState = PresenceState.CONFIRMED_MOVING,
    respiration_lost_s: float | None = None,
    at_offset_s: float = 0.0,
    incident_id: str | None = "inc-0001",
) -> InteriorState:
    return InteriorState(
        site_id=SITE,
        captured_at=utc_now() + timedelta(seconds=at_offset_s),
        sensor_identity="sensor.hawkeye.invalid",
        calibration=Calibration(baseline_age_s=600.0, healthy=True),
        presences=[
            Presence(
                presence_id="p1",
                state=presence_state,
                position=Position(zone="main_bedroom", x=1.8, y=4.3, zone_confidence=0.9),
                moving=presence_state is PresenceState.CONFIRMED_MOVING,
                confidence=0.9,
                vitals=Vitals(
                    respiration=RespirationStatus.BREATHING,
                    breathing_bpm=16.0,
                    person_confidence=0.92,
                ),
                respiration_lost_s=respiration_lost_s,
                provenance=SIM,
            )
        ],
        floorplan=build_floorplan(SITE),
        active_incident_id=incident_id,
    )


@pytest.fixture
def recorder() -> ReplayRecorder:
    rec = ReplayRecorder(caller_ansname=CALLER, frame_interval_s=0.5)
    rec.sensor = SensorLiveness(
        source=Source.RUVIEW_SIM,
        simulated=True,
        live=True,
        frame_rate_hz=137.4,
        baseline_healthy=True,
        baseline_age_s=600.0,
    )
    return rec


def raise_it(recorder: ReplayRecorder, inc: Incident) -> None:
    recorder.observe(IncidentEvent(phase=IncidentPhase.RAISED, incident=inc), inc.incident_id)


def end_call(recorder: ReplayRecorder, inc: Incident) -> None:
    inc.call_state = CallState.ENDED
    inc.status = IncidentStatus.RESOLVED
    inc.resolved_at = utc_now()
    recorder.observe(
        IncidentEvent(phase=IncidentPhase.RESOLVED, incident=inc), inc.incident_id
    )


# ----------------------------------------------------------------- what opens


def test_a_human_tap_opens_a_record(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)

    session = recorder.get(inc.incident_id)
    assert session is not None
    assert len(session) == 1
    assert session.entries[0].kind == "lifecycle"
    assert session.entries[0].actor == "resident"
    assert "raised by user" in session.entries[0].summary


def test_a_system_raise_opens_nothing(recorder: ReplayRecorder) -> None:
    """Hawk Eye never dials on its own, so there is no call to record.

    Settled 2026-09-19. `assert_human_released` enforces the same boundary on
    the dialing path; this is the recorder's half of it.
    """
    inc = incident(raised_by=RaisedBy.SYSTEM)
    raise_it(recorder, inc)
    assert recorder.get(inc.incident_id) is None


def test_an_incident_first_seen_mid_flight_is_not_recorded(recorder: ReplayRecorder) -> None:
    """A chain that omits its own beginning has the shape of a doctored one."""
    inc = incident(status=IncidentStatus.ON_CALL, call_state=CallState.CONNECTED)
    recorder.observe(
        IncidentEvent(phase=IncidentPhase.UPDATED, incident=inc), inc.incident_id
    )
    assert recorder.get(inc.incident_id) is None


# ---------------------------------------------------------------- what closes


def test_the_call_ending_seals_the_record(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    end_call(recorder, inc)

    session = recorder.get(inc.incident_id)
    assert session.sealed
    assert session.sealed_at is not None
    assert session.entries[-1].kind == "lifecycle"
    assert "sealed" in session.entries[-1].summary.lower()
    # The limit is stated on the record itself, not only in the export README.
    assert session.entries[-1].detail["transparency_receipt"] is None


def test_a_sealed_record_refuses_to_grow(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    end_call(recorder, inc)
    session = recorder.get(inc.incident_id)
    sealed_length = len(session)

    with pytest.raises(RecordSealed):
        session.append(kind="transcript", summary="one more word")

    # And through the event path, where it is logged rather than raised: a
    # trailing state tick after the call ends is ordinary, not a bug.
    recorder.observe(StateEvent(state=state()), inc.incident_id)
    recorder.observe(
        TranscriptEvent(
            line=TranscriptLine(
                line_id="l-99",
                incident_id=inc.incident_id,
                speaker=TranscriptSpeaker.OPERATOR,
                text="after the fact",
                provenance=SIM,
            )
        ),
        inc.incident_id,
    )
    assert len(session) == sealed_length


def test_resolution_without_a_call_still_seals(recorder: ReplayRecorder) -> None:
    """There is no call end to wait for, and an open record forever is worse."""
    inc = incident()
    raise_it(recorder, inc)
    inc.call_state = CallState.NOT_PLACED
    inc.resolved_at = utc_now()
    inc.status = IncidentStatus.RESOLVED
    recorder.observe(
        IncidentEvent(phase=IncidentPhase.RESOLVED, incident=inc), inc.incident_id
    )
    assert recorder.get(inc.incident_id).sealed


# ------------------------------------------------------------- what goes in it


def test_every_event_kind_lands_once(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    session = recorder.get(inc.incident_id)

    recorder.observe(
        TranscriptEvent(
            line=TranscriptLine(
                line_id="l-1",
                incident_id=inc.incident_id,
                speaker=TranscriptSpeaker.CALLER,
                text="There is one person down in the main bedroom.",
                provenance=SIM,
            )
        ),
        inc.incident_id,
    )
    recorder.observe(
        ContextEvent(
            note=ContextNote(
                note_id="n-1",
                incident_id=inc.incident_id,
                text="she takes blood thinners",
                provenance=SIM,
            )
        ),
        inc.incident_id,
    )
    kinds = [e.kind for e in session.entries]
    assert kinds == ["lifecycle", "transcript", "context"]
    assert session.entries[2].actor == "resident"


def test_a_frame_carries_the_map_and_the_radio(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    recorder.observe(StateEvent(state=state(respiration_lost_s=45.0)), inc.incident_id)

    frame = recorder.get(inc.incident_id).entries[-1]
    assert frame.kind == "frame"
    assert frame.detail["presences"][0]["respiration_lost_s"] == 45.0
    assert frame.detail["rf"]["frame_rate_hz"] == 137.4
    # The honesty rule, enforced in the data rather than in a comment.
    assert frame.detail["rf"]["raw_csi"] is None
    assert frame.detail["rf"]["simulated"] is True
    assert frame.detail["presences"][0]["simulated"] is True


def test_the_floorplan_rides_on_the_first_frame_only(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    recorder.observe(StateEvent(state=state(at_offset_s=0)), inc.incident_id)
    recorder.observe(
        StateEvent(state=state(presence_state=PresenceState.CONFIRMED_STILL, at_offset_s=1)),
        inc.incident_id,
    )

    frames = [e for e in recorder.get(inc.incident_id).entries if e.kind == "frame"]
    assert "floorplan" in frames[0].detail
    assert frames[0].detail["floorplan"]["origin"] == "authored-enrollment-walk"
    assert "floorplan" not in frames[1].detail


# ------------------------------------------------------------------- throttle


def test_frames_are_throttled(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    for offset in (0.0, 0.1, 0.2, 0.3):
        recorder.observe(StateEvent(state=state(at_offset_s=offset)), inc.incident_id)

    session = recorder.get(inc.incident_id)
    assert len([e for e in session.entries if e.kind == "frame"]) == 1
    assert session.frames_dropped == 3


def test_a_presence_going_still_is_never_throttled_away(recorder: ReplayRecorder) -> None:
    """The transition the whole system exists to catch must not be dropped."""
    inc = incident()
    raise_it(recorder, inc)
    recorder.observe(StateEvent(state=state(at_offset_s=0.0)), inc.incident_id)
    recorder.observe(
        StateEvent(
            state=state(presence_state=PresenceState.CONFIRMED_STILL, at_offset_s=0.05)
        ),
        inc.incident_id,
    )

    frames = [e for e in recorder.get(inc.incident_id).entries if e.kind == "frame"]
    assert len(frames) == 2
    assert frames[1].detail["presences"][0]["state"] == "confirmed_still"


def test_the_entry_ceiling_stops_frames_and_says_so(recorder: ReplayRecorder) -> None:
    rec = ReplayRecorder(caller_ansname=CALLER, frame_interval_s=0.0, max_entries=4)
    inc = incident()
    raise_it(rec, inc)
    for offset in range(10):
        rec.observe(StateEvent(state=state(at_offset_s=offset)), inc.incident_id)

    session = rec.get(inc.incident_id)
    assert session.frames_suspended
    assert session.entries[-1].kind == "lifecycle"
    assert "suspended" in session.entries[-1].summary

    # Everything that is not a frame keeps being recorded, because the claims
    # and the transcript are the record's point.
    rec.observe(
        ContextEvent(
            note=ContextNote(
                note_id="n-2", incident_id=inc.incident_id, text="still going", provenance=SIM
            )
        ),
        inc.incident_id,
    )
    assert session.entries[-1].kind == "context"


# ---------------------------------------------------------------- the chain


def test_the_chain_verifies(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    recorder.observe(StateEvent(state=state()), inc.incident_id)
    end_call(recorder, inc)

    intact, detail, failed = recorder.get(inc.incident_id).verify()
    assert intact, detail
    assert failed is None


def test_editing_an_entry_is_caught_at_that_entry(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    for offset in range(4):
        recorder.observe(StateEvent(state=state(at_offset_s=offset)), inc.incident_id)
    session = recorder.get(inc.incident_id)
    assert len(session) >= 4

    # The realistic attack: change what a sensing agent is recorded as having
    # seen, and leave everything else alone.
    session.entries[2].detail["presences"][0]["zone"] = "living_room"

    intact, detail, failed = session.verify()
    assert not intact
    assert failed == 3
    assert "altered" in detail


def test_removing_an_entry_is_caught(recorder: ReplayRecorder) -> None:
    inc = incident()
    raise_it(recorder, inc)
    for offset in range(4):
        recorder.observe(StateEvent(state=state(at_offset_s=offset)), inc.incident_id)
    session = recorder.get(inc.incident_id)

    del session._entries[2]
    intact, _, failed = session.verify()
    assert not intact
    assert failed == 4


# ---------------------------------------------------------------- the export


def test_the_export_bundle_holds_what_it_claims(recorder: ReplayRecorder, tmp_path) -> None:
    inc = incident()
    raise_it(recorder, inc)
    recorder.observe(StateEvent(state=state(respiration_lost_s=90.0)), inc.incident_id)
    end_call(recorder, inc)

    record = recorder.get(inc.incident_id).to_record()
    blob = build_export(record, utc_now())
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        assert sorted(bundle.namelist()) == ["README.txt", "chain.txt", "record.json", "verify.py"]
        readme = bundle.read("README.txt").decode()
        bundle.extractall(tmp_path)

    # The limit is stated, not buried. An export that overstates what it proves
    # is worse than no export, because it will be believed.
    assert "WHAT IT DOES NOT PROVE" in readme
    assert "NOT implemented" in readme

    parsed = json.loads((tmp_path / "record.json").read_text())
    assert parsed["incident_id"] == inc.incident_id
    assert parsed["scitt_receipt"] is None


def test_the_shipped_verifier_agrees_with_the_server(recorder: ReplayRecorder, tmp_path) -> None:
    """The script a detective runs must reach the same verdict as the code that wrote the record.

    It reimplements the canonical form rather than importing it, so this test is
    the only thing keeping the two in step.
    """
    inc = incident()
    raise_it(recorder, inc)
    for offset in range(3):
        recorder.observe(StateEvent(state=state(at_offset_s=offset)), inc.incident_id)
    end_call(recorder, inc)

    blob = build_export(recorder.get(inc.incident_id).to_record(), utc_now())
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        bundle.extractall(tmp_path)

    ok = subprocess.run(
        [sys.executable, "verify.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "INTACT" in ok.stdout

    # And it must catch the edit the server catches, on the same entry.
    record = json.loads((tmp_path / "record.json").read_text())
    record["entries"][2]["summary"] = "nothing happened"
    (tmp_path / "record.json").write_text(json.dumps(record))

    caught = subprocess.run(
        [sys.executable, "verify.py"], cwd=tmp_path, capture_output=True, text=True
    )
    assert caught.returncode == 1
    assert "ALTERED" in caught.stdout
    assert "entry 3" in caught.stdout
