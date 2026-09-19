"""Roster operations: remembering, matching, forgetting."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hawkeye_backend.household.roster import Roster, UnknownDevice
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.household import MemberKind, ObservedDevice, RememberRequest
from hawkeye_backend.store import InMemoryStore

AT = datetime(2026, 9, 19, 21, 4, tzinfo=UTC)
SALT = "site-demo-01-salt"
PROV = Provenance(source=Source.RUVIEW_SIM, producer="master/simulated")


def observed(device_id: str, identifier_hash: str) -> ObservedDevice:
    return ObservedDevice(
        device_id=device_id,
        identifier_hash=identifier_hash,
        fingerprint="a4:..:91",
        first_seen_at=AT,
        provenance=PROV,
    )


async def a_roster() -> Roster:
    return Roster(InMemoryStore(), salt=SALT)


async def test_remembering_with_a_device_binds_it():
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))

    member = await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    assert member.name == "Grandma"
    assert member.recognisable is True
    assert member.devices[0].identifier_hash == "a" * 64


async def test_remembering_without_a_device_is_allowed_and_not_recognisable():
    """A guest with no phone can still be named. The roster says it cannot see them."""
    r = await a_roster()

    member = await r.remember(RememberRequest(name="Plumber", device_id=None))

    assert member.recognisable is False
    assert member.devices == []


async def test_remembering_an_unknown_device_is_refused():
    """Binding a device nobody observed would create a member that can never match."""
    r = await a_roster()

    with pytest.raises(UnknownDevice):
        await r.remember(RememberRequest(name="Grandma", device_id="obs-nope"))


async def test_a_failed_binding_creates_no_member():
    """Atomic: a half-created member looks like a working roster and never matches."""
    r = await a_roster()

    with pytest.raises(UnknownDevice):
        await r.remember(RememberRequest(name="Grandma", device_id="obs-nope"))

    assert await r.members() == []


async def test_a_remembered_device_is_no_longer_unclaimed():
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    assert await r.unclaimed_devices() == []


async def test_an_unremembered_device_stays_unclaimed():
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))

    assert [d.device_id for d in await r.unclaimed_devices()] == ["obs-01"]


async def test_known_devices_present_counts_only_remembered_ones():
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.observe(observed("obs-02", "b" * 64))
    await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    present = [observed("x", "a" * 64), observed("y", "b" * 64)]

    assert await r.known_devices_present(present) == 1


async def test_forgetting_a_member_frees_their_device():
    """Removing someone must not leave a device claimed by nobody."""
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    member = await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    assert await r.forget(member.member_id) is True

    assert [d.device_id for d in await r.unclaimed_devices()] == ["obs-01"]


async def test_the_same_phone_observed_twice_is_one_unclaimed_device():
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.observe(observed("obs-99", "a" * 64))

    assert len(await r.unclaimed_devices()) == 1
