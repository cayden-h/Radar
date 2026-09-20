"""Approving a presence, and what that does and does not change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.state import (
    Calibration, InteriorState, Position, Presence, PresenceClass,
    PresenceState, RespirationStatus, Vitals,
)
from hawkeye_backend.notices.detector import NoticeDetector

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)
PROV = Provenance(source=Source.RUVIEW_SIM, producer="sensor/")


def presence(presence_id: str = "p4") -> Presence:
    return Presence(
        presence_id=presence_id,
        state=PresenceState.CONFIRMED_MOVING,
        position=Position(zone="living_room", x=12.0, y=3.0, zone_confidence=0.8),
        moving=True,
        confidence=0.8,
        vitals=Vitals(respiration=RespirationStatus.BREATHING, breathing_bpm=21, person_confidence=0.88),
        presence_class=PresenceClass.ADULT,
        class_basis="respiration_rate",
        expected=False,
        provenance=PROV,
    )


def frame(*presences: Presence, at_s: float = 0.0) -> InteriorState:
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=True),
        presences=list(presences),
        floorplan=build_floorplan("site-demo-01"),
    )


def test_an_approved_presence_raises_no_notice():
    approved: set[str] = {"p4"}
    d = NoticeDetector(hold_s=5.0, is_suppressed=lambda pid: pid in approved)

    d.observe(frame(presence(), at_s=0))

    assert d.observe(frame(presence(), at_s=30)) == []


def test_approving_one_presence_does_not_suppress_another():
    """Two intruders, one vouched for. The other must still raise."""
    approved: set[str] = {"p4"}
    d = NoticeDetector(hold_s=5.0, is_suppressed=lambda pid: pid in approved)
    a, b = presence("p4"), presence("p6")
    d.observe(frame(a, b, at_s=0))

    raised = d.observe(frame(a, b, at_s=5))

    assert [n.presence_id for n in raised] == ["p6"]


def test_approving_mid_hold_stops_the_notice():
    """The resident can get ahead of it, and the hold is not already committed."""
    approved: set[str] = set()
    d = NoticeDetector(hold_s=5.0, is_suppressed=lambda pid: pid in approved)
    d.observe(frame(presence(), at_s=0))

    approved.add("p4")

    assert d.observe(frame(presence(), at_s=5)) == []


def test_no_suppressor_behaves_exactly_as_before():
    """The parameter is optional and the default path is unchanged."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))

    assert len(d.observe(frame(presence(), at_s=5))) == 1
