"""The roster: who the house is not surprised by.

Talks to `Store` and to nothing else. No HTTP, no FastAPI, no hub imports, so
this moves into `agents/intruder` as an import change.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.household import (
    HouseholdMember,
    KnownDevice,
    ObservedDevice,
    RememberRequest,
)
from hawkeye_backend.store import Store


class UnknownDevice(LookupError):
    """Asked to bind a device nobody has observed.

    Refused rather than tolerated: a member bound to a device that was never
    seen can never match anything, so the roster would look populated and
    recognise nobody.
    """


class DeviceAlreadyClaimed(LookupError):
    """That device already belongs to someone on the roster.

    Refused because one device must have exactly one owner. Two members holding
    one phone would each be counted as present when it appears, so the surplus
    would fall by two for one human, and an intruder would read as accounted
    for.
    """


class Roster:
    """Household membership, and matching observed devices against it.

    Takes no salt. Devices arrive with `identifier_hash` already computed by
    their producer, so this class only ever compares hash to hash and never
    sees a raw address. If something upstream ever hands it one, the salt comes
    back then rather than sitting here implying a responsibility it does not
    have.
    """

    def __init__(self, store: Store) -> None:
        self._store = store

    async def members(self) -> list[HouseholdMember]:
        return await self._store.list_members()

    async def observe(self, device: ObservedDevice) -> None:
        """Record a device seen on the network. Deduplicated by hash."""
        await self._store.put_observed_device(device)

    async def _claimed_hashes(self) -> set[str]:
        return {
            device.identifier_hash
            for member in await self._store.list_members()
            for device in member.devices
        }

    async def unclaimed_devices(self) -> list[ObservedDevice]:
        """Observed devices no member claims. The candidates for a binding."""
        claimed = await self._claimed_hashes()
        return [
            d for d in await self._store.list_observed_devices()
            if d.identifier_hash not in claimed
        ]

    async def remember(self, request: RememberRequest) -> HouseholdMember:
        """Create a member, optionally binding one observed device.

        One operation rather than create-then-bind. The two halves are
        meaningless apart, and a partial failure would leave a named member with
        no device, which is the state that looks like a working roster and
        silently recognises nobody.

        Atomic because the store write is the single terminal step: everything
        before it is object construction in locals, so a failure leaves nothing
        partial for a reader to find. A future store must preserve that, which
        means a member document appears whole or not at all.
        """
        device: KnownDevice | None = None
        if request.device_id is not None:
            observed = next(
                (d for d in await self._store.list_observed_devices()
                 if d.device_id == request.device_id),
                None,
            )
            if observed is None:
                raise UnknownDevice(request.device_id)
            if observed.identifier_hash in await self._claimed_hashes():
                raise DeviceAlreadyClaimed(request.device_id)
            device = KnownDevice(
                device_id=observed.device_id,
                identifier_hash=observed.identifier_hash,
                fingerprint=observed.fingerprint,
                added_at=utc_now(),
                last_seen_at=observed.first_seen_at,
            )

        member = HouseholdMember(
            member_id=f"mem-{uuid.uuid4().hex}",
            name=request.name,
            kind=request.kind,
            devices=[device] if device is not None else [],
            added_at=utc_now(),
            added_by="approval",
        )
        await self._store.put_member(member)
        return member

    async def forget(self, member_id: str) -> bool:
        """Remove a member. Their devices become unclaimed again rather than
        staying bound to nobody."""
        return await self._store.delete_member(member_id)

    async def known_devices_present(self, present: Iterable[ObservedDevice]) -> int:
        """How many roster MEMBERS have at least one device present.

        Counts people, not devices, because this number is subtracted from a
        count of people. One human carrying a phone and a watch is one human,
        and counting two would let them account for two presences: an intruder
        standing beside them would read as accounted for, which is the failure
        this feature exists to prevent.
        """
        present_hashes = {d.identifier_hash for d in present}
        return sum(
            1
            for member in await self._store.list_members()
            if any(d.identifier_hash in present_hashes for d in member.devices)
        )
