"""The runtime hook: a state event that qualifies produces a notice event."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings
from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import NoticeEvent, StateEvent
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
from hawkeye_backend.notices import NoticeDetector
from hawkeye_backend.runtime import HubRuntime
from hawkeye_backend.store import InMemoryStore

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)
PROV = Provenance(source=Source.RUVIEW_SIM, producer="sensor/")


class NoMaster:
    """A MasterClient that produces nothing. The runtime is what is under test."""

    async def start(self, sink) -> None: ...
    async def stop(self) -> None: ...


def frame(at_s: float, *, expected: bool | None = False) -> InteriorState:
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=True),
        presences=[
            Presence(
                presence_id="p4",
                state=PresenceState.CONFIRMED_MOVING,
                position=Position(zone="living_room", x=12.0, y=3.0, zone_confidence=0.8),
                moving=True,
                confidence=0.8,
                vitals=Vitals(
                    respiration=RespirationStatus.BREATHING,
                    breathing_bpm=21,
                    person_confidence=0.88,
                ),
                presence_class=PresenceClass.ADULT,
                class_basis="respiration_rate",
                expected=expected,
                provenance=PROV,
            )
        ],
        floorplan=build_floorplan("site-demo-01"),
    )


def a_runtime(sinks) -> HubRuntime:
    return HubRuntime(
        settings=Settings(_env_file=None),
        store=InMemoryStore(),
        bus=EventBus(),
        client=NoMaster(),
        detector=NoticeDetector(hold_s=5.0),
        notice_sinks=sinks,
    )


class Recorder:
    def __init__(self) -> None:
        self.seen = []

    async def deliver(self, notice) -> None:
        self.seen.append(notice)


async def test_a_qualifying_state_stream_raises_one_notice():
    rec = Recorder()
    rt = a_runtime([rec])

    await rt.emit(StateEvent(state=frame(0)))
    assert rec.seen == []

    await rt.emit(StateEvent(state=frame(5)))
    assert len(rec.seen) == 1
    assert rec.seen[0].presence_id == "p4"


async def test_the_notice_reaches_a_subscribed_app():
    """The stream sink is wired by the runtime, so a websocket client sees it."""
    rt = a_runtime([])
    sub = await rt.bus.subscribe()

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    payloads = []
    while not sub.queue.empty():
        payloads.append(sub.queue.get_nowait().payload)
    assert any(isinstance(p, NoticeEvent) for p in payloads)


async def test_a_notice_event_does_not_itself_run_the_detector():
    """Guards against unbounded recursion through emit."""
    rt = a_runtime([])

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    events = await rt.store.recent_events(200)
    notices = [e for e in events if isinstance(e.payload, NoticeEvent)]
    assert len(notices) == 1


async def test_an_expected_resident_raises_nothing():
    rec = Recorder()
    rt = a_runtime([rec])

    await rt.emit(StateEvent(state=frame(0, expected=True)))
    await rt.emit(StateEvent(state=frame(30, expected=True)))

    assert rec.seen == []


async def test_a_broken_detector_does_not_break_the_event_pipeline():
    """A notice is an addition to the event stream, never a risk to it.

    `emit` is the single path every event takes to reach the app. If a bug in
    the detector could propagate out of it, one bad tick would stop transcript
    lines and verification results reaching the resident mid-call.
    """

    class Exploding:
        def observe(self, state):
            raise RuntimeError("bookkeeping is wrong")

    rt = a_runtime([])
    rt.detector = Exploding()
    sub = await rt.bus.subscribe()

    await rt.emit(StateEvent(state=frame(0)))  # must not raise

    assert not sub.queue.empty()
    assert isinstance(sub.queue.get_nowait().payload, StateEvent)


async def test_vouching_on_the_camera_suppresses_the_notice():
    """The whole point of tapping a box: the banner stops.

    This is the seam that makes a vouch mean something. Without it the resident
    names the person on screen, the box turns green, and their wrist buzzes
    anyway - which is worse than not offering the control at all, because it
    teaches them the control does not work.
    """
    rec = Recorder()
    rt = a_runtime([rec])
    rt.camera_vouches.vouch(3, "Jordan")

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    assert rec.seen == []


async def test_a_vouch_that_lost_its_track_does_not_suppress_anything():
    """Only *held* vouches account for a body.

    One inside its grace window is a person who has left frame, and suppressing
    a notice on the strength of somebody who may no longer be in the room is the
    direction this must never fail in.
    """
    rec = Recorder()
    rt = a_runtime([rec])
    rt.camera_vouches.vouch(3, "Jordan")
    # The detector looked and found nobody, so the vouch is lapsing.
    rt.camera_vouches.observe(frozenset())

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    assert len(rec.seen) == 1


async def test_revoking_a_vouch_lets_the_notice_through_again():
    rec = Recorder()
    rt = a_runtime([rec])
    rt.camera_vouches.vouch(3, "Jordan")
    rt.camera_vouches.revoke(3)

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    assert len(rec.seen) == 1


async def test_vouching_for_more_people_than_are_there_cannot_raise_an_alarm():
    """Two namespaces meet in that sum, so it must only ever lower one.

    A vouch is keyed to a camera track and the headcount comes from the radio.
    An over-count suppresses a banner; it must never be able to manufacture one,
    which is what `unaccounted_count` flooring at zero buys.
    """
    rec = Recorder()
    rt = a_runtime([rec])
    for track_id in range(5):
        rt.camera_vouches.vouch(track_id, f"Guest {track_id}")

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    assert rec.seen == []
