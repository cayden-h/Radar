"""Roster persistence, against whichever Store is configured."""

from __future__ import annotations

from datetime import UTC, datetime

from hawkeye_backend.models.household import HouseholdMember, KnownDevice, MemberKind
from hawkeye_backend.store import InMemoryStore

AT = datetime(2026, 9, 19, 21, 4, tzinfo=UTC)


def a_member(member_id: str = "mem-01", *, devices: list[KnownDevice] | None = None):
    return HouseholdMember(
        member_id=member_id,
        name="Grandma",
        kind=MemberKind.GUEST,
        devices=devices or [],
        added_at=AT,
        added_by="approval",
    )


async def test_a_member_round_trips():
    store = InMemoryStore()

    await store.put_member(a_member())

    assert [m.member_id for m in await store.list_members()] == ["mem-01"]


async def test_members_come_back_in_insertion_order():
    """The Household list should not reshuffle itself between reads."""
    store = InMemoryStore()
    for i in range(3):
        await store.put_member(a_member(f"mem-0{i}"))

    assert [m.member_id for m in await store.list_members()] == ["mem-00", "mem-01", "mem-02"]


async def test_putting_the_same_id_updates_rather_than_duplicates():
    store = InMemoryStore()
    await store.put_member(a_member())
    updated = a_member()
    updated.name = "Grandma Jean"

    await store.put_member(updated)

    members = await store.list_members()
    assert len(members) == 1
    assert members[0].name == "Grandma Jean"


async def test_deleting_a_member_removes_them():
    store = InMemoryStore()
    await store.put_member(a_member())

    assert await store.delete_member("mem-01") is True
    assert await store.list_members() == []


async def test_deleting_an_absent_member_reports_it():
    """The route turns this into a 404 rather than a cheerful 200."""
    store = InMemoryStore()

    assert await store.delete_member("mem-nope") is False


async def test_observed_devices_round_trip_and_deduplicate():
    """The same phone seen twice is one unclaimed device, not two."""
    from hawkeye_backend.models.common import Provenance, Source
    from hawkeye_backend.models.household import ObservedDevice

    store = InMemoryStore()
    prov = Provenance(source=Source.RUVIEW_SIM, producer="master/simulated")
    d = ObservedDevice(
        device_id="obs-01", identifier_hash="c" * 64, fingerprint="a4:..:91",
        first_seen_at=AT, provenance=prov,
    )

    await store.put_observed_device(d)
    await store.put_observed_device(d)

    assert len(await store.list_observed_devices()) == 1
