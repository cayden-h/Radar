"""Roster operations: remembering, matching, forgetting."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hawkeye_backend.household.roster import DeviceAlreadyClaimed, Roster, UnknownDevice
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.household import (
    HouseholdMember,
    KnownDevice,
    MemberKind,
    ObservedDevice,
    RememberRequest,
)
from hawkeye_backend.store import InMemoryStore

AT = datetime(2026, 9, 19, 21, 4, tzinfo=UTC)
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
    return Roster(InMemoryStore())


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


async def test_one_member_with_two_devices_counts_as_one_person():
    """The failure this feature exists to prevent.

    A resident carrying a phone and a watch is one human. Counting their
    devices would let them account for two presences, and an intruder beside
    them would read as accounted for.
    """
    store = InMemoryStore()
    r = Roster(store)
    member = HouseholdMember(
        member_id="mem-01",
        name="Resident",
        kind=MemberKind.RESIDENT,
        devices=[
            KnownDevice(device_id="d1", identifier_hash="a" * 64, fingerprint="a4:..:01"),
            KnownDevice(device_id="d2", identifier_hash="b" * 64, fingerprint="b8:..:02"),
        ],
        added_by="enrollment",
    )
    await store.put_member(member)

    present = [observed("x", "a" * 64), observed("y", "b" * 64)]

    assert await r.known_devices_present(present) == 1


async def test_two_members_with_a_device_each_count_as_two_people():
    """The other direction, so the fix does not simply always return one."""
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.observe(observed("obs-02", "b" * 64))
    await r.remember(RememberRequest(name="A", device_id="obs-01"))
    await r.remember(RememberRequest(name="B", device_id="obs-02"))

    present = [observed("x", "a" * 64), observed("y", "b" * 64)]

    assert await r.known_devices_present(present) == 2


async def test_a_device_cannot_be_claimed_twice():
    """One device, one owner. Two owners would halve the surplus for one human."""
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    with pytest.raises(DeviceAlreadyClaimed):
        await r.remember(RememberRequest(name="Impostor", device_id="obs-01"))


async def test_a_refused_double_claim_creates_no_member():
    """Still atomic on the new failure path."""
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))

    with pytest.raises(DeviceAlreadyClaimed):
        await r.remember(RememberRequest(name="Impostor", device_id="obs-01"))

    assert [m.name for m in await r.members()] == ["Grandma"]


async def test_a_device_freed_by_forgetting_can_be_claimed_again():
    """Forgetting must actually release the device, not just hide the member."""
    r = await a_roster()
    await r.observe(observed("obs-01", "a" * 64))
    first = await r.remember(RememberRequest(name="Grandma", device_id="obs-01"))
    await r.forget(first.member_id)

    second = await r.remember(RememberRequest(name="Grandma again", device_id="obs-01"))

    assert second.recognisable is True
