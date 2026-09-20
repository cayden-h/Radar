"""The camera path reaches the sealed record.

The record is the artifact emailed to the responding department. A bundle that
omitted the moment the camera was uncovered, or the moment something was
refused permission to uncover it, would be missing the only part a reader
cannot reconstruct from anywhere else.
"""

from __future__ import annotations

import pytest

from hawkeye_backend.models.common import Source, utc_now
from hawkeye_backend.models.events import (
    FrameEvent,
    NarrationEvent,
    OccupancyEvent,
    ShieldEvent,
)
from hawkeye_backend.models.incident import (
    Incident,
    IncidentStatus,
    IncidentType,
    RaisedBy,
)
from hawkeye_backend.models.events import IncidentEvent, IncidentPhase
from hawkeye_backend.replay import ReplayRecorder

INCIDENT = "inc-test-0001"


@pytest.fixture
def recorder() -> ReplayRecorder:
    r = ReplayRecorder(caller_ansname="ans://v1.0.0.caller.example")
    r.observe(
        IncidentEvent(
            phase=IncidentPhase.RAISED,
            incident=Incident(
                incident_id=INCIDENT,
                site_id="site-demo-01",
                incident_type=IncidentType.BURGLARY,
                status=IncidentStatus.RAISED,
                raised_by=RaisedBy.USER,
                raised_at=utc_now(),
                address="1872 Ridgeview Lane, Blacksburg VA 24060",
            ),
        ),
        INCIDENT,
    )
    return r


def kinds(recorder: ReplayRecorder) -> list[str]:
    session = recorder.get(INCIDENT)
    assert session is not None
    return [e.kind for e in session.to_record().entries]


def test_narration_is_sealed_alongside_what_the_operator_was_told(recorder):
    """An investigator comparing the two is the point of this record, and it
    cannot be done if only one half is in it."""
    recorder.observe(
        NarrationEvent(text="A person by the door.", room="Living room"), INCIDENT
    )
    assert "narration" in kinds(recorder)


def test_occupancy_is_sealed(recorder):
    recorder.observe(
        OccupancyEvent(person_present=True, people=1, room="Living room"), INCIDENT
    )
    assert "occupancy" in kinds(recorder)


def test_the_shield_moving_is_sealed(recorder):
    recorder.observe(
        ShieldEvent(position="open", commanded_angle=90, requested_action="open"),
        INCIDENT,
    )
    session = recorder.get(INCIDENT)
    entry = next(e for e in session.to_record().entries if e.kind == "shield")
    # The basis travels with it. A reader must not be able to mistake a
    # commanded angle for a measured position.
    assert "not measured" in entry.summary


def test_a_refusal_is_sealed_and_says_so(recorder):
    """The refusal is the submission. It belongs in the bundle a detective is
    handed, not only on a screen during the incident."""
    recorder.observe(
        ShieldEvent(
            position="closed",
            commanded_angle=0,
            requested_action="open",
            refused=True,
            refusal_reason="unregistered_issuer",
        ),
        INCIDENT,
    )
    session = recorder.get(INCIDENT)
    entry = next(e for e in session.to_record().entries if e.kind == "shield")
    assert "REFUSED" in entry.summary
    assert "unregistered_issuer" in entry.summary


def test_frames_are_not_sealed_into_the_document(recorder):
    """A frame a second for the length of a call is megabytes of base64 in a
    document whose whole value is that a human can read it. The footage is on
    disk as hashed mp4 segments; the record references it rather than
    duplicating it."""
    recorder.observe(
        FrameEvent(
            jpeg_base64="/9j/4AAQSkZJRg==",
            captured_at=utc_now(),
            source=Source.CAMERA_UVC,
            live=True,
            room="Living room",
        ),
        INCIDENT,
    )
    assert "frame" not in kinds(recorder)
