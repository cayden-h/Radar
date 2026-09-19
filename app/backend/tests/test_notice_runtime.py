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
