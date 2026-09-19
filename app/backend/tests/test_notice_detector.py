"""The trigger rule.

The detector is driven by `state.captured_at` rather than a wall clock, so
every test here advances time by constructing a frame rather than by sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.state import (
    Calibration,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.notices.detector import NoticeDetector

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)

PROV = Provenance(source=Source.RUVIEW_SIM, producer="sensor/")


def presence(
    presence_id: str = "p4",
    *,
    state: PresenceState = PresenceState.CONFIRMED_MOVING,
    expected: bool | None = False,
    zone: str = "living_room",
) -> Presence:
    return Presence(
        presence_id=presence_id,
        state=state,
        position=Position(zone=zone, x=12.0, y=3.0, zone_confidence=0.8),
        moving=True,
        confidence=0.8,
        vitals=Vitals(respiration=RespirationStatus.BREATHING, breathing_bpm=21, person_confidence=0.88),
        presence_class=PresenceClass.ADULT,
        class_basis="respiration_rate",
        expected=expected,
        provenance=PROV,
    )


def frame(*presences: Presence, at_s: float = 0.0, healthy: bool = True) -> InteriorState:
    # `floorplan` is required on InteriorState - it has no default - so the
    # enrolled plan is built here. It is also what makes the room name in the
    # notice body real rather than a fallback.
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=healthy),
        presences=list(presences),
        floorplan=build_floorplan("site-demo-01"),
    )


def test_nothing_fires_before_the_hold_elapses():
    """Five seconds means five seconds. A notice is unrecallable once sent."""
    d = NoticeDetector(hold_s=5.0)

    assert d.observe(frame(presence(), at_s=0)) == []
    assert d.observe(frame(presence(), at_s=2)) == []
    assert d.observe(frame(presence(), at_s=4.9)) == []


def test_it_fires_once_the_hold_elapses():
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))

    raised = d.observe(frame(presence(), at_s=5.0))

    assert len(raised) == 1
    assert raised[0].presence_id == "p4"
    assert raised[0].zone == "living_room"
    assert raised[0].title == "Unexpected person"
    assert raised[0].provenance.producer == "agents/intruder"


def test_it_fires_exactly_once_however_many_frames_follow():
    """A presence walking room to room is one event, not five."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(presence(), at_s=5.0))

    later = [d.observe(frame(presence(zone="kitchen"), at_s=t)) for t in (6, 7, 8, 30)]

    assert later == [[], [], [], []]


def test_flicker_below_the_hold_resets_the_timer():
    """`expected` can flicker while agents/intruder is still resolving."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(expected=False), at_s=0))
    d.observe(frame(presence(expected=True), at_s=3))

    # The clock restarts from the frame it came back on, so t=8 is only 3s in.
    d.observe(frame(presence(expected=False), at_s=5))
    assert d.observe(frame(presence(expected=False), at_s=8)) == []
    assert len(d.observe(frame(presence(expected=False), at_s=10))) == 1


def test_an_unconfirmed_perturbation_never_fires():
    """The curtain over the dryer vent is not a person and never becomes one here."""
    d = NoticeDetector(hold_s=5.0)
    curtain = presence("p5", state=PresenceState.UNCONFIRMED, expected=False, zone="laundry")

    d.observe(frame(curtain, at_s=0))

    assert d.observe(frame(curtain, at_s=30)) == []


def test_an_unhealthy_baseline_suppresses_everything():
    """A stale baseline invents presences. Texting someone at 3am on one is its own harm."""
    d = NoticeDetector(hold_s=5.0)

    d.observe(frame(presence(), at_s=0, healthy=False))

    assert d.observe(frame(presence(), at_s=30, healthy=False)) == []


def test_an_unhealthy_baseline_resets_an_in_flight_hold():
    """The hold must be five seconds of trustworthy observation, not five of any."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(presence(), at_s=3, healthy=False))

    assert d.observe(frame(presence(), at_s=6)) == []
    assert len(d.observe(frame(presence(), at_s=11))) == 1


def test_an_expected_resident_never_fires():
    d = NoticeDetector(hold_s=5.0)
    resident = presence("p1", expected=True, zone="second_bedroom")

    d.observe(frame(resident, at_s=0))

    assert d.observe(frame(resident, at_s=30)) == []


def test_a_null_expected_never_fires():
    """null means not yet decided. A frame that omits it must not make intruders."""
    d = NoticeDetector(hold_s=5.0)
    undecided = presence("p2", expected=None)

    d.observe(frame(undecided, at_s=0))

    assert d.observe(frame(undecided, at_s=30)) == []


def test_two_unexpected_presences_each_get_their_own_notice():
    d = NoticeDetector(hold_s=5.0)
    a, b = presence("p4"), presence("p6", zone="kitchen")
    d.observe(frame(a, b, at_s=0))

    raised = d.observe(frame(a, b, at_s=5))

    assert sorted(n.presence_id for n in raised) == ["p4", "p6"]


def test_a_presence_that_disappears_and_returns_restarts_the_hold():
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(at_s=2))

    assert d.observe(frame(presence(), at_s=4)) == []
    assert len(d.observe(frame(presence(), at_s=9))) == 1


def test_the_body_uses_the_room_name_from_the_floorplan():
    """The resident reads 'Living room', not 'living_room'."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))

    raised = d.observe(frame(presence(), at_s=5))

    assert raised[0].body == "Not accounted for. Living room."
