"""The runtime wires observed devices into the roster, and the roster's surplus
rule suppresses the notice once every confirmed person is accounted for.

Shape borrowed from `tests/test_notice_runtime.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings
from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import NoticeEvent, StateEvent
from hawkeye_backend.models.household import ObservedDevice, RememberRequest
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
ROUTER = Provenance(source=Source.RUVIEW_SIM, producer="master/simulated", detail="test fixture")


class NoMaster:
    """A MasterClient that produces nothing. The runtime is what is under test."""

    async def start(self, sink) -> None: ...
    async def stop(self) -> None: ...


def a_device(device_id: str = "obs-1") -> ObservedDevice:
    return ObservedDevice(
        device_id=device_id,
        identifier_hash="7" * 64,
        fingerprint="a4:..:01",
        provenance=ROUTER,
    )


def frame(
    *devices: ObservedDevice,
    at_s: float = 0.0,
    presences: list[Presence] | None = None,
) -> InteriorState:
    if presences is None:
        presences = [
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
                expected=False,
                provenance=PROV,
            )
        ]
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=True),
        presences=presences,
        associated_devices=list(devices),
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


async def test_a_device_on_a_frame_becomes_unclaimed():
    rt = a_runtime([])
    device = a_device()

    await rt.emit(StateEvent(state=frame(device, at_s=0)))

    unclaimed = await rt.roster.unclaimed_devices()
    assert [d.device_id for d in unclaimed] == ["obs-1"]


async def test_an_absent_field_means_not_reported_not_nobody_here():
    rt = a_runtime([])
    device = a_device()

    await rt.emit(StateEvent(state=frame(device, at_s=0)))
    await rt.emit(StateEvent(state=frame(at_s=5)))  # no devices reported this tick

    unclaimed = await rt.roster.unclaimed_devices()
    assert [d.device_id for d in unclaimed] == ["obs-1"]


async def test_a_roster_that_accounts_for_everyone_suppresses_the_notice():
    rec = Recorder()
    rt = a_runtime([rec])
    device = a_device()

    await rt.roster.observe(device)
    await rt.roster.remember(RememberRequest(name="Grandma", device_id=device.device_id))

    presences = [
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
            expected=False,
            provenance=PROV,
        )
    ]

    await rt.emit(StateEvent(state=frame(device, at_s=0, presences=presences)))
    await rt.emit(StateEvent(state=frame(device, at_s=30, presences=presences)))

    assert rec.seen == []


async def test_an_unremembered_device_does_not_suppress():
    rt = a_runtime([])
    device = a_device()

    await rt.emit(StateEvent(state=frame(device, at_s=0)))
    await rt.emit(StateEvent(state=frame(device, at_s=30)))

    events = await rt.store.recent_events(200)
    notices = [e for e in events if isinstance(e.payload, NoticeEvent)]
    assert len(notices) == 1


async def test_no_devices_reported_does_not_suppress():
    rt = a_runtime([])

    await rt.emit(StateEvent(state=frame(at_s=0)))
    await rt.emit(StateEvent(state=frame(at_s=30)))

    events = await rt.store.recent_events(200)
    notices = [e for e in events if isinstance(e.payload, NoticeEvent)]
    assert len(notices) == 1
