# Family Roster and Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a resident tell the house that a detected person is fine, either for now or permanently, so a visiting grandparent stops being an intruder every Sunday and a resident whose phone is off Wi-Fi stops being an intruder in their own home.

**Architecture:** A standalone `household/` package in the hub with no FastAPI and no hub imports, the way `verification/` is standalone, so it moves into `agents/intruder` as an import change. It owns three things: hashing a device identifier, the roster itself, and one pure function that decides whether the known devices present account for the confirmed people present. The hub calls that function today; `agents/intruder` calls the same function when it exists, so the rule that decides whether someone is an intruder has exactly one implementation. Approving a presence is a separate, session-scoped suppression that the notice detector consults.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest + pytest-asyncio, `hmac`/`hashlib` from the standard library. Swift 6 / SwiftUI on the client, no third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-09-19-family-roster-and-approval-design.md`

**Scope note:** the spec also calls for MongoDB Atlas persistence. That is a separate plan and a separate subsystem: seventeen `Store` protocol methods against Atlas, a driver, and a connection lifecycle. This plan runs entirely on `InMemoryStore` and must keep doing so, because the judging demo is specifically designed not to need a network. Do not add `motor` here.

**One refinement to the spec, made deliberately.** The spec says the surplus arithmetic stays in `agents/intruder`. Taken literally, remembering a visitor would have no visible effect until the agents exist, which makes the feature undemoable. Instead the rule lives in `household/accounting.py` as a pure function that the hub calls now and `intruder` imports later. That is sharing, not duplicating, and it is the same move `verification/` already made.

---

## File Structure

**Backend, created:**

| File | Responsibility |
|---|---|
| `app/backend/hawkeye_backend/models/household.py` | `MemberKind`, `KnownDevice`, `HouseholdMember`, `ObservedDevice`, request bodies. Data only. |
| `app/backend/hawkeye_backend/household/__init__.py` | Package re-exports. |
| `app/backend/hawkeye_backend/household/identity.py` | Hashing an observed address, and the human-readable fingerprint. Pure. |
| `app/backend/hawkeye_backend/household/roster.py` | The roster: add, remember, remove, and match an observed device. Talks to `Store`, no HTTP. |
| `app/backend/hawkeye_backend/household/accounting.py` | One pure function: do the known devices present account for the confirmed people present. |
| `app/backend/tests/test_household_identity.py` | Hashing and fingerprints. |
| `app/backend/tests/test_household_roster.py` | Roster operations and device matching. |
| `app/backend/tests/test_household_accounting.py` | The surplus rule. |
| `app/backend/tests/test_household_api.py` | The five routes. |

**Backend, modified:**

| File | Change |
|---|---|
| `models/state.py` | `InteriorState.associated_devices`. |
| `store.py` | Four roster methods on `Store` and `InMemoryStore`. |
| `notices/detector.py` | Optional `is_suppressed` callable. |
| `runtime.py` | Hold the roster and the approval set; pass suppression into the detector. |
| `api.py` | Five routes. |
| `master/simulated.py` | Emit `associated_devices` so the mock path exercises the flow. |
| `tools/gen_schema.py` | Household examples. |

**iOS, created:**

| File | Responsibility |
|---|---|
| `app/ios/HawkEye/Models/Household.swift` | Mirrors the Pydantic models. |
| `app/ios/HawkEye/Features/Home/RememberVisitorSheet.swift` | Name, device choice, confirm. |
| `app/ios/HawkEye/Features/Home/HouseholdList.swift` | Read-only roster plus delete. |

**iOS, modified:**

| File | Change |
|---|---|
| `Services/HawkEyeClient.swift` | Protocol gains roster reads and the two actions. |
| `Services/LiveHawkEyeClient.swift` | REST calls. |
| `Services/MockHawkEyeClient.swift` | In-memory roster so judging needs no hub. |
| `Features/Home/NoticeBanner.swift` | Two actions. |
| `Features/Home/HomeView.swift` | Sheet presentation and the header entry point. |

---

### Task 1: The household models

**Files:**
- Create: `app/backend/hawkeye_backend/models/household.py`
- Test: `app/backend/tests/test_household_models.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_household_models.py`:

```python
"""The household models, and the distinctions they are built to keep apart."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.household import (
    HouseholdMember,
    KnownDevice,
    MemberKind,
    ObservedDevice,
    RememberRequest,
)

AT = datetime(2026, 9, 19, 21, 4, tzinfo=UTC)


def a_device() -> KnownDevice:
    return KnownDevice(
        device_id="dev-01",
        identifier_hash="a" * 64,
        fingerprint="a4:..:91",
        label="iPhone",
        added_at=AT,
    )


def test_a_member_may_have_no_device():
    """A named guest who is not on the Wi-Fi is legal and meaningful.

    The system cannot auto-recognise them, and the roster says so rather than
    silently looking like it can.
    """
    m = HouseholdMember(
        member_id="mem-01",
        name="Grandma",
        kind=MemberKind.GUEST,
        added_at=AT,
        added_by="approval",
    )
    assert m.devices == []
    assert m.recognisable is False


def test_a_member_with_a_device_is_recognisable():
    m = HouseholdMember(
        member_id="mem-01",
        name="Grandma",
        kind=MemberKind.GUEST,
        devices=[a_device()],
        added_at=AT,
        added_by="approval",
    )
    assert m.recognisable is True


def test_added_by_is_a_closed_set():
    """How someone joined the roster is a fact the list surfaces, not free text."""
    with pytest.raises(ValidationError):
        HouseholdMember(
            member_id="mem-01",
            name="Grandma",
            kind=MemberKind.GUEST,
            added_at=AT,
            added_by="whatever",
        )


def test_an_observed_device_carries_provenance():
    """It is a reading like any other and is labelled like one."""
    d = ObservedDevice(
        device_id="obs-01",
        identifier_hash="b" * 64,
        fingerprint="de:..:07",
        first_seen_at=AT,
        provenance=Provenance(source=Source.RUVIEW_SIM, producer="master/simulated"),
    )
    assert d.provenance.simulated is True


def test_remember_accepts_a_null_device():
    """Naming a guest with no phone is the whole point of the null case."""
    r = RememberRequest(name="Grandma", kind=MemberKind.GUEST, device_id=None)
    assert r.device_id is None


def test_a_member_is_labelled_as_a_human_declaration():
    """The honesty rule applied to the roster.

    `caller` must be able to say "the resident says this person is expected" and
    must never be able to say "the system verified this person". The class is
    computed from the source, so the model cannot get this wrong.
    """
    m = HouseholdMember(
        member_id="mem-01", name="Grandma", kind=MemberKind.GUEST,
        added_at=AT, added_by="approval",
    )
    assert m.provenance.source_class == "human"
    assert m.provenance.simulated is False


def test_remember_rejects_a_blank_name():
    """An unnamed roster entry is indistinguishable from a bug three days later."""
    with pytest.raises(ValidationError):
        RememberRequest(name="   ", kind=MemberKind.GUEST, device_id=None)
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_household_models.py -q
```

Expected: `ModuleNotFoundError: No module named 'hawkeye_backend.models.household'`.

- [ ] **Step 3: Write the models**

Create `app/backend/hawkeye_backend/models/household.py`:

```python
"""Who belongs in this house, and what they carry.

A roster entry is a human declaration, never a sensed fact. CSI resolves a body
reflecting RF and cannot recognise a person, so every persistent identity here
comes from a device someone carries or from a resident saying so out loud.

The identifier is stored hashed. A roster is a list of which humans were in a
building and which devices they carry, and that is exactly the file that should
not be useful to whoever steals it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from hawkeye_backend.models.common import Provenance, Source, utc_now


class MemberKind(StrEnum):
    """Whether someone lives here or visits."""

    RESIDENT = "resident"
    GUEST = "guest"


class KnownDevice(BaseModel):
    """A device the roster recognises.

    `identifier_hash` is HMAC-SHA256 over the observed address under the site
    salt. The raw address is never stored, so a leaked roster does not become a
    device-tracking list for the house it came from.
    """

    device_id: str
    identifier_hash: str = Field(min_length=64, max_length=64)
    fingerprint: str = Field(description="Short and human-readable, for telling two phones apart.")
    label: str | None = None
    added_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime | None = None


class HouseholdMember(BaseModel):
    """One person the house is not surprised by."""

    member_id: str
    name: str
    kind: MemberKind
    devices: list[KnownDevice] = []
    added_at: datetime = Field(default_factory=utc_now)
    added_by: Literal["approval", "enrollment"] = Field(
        description=(
            "How they joined. Approving a live detection is a different kind of fact "
            "from being typed in during setup, and the Household list says which."
        )
    )
    provenance: Provenance = Field(
        default_factory=lambda: Provenance(source=Source.USER_INPUT, producer="app/ios"),
        description=(
            "A roster entry is a human declaration and is labelled as one. `USER_INPUT` "
            "maps to `SourceClass.HUMAN`, never to anything measured or inferred, so "
            "`caller` can say 'the resident says this person is expected' and cannot "
            "accidentally say 'the system verified this person'."
        ),
    )

    @property
    def recognisable(self) -> bool:
        """False means present but invisible to the roster.

        A named guest with no device is legal and useful, and the UI must render
        the difference rather than leaving it blank.
        """
        return bool(self.devices)


class ObservedDevice(BaseModel):
    """A device seen associated to the network, hashed on arrival.

    Carries `Provenance` because it is a reading like any other. On the mock
    path that provenance says simulated, and nothing downstream has to guess.
    """

    device_id: str
    identifier_hash: str = Field(min_length=64, max_length=64)
    fingerprint: str
    first_seen_at: datetime = Field(default_factory=utc_now)
    provenance: Provenance


class RememberRequest(BaseModel):
    """Name a person and optionally bind the device that just appeared."""

    name: str
    kind: MemberKind = MemberKind.GUEST
    device_id: str | None = Field(
        default=None,
        description="An unclaimed device to bind, or null for a guest with no phone.",
    )

    @field_validator("name")
    @classmethod
    def _name_is_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("a roster entry needs a name")
        return cleaned
```

- [ ] **Step 4: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_household_models.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/backend/hawkeye_backend/models/household.py app/backend/tests/test_household_models.py
git commit -m "Add the household models"
```

---

### Task 2: Hashing a device identifier

**Files:**
- Create: `app/backend/hawkeye_backend/household/__init__.py`
- Create: `app/backend/hawkeye_backend/household/identity.py`
- Test: `app/backend/tests/test_household_identity.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_household_identity.py`:

```python
"""Device identifiers, and the property that makes storing them safe."""

from __future__ import annotations

from hawkeye_backend.household.identity import fingerprint, hash_identifier

MAC = "a4:83:e7:2c:19:91"
SALT = "site-demo-01-salt"


def test_the_same_address_hashes_the_same_way():
    """Matching an observed device is hashing it and comparing."""
    assert hash_identifier(MAC, SALT) == hash_identifier(MAC, SALT)


def test_case_and_separator_do_not_change_the_hash():
    """Routers report MACs in several shapes and they are the same device."""
    assert hash_identifier("A4:83:E7:2C:19:91", SALT) == hash_identifier("a4-83-e7-2c-19-91", SALT)
    assert hash_identifier("a483e72c1991", SALT) == hash_identifier(MAC, SALT)


def test_a_different_salt_gives_a_different_hash():
    """A roster leaked from one house does not identify devices in another."""
    assert hash_identifier(MAC, SALT) != hash_identifier(MAC, "some-other-house")


def test_the_hash_is_sixty_four_hex_characters():
    h = hash_identifier(MAC, SALT)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_the_raw_address_is_not_recoverable_from_the_hash():
    """Stated as a test so nobody later stores the address 'just for debugging'."""
    h = hash_identifier(MAC, SALT)
    assert "a4" not in h[:2] or True  # the point is the next line
    assert MAC.replace(":", "") not in h


def test_the_fingerprint_is_short_and_stable():
    """Enough to tell two phones apart in one room, not enough to track one."""
    f = fingerprint(MAC, SALT)
    assert f == fingerprint(MAC, SALT)
    assert len(f) <= 12
    assert f.startswith("a4")


def test_different_devices_get_different_fingerprints():
    assert fingerprint(MAC, SALT) != fingerprint("b8:27:eb:11:22:33", SALT)
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_household_identity.py -q
```

Expected: `ModuleNotFoundError: No module named 'hawkeye_backend.household'`.

- [ ] **Step 3: Create the package**

Create `app/backend/hawkeye_backend/household/__init__.py`:

```python
"""Who belongs in this house.

Standalone: no FastAPI imports and no hub imports, the way `verification/` is
standalone, so this moves into `agents/intruder` as an import change rather than
a rewrite.
"""

from hawkeye_backend.household.identity import fingerprint, hash_identifier

__all__ = ["fingerprint", "hash_identifier"]
```

- [ ] **Step 4: Write the hashing**

Create `app/backend/hawkeye_backend/household/identity.py`:

```python
"""Turning an observed network address into something safe to store.

The roster never holds a raw MAC. It holds an HMAC of one under a per-site salt,
so matching still works and a stolen roster is not a list of which devices visit
which house.

HMAC rather than a bare SHA-256 because the input space is small enough to
enumerate: the whole 48-bit MAC space is brute-forceable, and vendor prefixes cut
it far below that. A keyed hash makes the salt necessary to test a guess.
"""

from __future__ import annotations

import hashlib
import hmac


def _normalise(address: str) -> str:
    """One canonical form, because routers report several.

    `A4:83:E7:2C:19:91`, `a4-83-e7-2c-19-91` and `a483e72c1991` are one device,
    and hashing them differently would silently fail to match a remembered guest.
    """
    return "".join(c for c in address.lower() if c in "0123456789abcdef")


def hash_identifier(address: str, salt: str) -> str:
    """HMAC-SHA256 of a normalised address under the site salt. 64 hex chars."""
    return hmac.new(salt.encode(), _normalise(address).encode(), hashlib.sha256).hexdigest()


def fingerprint(address: str, salt: str) -> str:
    """A short label so a human can tell two phones in one room apart.

    The real first octet, then four hex of the hash. The octet is a vendor
    prefix rather than a device identity, and four hex is far too few to search,
    so this discloses essentially nothing while still being stable and readable.
    """
    normalised = _normalise(address)
    head = normalised[:2] if len(normalised) >= 2 else "??"
    return f"{head}:..:{hash_identifier(address, salt)[:4]}"
```

- [ ] **Step 5: Run the tests**

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/household/ app/backend/tests/test_household_identity.py
git commit -m "Hash device identifiers under a per-site salt"
```

---

### Task 3: Roster storage

**Files:**
- Modify: `app/backend/hawkeye_backend/store.py`
- Test: `app/backend/tests/test_household_store.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_household_store.py`:

```python
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
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: `AttributeError: 'InMemoryStore' object has no attribute 'put_member'`.

- [ ] **Step 3: Extend the Store protocol**

In `app/backend/hawkeye_backend/store.py`, add to the imports:

```python
from hawkeye_backend.models.household import HouseholdMember, ObservedDevice
```

Add to the `Store` protocol, after `next_seq`:

```python
    async def put_member(self, member: HouseholdMember) -> None: ...

    async def list_members(self) -> list[HouseholdMember]: ...

    async def delete_member(self, member_id: str) -> bool: ...

    async def put_observed_device(self, device: ObservedDevice) -> None: ...

    async def list_observed_devices(self) -> list[ObservedDevice]: ...
```

- [ ] **Step 4: Implement on InMemoryStore**

Add to `InMemoryStore.__init__`:

```python
        self._members: dict[str, HouseholdMember] = {}
        self._observed: dict[str, ObservedDevice] = {}
```

Add the methods to `InMemoryStore`:

```python
    async def put_member(self, member: HouseholdMember) -> None:
        # dict preserves insertion order and replaces in place, so an update
        # does not reshuffle the Household list under the reader.
        self._members[member.member_id] = member

    async def list_members(self) -> list[HouseholdMember]:
        return list(self._members.values())

    async def delete_member(self, member_id: str) -> bool:
        return self._members.pop(member_id, None) is not None

    async def put_observed_device(self, device: ObservedDevice) -> None:
        # Keyed by hash rather than by device_id: the same phone seen across two
        # frames is one unclaimed device, and the router may renumber its table.
        existing = self._observed.get(device.identifier_hash)
        if existing is not None:
            return
        self._observed[device.identifier_hash] = device

    async def list_observed_devices(self) -> list[ObservedDevice]:
        return list(self._observed.values())
```

Add the same five methods to `MongoStore`, each raising the existing
`NotImplementedError` the class already raises from `__init__`, so the protocol
stays satisfied. The class raises on construction, so the bodies are never
reached:

```python
    async def put_member(self, member: HouseholdMember) -> None: ...

    async def list_members(self) -> list[HouseholdMember]: ...

    async def delete_member(self, member_id: str) -> bool: ...

    async def put_observed_device(self, device: ObservedDevice) -> None: ...

    async def list_observed_devices(self) -> list[ObservedDevice]: ...
```

- [ ] **Step 5: Run the tests**

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/store.py app/backend/tests/test_household_store.py
git commit -m "Persist the roster behind the Store protocol"
```

---

### Task 4: The accounting rule

This is the task that decides whether remembering a visitor actually does anything. Write the tests first and do not shortcut them.

**Files:**
- Create: `app/backend/hawkeye_backend/household/accounting.py`
- Test: `app/backend/tests/test_household_accounting.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_household_accounting.py`:

```python
"""The surplus rule: do the devices present account for the people present.

This is the one place that rule exists. `agents/intruder` imports this same
function when it is written, rather than reimplementing it, because two copies
of the rule that decides whether someone is an intruder will drift.
"""

from __future__ import annotations

from hawkeye_backend.household.accounting import unaccounted_count


def test_two_people_two_known_devices_is_accounted_for():
    assert unaccounted_count(people=2, known_devices_present=2) == 0


def test_one_more_person_than_devices_is_a_surplus_of_one():
    """The claim a 1x1 radio can actually support: at least one more presence
    than the roster accounts for."""
    assert unaccounted_count(people=3, known_devices_present=2) == 1


def test_more_devices_than_people_is_not_negative():
    """Phones outnumber people constantly: a tablet, a watch, a laptop.

    Surplus is a floor at zero, never a negative that would later cancel out a
    real intruder in some future sum.
    """
    assert unaccounted_count(people=2, known_devices_present=5) == 0


def test_nobody_home_is_accounted_for():
    assert unaccounted_count(people=0, known_devices_present=0) == 0


def test_a_person_with_no_devices_reported_is_a_surplus():
    """Devices absent from a frame means not reported, and the rule is
    conservative: it does not assume everyone is accounted for."""
    assert unaccounted_count(people=1, known_devices_present=0) == 1
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: `ModuleNotFoundError: No module named 'hawkeye_backend.household.accounting'`.

- [ ] **Step 3: Write the rule**

Create `app/backend/hawkeye_backend/household/accounting.py`:

```python
"""Does the roster account for who is in the building.

One function, deliberately. `agents/intruder` owns this decision conceptually
and will import this when it exists; having the hub reimplement it would produce
two versions of the rule that decides whether to treat someone as an intruder,
and they would drift.

Phrase the output as a surplus, never as arithmetic on an exact headcount. A 1x1
radio resolves presence, not a number of people: two people within about a metre
merge into one. What survives that limit is "at least one more presence than the
roster accounts for", which only requires noticing that an additional presence
appeared. See `agents/occupancy` for the counting limits.
"""

from __future__ import annotations


def unaccounted_count(*, people: int, known_devices_present: int) -> int:
    """How many confirmed people the known devices do not account for.

    Floors at zero. Phones routinely outnumber people, and a negative surplus
    would be a credit that silently cancelled a real intruder in a later sum.
    """
    return max(0, people - known_devices_present)
```

- [ ] **Step 4: Run the tests**

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/backend/hawkeye_backend/household/accounting.py app/backend/tests/test_household_accounting.py
git commit -m "Add the surplus rule, in one place"
```

---

### Task 5: The roster service

**Files:**
- Create: `app/backend/hawkeye_backend/household/roster.py`
- Modify: `app/backend/hawkeye_backend/household/__init__.py`
- Test: `app/backend/tests/test_household_roster.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_household_roster.py`:

```python
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
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: `ModuleNotFoundError: No module named 'hawkeye_backend.household.roster'`.

- [ ] **Step 3: Write the roster**

Create `app/backend/hawkeye_backend/household/roster.py`:

```python
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


class Roster:
    """Household membership, and matching observed devices against it."""

    def __init__(self, store: Store, *, salt: str) -> None:
        self._store = store
        self._salt = salt

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
            device = KnownDevice(
                device_id=observed.device_id,
                identifier_hash=observed.identifier_hash,
                fingerprint=observed.fingerprint,
                added_at=utc_now(),
                last_seen_at=observed.first_seen_at,
            )

        member = HouseholdMember(
            member_id=f"mem-{uuid.uuid4().hex[:8]}",
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
        """How many of the devices currently present belong to the roster.

        Counts distinct hashes, so one phone reported twice in a frame does not
        account for two people.
        """
        claimed = await self._claimed_hashes()
        return len({d.identifier_hash for d in present if d.identifier_hash in claimed})
```

- [ ] **Step 4: Export it**

Replace `app/backend/hawkeye_backend/household/__init__.py`:

```python
"""Who belongs in this house.

Standalone: no FastAPI imports and no hub imports, the way `verification/` is
standalone, so this moves into `agents/intruder` as an import change rather than
a rewrite.
"""

from hawkeye_backend.household.accounting import unaccounted_count
from hawkeye_backend.household.identity import fingerprint, hash_identifier
from hawkeye_backend.household.roster import Roster, UnknownDevice

__all__ = [
    "Roster",
    "UnknownDevice",
    "fingerprint",
    "hash_identifier",
    "unaccounted_count",
]
```

- [ ] **Step 5: Run the tests**

Expected: `9 passed`. Full suite: `83 + 6 + 7 + 6 + 5 + 9 = 116 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/household/ app/backend/tests/test_household_roster.py
git commit -m "Add the roster service"
```

---

### Task 6: Approval, and suppressing a notice

**Files:**
- Modify: `app/backend/hawkeye_backend/notices/detector.py`
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Test: `app/backend/tests/test_household_approval.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_household_approval.py`:

```python
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
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: `TypeError: NoticeDetector.__init__() got an unexpected keyword argument 'is_suppressed'`.

- [ ] **Step 3: Add suppression to the detector**

In `app/backend/hawkeye_backend/notices/detector.py`, add to the imports:

```python
from collections.abc import Callable
```

Change `__init__` to:

```python
    def __init__(
        self,
        hold_s: float = 5.0,
        forget_after_s: float = 900.0,
        is_suppressed: Callable[[str], bool] | None = None,
    ) -> None:
        if hold_s < 0 or forget_after_s < 0:
            raise ValueError("hold_s and forget_after_s must not be negative")
        self.hold_s = hold_s
        self.forget_after_s = forget_after_s
        # A resident saying "this person is fine" is a human override of a
        # machine inference, and it only ever lowers an alarm. Consulted here
        # rather than filtered downstream so an approved presence never starts a
        # hold at all, and approving mid-hold stops the notice.
        self._is_suppressed = is_suppressed
        self._since: dict[str, datetime] = {}
        self._fired: dict[str, datetime] = {}
```

In `observe`, immediately after the `qualifying` dict is built, add:

```python
        if self._is_suppressed is not None:
            qualifying = {
                pid: p for pid, p in qualifying.items() if not self._is_suppressed(pid)
            }
```

- [ ] **Step 4: Hold approvals on the runtime**

In `app/backend/hawkeye_backend/runtime.py`, add to `__init__`, before the detector is constructed:

```python
        # Presences the resident has vouched for, this session only. Deliberately
        # not persisted: a new session reuses presence ids, so a stored approval
        # would silently vouch for a stranger.
        self.approved_presences: set[str] = set()
```

and change the detector default construction to pass the suppressor:

```python
        self.detector = detector or NoticeDetector(
            hold_s=settings.notice_hold_s,
            forget_after_s=settings.notice_forget_after_s,
            is_suppressed=self.approved_presences.__contains__,
        )
```

- [ ] **Step 5: Run the tests**

Expected: `4 passed`, and the full suite `120 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/notices/detector.py app/backend/hawkeye_backend/runtime.py app/backend/tests/test_household_approval.py
git commit -m "Let a resident approve a presence, suppressing its notice"
```

---

### Task 7: Carry observed devices on interior state

**Files:**
- Modify: `app/backend/hawkeye_backend/models/state.py`
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Test: `app/backend/tests/test_household_observation.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_household_observation.py`:

```python
"""Devices arriving on a state frame become unclaimed roster candidates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings
from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import StateEvent
from hawkeye_backend.models.household import ObservedDevice
from hawkeye_backend.models.state import Calibration, InteriorState
from hawkeye_backend.runtime import HubRuntime
from hawkeye_backend.store import InMemoryStore

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)
PROV = Provenance(source=Source.RUVIEW_SIM, producer="master/simulated")


class NoMaster:
    async def start(self, sink) -> None: ...
    async def stop(self) -> None: ...


def frame(*devices: ObservedDevice, at_s: float = 0.0) -> InteriorState:
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=True),
        presences=[],
        floorplan=build_floorplan("site-demo-01"),
        associated_devices=list(devices),
    )


def a_device(device_id: str = "obs-01") -> ObservedDevice:
    return ObservedDevice(
        device_id=device_id,
        identifier_hash="a" * 64,
        fingerprint="a4:..:91",
        first_seen_at=T0,
        provenance=PROV,
    )


def a_runtime() -> HubRuntime:
    return HubRuntime(
        settings=Settings(_env_file=None),
        store=InMemoryStore(),
        bus=EventBus(),
        client=NoMaster(),
    )


async def test_a_device_on_a_frame_becomes_unclaimed():
    rt = a_runtime()

    await rt.emit(StateEvent(state=frame(a_device())))

    assert [d.device_id for d in await rt.roster.unclaimed_devices()] == ["obs-01"]


async def test_an_absent_field_means_not_reported_not_nobody_here():
    """A frame without the field must not wipe what was already observed."""
    rt = a_runtime()
    await rt.emit(StateEvent(state=frame(a_device())))

    await rt.emit(StateEvent(state=frame(at_s=1)))

    assert len(await rt.roster.unclaimed_devices()) == 1
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: `ValidationError` about an unexpected keyword `associated_devices`, or `AttributeError: 'HubRuntime' object has no attribute 'roster'`.

- [ ] **Step 3: Add the field**

In `app/backend/hawkeye_backend/models/state.py`, add to the imports:

```python
from hawkeye_backend.models.household import ObservedDevice
```

Add to `InteriorState`, after `presences`:

```python
    associated_devices: list[ObservedDevice] = Field(
        default_factory=list,
        description=(
            "Devices the router reports associated, hashed by the producer. An "
            "absent field means not reported, never that nobody is here."
        ),
    )
```

- [ ] **Step 4: Record them on the runtime**

In `app/backend/hawkeye_backend/runtime.py`, add to the imports:

```python
from hawkeye_backend.household import Roster
```

Add to `__init__`, after the approvals set:

```python
        self.roster = Roster(store, salt=settings.site_id)
```

In `emit`, inside the existing `if isinstance(payload, StateEvent):` block and
before the detector runs, add:

```python
            # Record before detecting. A device that arrived on this frame should
            # be a binding candidate by the time the notice about it lands.
            for device in payload.state.associated_devices:
                await self.roster.observe(device)

            # This is where remembering a visitor starts to mean something.
            #
            # `Presence.expected` is decided upstream and knows nothing about
            # this hub's roster, so without this the roster would be a list
            # nobody consults and "Remember this visitor" would change nothing
            # about the next visit.
            #
            # The rule itself lives in household/accounting.py and is called
            # rather than reimplemented, so `agents/intruder` and the hub cannot
            # drift on the question of whether someone is unaccounted for.
            #
            # It can only ever lower an alarm. With no devices reported,
            # `known_devices_present` is 0, the surplus equals the headcount,
            # and nothing is suppressed: an absent field means not reported,
            # never that everyone is accounted for.
            people = sum(1 for p in payload.state.presences if p.state in PERSON_STATES)
            known = await self.roster.known_devices_present(payload.state.associated_devices)
            if unaccounted_count(people=people, known_devices_present=known) == 0:
                return
```

Add to the imports in `runtime.py`:

```python
from hawkeye_backend.household import Roster, unaccounted_count
from hawkeye_backend.notices.detector import PERSON_STATES
```

`PERSON_STATES` is currently the private `_PERSON_STATES` in `notices/detector.py`.
Rename it to `PERSON_STATES` and update its use inside that file. It is now shared
by two modules, and a leading underscore on a name two files import is a lie about
its scope.

Add these tests to `app/backend/tests/test_household_observation.py`:

```python
def a_person(presence_id: str = "p1") -> Presence:
    return Presence(
        presence_id=presence_id,
        state=PresenceState.CONFIRMED_MOVING,
        position=Position(zone="living_room", x=12.0, y=3.0, zone_confidence=0.8),
        moving=True,
        confidence=0.8,
        vitals=Vitals(
            respiration=RespirationStatus.BREATHING, breathing_bpm=16, person_confidence=0.9
        ),
        presence_class=PresenceClass.ADULT,
        class_basis="respiration_rate",
        expected=False,
        provenance=PROV,
    )


async def test_a_roster_that_accounts_for_everyone_suppresses_the_notice():
    """The whole point of remembering a visitor.

    `expected` is decided upstream and knows nothing about this hub's roster, so
    without this the roster would be a list nobody consults.
    """
    rt = a_runtime()
    device = a_device()
    await rt.emit(StateEvent(state=frame(device)))
    await rt.roster.remember(RememberRequest(name="Grandma", device_id=device.device_id))

    state = frame(device, at_s=1)
    state.presences = [a_person()]
    rec = Recorder()
    rt.notice_sinks.append(rec)

    await rt.emit(StateEvent(state=state))
    state2 = frame(device, at_s=30)
    state2.presences = [a_person()]
    await rt.emit(StateEvent(state=state2))

    assert rec.seen == []


async def test_an_unremembered_device_does_not_suppress():
    """An unclaimed device accounts for nobody, so the surplus stands."""
    rt = a_runtime()
    device = a_device()

    state = frame(device)
    state.presences = [a_person()]
    await rt.emit(StateEvent(state=state))
    state2 = frame(device, at_s=30)
    state2.presences = [a_person()]
    await rt.emit(StateEvent(state=state2))

    events = await rt.store.recent_events(200)
    assert any(isinstance(e.payload, NoticeEvent) for e in events)


async def test_no_devices_reported_does_not_suppress():
    """Absent means not reported, never that everyone is accounted for."""
    rt = a_runtime()

    state = frame()
    state.presences = [a_person()]
    await rt.emit(StateEvent(state=state))
    state2 = frame(at_s=30)
    state2.presences = [a_person()]
    await rt.emit(StateEvent(state=state2))

    events = await rt.store.recent_events(200)
    assert any(isinstance(e.payload, NoticeEvent) for e in events)
```

Add the imports those tests need: `NoticeEvent` from `models.events`, `RememberRequest`
from `models.household`, `Position`, `Presence`, `PresenceClass`, `PresenceState`,
`RespirationStatus`, `Vitals` from `models.state`, and a `Recorder` sink class
matching the one in `tests/test_notice_runtime.py`.

- [ ] **Step 5: Run the tests**

Expected: `2 passed`, full suite `122 passed`.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/models/state.py app/backend/hawkeye_backend/runtime.py app/backend/tests/test_household_observation.py
git commit -m "Carry observed devices on interior state"
```

---

### Task 8: The API

**Files:**
- Modify: `app/backend/hawkeye_backend/api.py`
- Test: `app/backend/tests/test_household_api.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_household_api.py`:

```python
"""The five household routes, against a real app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(_env_file=None, mode="simulated"))
    with TestClient(app) as c:
        yield c


def test_an_empty_household_is_an_empty_list_not_an_error(client: TestClient):
    r = client.get("/v1/household")

    assert r.status_code == 200
    assert r.json() == {"members": []}


def test_remembering_without_a_device_creates_a_member(client: TestClient):
    r = client.post("/v1/household/remember", json={"name": "Grandma", "kind": "guest"})

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Grandma"
    assert body["devices"] == []


def test_remembering_a_device_nobody_saw_is_a_404(client: TestClient):
    """Not a 500. The app asked to bind something that is not there, which is a
    client-visible condition, and the message says which device."""
    r = client.post(
        "/v1/household/remember",
        json={"name": "Grandma", "kind": "guest", "device_id": "obs-nope"},
    )

    assert r.status_code == 404
    assert "obs-nope" in r.json()["detail"]


def test_a_blank_name_is_rejected_by_validation(client: TestClient):
    r = client.post("/v1/household/remember", json={"name": "   ", "kind": "guest"})

    assert r.status_code == 422


def test_a_remembered_member_appears_in_the_household(client: TestClient):
    client.post("/v1/household/remember", json={"name": "Grandma", "kind": "guest"})

    names = [m["name"] for m in client.get("/v1/household").json()["members"]]

    assert names == ["Grandma"]


def test_deleting_a_member_removes_them(client: TestClient):
    member_id = client.post(
        "/v1/household/remember", json={"name": "Grandma", "kind": "guest"}
    ).json()["member_id"]

    assert client.delete(f"/v1/household/members/{member_id}").status_code == 204
    assert client.get("/v1/household").json()["members"] == []


def test_deleting_an_absent_member_is_a_404(client: TestClient):
    assert client.delete("/v1/household/members/mem-nope").status_code == 404


def test_approving_a_presence_is_accepted_and_idempotent(client: TestClient):
    """Approving twice is not an error. A resident tapping twice under stress is
    not a condition worth surfacing."""
    assert client.post("/v1/presences/p4/approve").status_code == 202
    assert client.post("/v1/presences/p4/approve").status_code == 202


def test_unclaimed_devices_is_empty_before_anything_is_observed(client: TestClient):
    r = client.get("/v1/household/unclaimed-devices")

    assert r.status_code == 200
    assert r.json() == {"devices": []}
```

- [ ] **Step 2: Run it and confirm it fails**

Expected: 404s, because the routes do not exist.

- [ ] **Step 3: Write the routes**

In `app/backend/hawkeye_backend/api.py`, add to the imports:

```python
from hawkeye_backend.household import UnknownDevice
from hawkeye_backend.models.household import HouseholdMember, ObservedDevice, RememberRequest
```

Add these response models near the other local models in the file:

```python
class HouseholdResponse(BaseModel):
    """The roster. A list rather than a bare array so the shape can grow."""

    members: list[HouseholdMember]


class UnclaimedDevicesResponse(BaseModel):
    devices: list[ObservedDevice]
```

If `BaseModel` is not already imported in `api.py`, add `from pydantic import BaseModel`.

Add the routes at the end of the file, before the websocket route:

```python
@router.get("/household", response_model=HouseholdResponse, summary="Who belongs here")
async def get_household(request: Request) -> HouseholdResponse:
    """The roster. Read-only: members are added by approving a real detection."""
    return HouseholdResponse(members=await _runtime(request).roster.members())


@router.get(
    "/household/unclaimed-devices",
    response_model=UnclaimedDevicesResponse,
    summary="Devices no member claims",
)
async def get_unclaimed_devices(request: Request) -> UnclaimedDevicesResponse:
    """Candidates for a binding, newest last. The app shows these when the
    resident chooses to remember a visitor."""
    return UnclaimedDevicesResponse(devices=await _runtime(request).roster.unclaimed_devices())


@router.post(
    "/household/remember",
    response_model=HouseholdMember,
    status_code=201,
    summary="Remember a visitor",
)
async def post_remember(request: Request, body: RememberRequest) -> HouseholdMember:
    """Name a person and optionally bind the device that just appeared.

    201 because this creates something that outlives the request, which is the
    whole difference between this and approving a presence.
    """
    try:
        return await _runtime(request).roster.remember(body)
    except UnknownDevice as exc:
        raise HTTPException(
            status_code=404, detail=f"no observed device with id {exc.args[0]!r}"
        ) from exc


@router.delete(
    "/household/members/{member_id}",
    status_code=204,
    summary="Forget a member",
)
async def delete_member(request: Request, member_id: str) -> None:
    """Remove a member. Their devices become unclaimed rather than orphaned."""
    if not await _runtime(request).roster.forget(member_id):
        raise HTTPException(status_code=404, detail=f"no member with id {member_id!r}")


@router.post(
    "/presences/{presence_id}/approve",
    status_code=202,
    summary="Vouch for a presence, this session only",
)
async def post_approve_presence(request: Request, presence_id: str) -> dict[str, str]:
    """A human override of a machine inference. It only ever lowers an alarm.

    Not persisted: presence ids are reused across sessions, so a stored approval
    would silently vouch for a stranger. Idempotent, because a resident tapping
    twice under stress is not a condition worth surfacing.
    """
    _runtime(request).approved_presences.add(presence_id)
    return {"presence_id": presence_id, "status": "approved"}
```

- [ ] **Step 4: Run the tests**

Expected: `9 passed`, full suite `131 passed`.

- [ ] **Step 5: Verify the OpenAPI docs render**

```bash
cd app/backend && .venv/bin/python -c "
from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
paths = sorted(p for p in create_app(Settings(_env_file=None)).openapi()['paths'] if 'household' in p or 'approve' in p)
print('\n'.join(paths))
"
```

Expected: all five paths listed.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/api.py app/backend/tests/test_household_api.py
git commit -m "Expose the household routes"
```

---

### Task 9: The mock supplies devices, and the schema records them

**Files:**
- Modify: `app/backend/hawkeye_backend/master/simulated.py`
- Modify: `app/backend/tools/gen_schema.py`

- [ ] **Step 1: Emit devices from the simulated master**

Read `master/simulated.py` first and find `_presence` and where `InteriorState` is
constructed. Add a module-level constant near the existing `CSI` provenance:

```python
# The router's association table, simulated. No router integration exists yet,
# so this is labelled rather than presented as measured. Swapping in the real
# table is a producer change behind a field that already exists.
ROUTER = Provenance(
    source=Source.RUVIEW_SIM,
    producer="master/simulated",
    detail="association table, simulated; no router integration exists yet",
)
```

Add a helper alongside `_presence`:

```python
    def _resident_devices(self) -> list[ObservedDevice]:
        """Two resident phones, always associated.

        The intruder deliberately has no device: that surplus is what makes the
        presence unexpected, and it is what the resident later resolves by
        remembering a visitor.
        """
        return [
            ObservedDevice(
                device_id="obs-resident-1",
                identifier_hash="1" * 64,
                fingerprint="a4:..:1c",
                provenance=ROUTER,
            ),
            ObservedDevice(
                device_id="obs-resident-2",
                identifier_hash="2" * 64,
                fingerprint="b8:..:7e",
                provenance=ROUTER,
            ),
        ]
```

Add `associated_devices=self._resident_devices()` to every `InteriorState(...)`
construction in the file. Import `ObservedDevice` from
`hawkeye_backend.models.household`.

- [ ] **Step 2: Confirm the suite still passes**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `131 passed`.

- [ ] **Step 3: Add household examples to the schema generator**

In `app/backend/tools/gen_schema.py`, add the imports:

```python
from hawkeye_backend.models.household import HouseholdMember, KnownDevice, MemberKind, ObservedDevice
```

Add two example files, following the shape the neighbouring entries use:

```python
    write(
        "household.json",
        HouseholdMember(
            member_id="mem-4f2a91cc",
            name="Grandma",
            kind=MemberKind.GUEST,
            devices=[
                KnownDevice(
                    device_id="obs-01",
                    identifier_hash="9" * 64,
                    fingerprint="a4:..:91",
                    label="iPhone",
                    added_at=at(60.0),
                    last_seen_at=at(60.0),
                )
            ],
            added_at=at(60.0),
            added_by="approval",
        ),
    )
    write(
        "observed-device.json",
        ObservedDevice(
            device_id="obs-01",
            identifier_hash="9" * 64,
            fingerprint="a4:..:91",
            first_seen_at=at(55.0),
            provenance=Provenance(
                source=Source.RUVIEW_SIM,
                producer="master/simulated",
                detail="association table, simulated; no router integration exists yet",
            ),
        ),
    )
```

- [ ] **Step 4: Regenerate and confirm determinism**

```bash
cd app/backend && .venv/bin/python tools/gen_schema.py
cd app/backend && md5 -q schema/household.json
cd app/backend && .venv/bin/python tools/gen_schema.py
cd app/backend && md5 -q schema/household.json
```

Expected: the two hashes match. If they differ, the example carries a
non-deterministic timestamp; pass an explicit `at(...)` the way the neighbours do.

- [ ] **Step 5: Commit**

```bash
git add app/backend/hawkeye_backend/master/simulated.py app/backend/tools/gen_schema.py app/backend/schema/
git commit -m "Simulate the association table and record the household schema"
```

---

### Task 10: The iOS models and client

**Files:**
- Create: `app/ios/HawkEye/Models/Household.swift`
- Modify: `app/ios/HawkEye/Services/HawkEyeClient.swift`
- Modify: `app/ios/HawkEye/Services/LiveHawkEyeClient.swift`
- Modify: `app/ios/HawkEye/Services/MockHawkEyeClient.swift`

- [ ] **Step 1: Write the model**

Create `app/ios/HawkEye/Models/Household.swift`:

```swift
import Foundation

/// Who the house is not surprised by.
///
/// Matched field for field against `app/backend/schema/household.json` and
/// `observed-device.json`.
///
/// A roster entry is a human declaration, never a sensed fact. The radio resolves
/// a body, not a person, and this app must never present it as more than that.
struct HouseholdMember: Codable, Sendable, Hashable, Identifiable {

    enum Kind: String, Codable, Sendable, Hashable, CaseIterable {
        case resident
        case guest

        var label: String {
            switch self {
            case .resident: "Lives here"
            case .guest: "Visitor"
            }
        }
    }

    /// How they joined the roster. The Household list says which, because
    /// approving a live detection is a different kind of fact from typing a name.
    enum AddedBy: String, Codable, Sendable, Hashable {
        case approval
        case enrollment
    }

    var memberID: String
    var name: String
    var kind: Kind
    var devices: [KnownDevice] = []
    var addedAt: Date
    var addedBy: AddedBy

    var id: String { memberID }

    /// False means present but invisible to the roster. The list renders this
    /// rather than leaving it blank, because the difference matters and is
    /// otherwise unknowable.
    ///
    /// Read off the wire rather than computed from `devices`. The hub computes
    /// it, for the same reason it computes `Provenance.sourceClass`: a derived
    /// fact that decides what the UI may imply about identifying someone gets
    /// one source of truth, not one per client.
    var isRecognisable: Bool

    enum CodingKeys: String, CodingKey {
        case name, kind, devices
        case memberID = "member_id"
        case addedAt = "added_at"
        case addedBy = "added_by"
        case isRecognisable = "recognisable"
    }
}

/// A device the roster recognises. The raw address never leaves the hub.
struct KnownDevice: Codable, Sendable, Hashable, Identifiable {
    var deviceID: String
    var fingerprint: String
    var label: String?
    var addedAt: Date
    var lastSeenAt: Date?

    var id: String { deviceID }

    enum CodingKeys: String, CodingKey {
        case fingerprint, label
        case deviceID = "device_id"
        case addedAt = "added_at"
        case lastSeenAt = "last_seen_at"
    }
}

/// A device seen on the network that no member claims. A binding candidate.
struct ObservedDevice: Codable, Sendable, Hashable, Identifiable {
    var deviceID: String
    var fingerprint: String
    var firstSeenAt: Date
    var provenance: Provenance

    var id: String { deviceID }

    enum CodingKeys: String, CodingKey {
        case fingerprint, provenance
        case deviceID = "device_id"
        case firstSeenAt = "first_seen_at"
    }
}
```

Note the Swift `KnownDevice` deliberately omits `identifier_hash`. The client has
no use for it and a value the UI never needs is a value that cannot leak from the
UI. Decoding ignores unknown keys, so this is safe.

- [ ] **Step 2: Extend the client protocol**

In `app/ios/HawkEye/Services/HawkEyeClient.swift`, add to `HawkEyeClienting`
after `dismissNotice`:

```swift
    /// The roster. Empty until loaded.
    var household: [HouseholdMember] { get }

    /// Devices seen on the network that nobody claims. Binding candidates.
    var unclaimedDevices: [ObservedDevice] { get }

    /// Vouch for a presence, this session only. Suppresses its notices.
    func approvePresence(_ presenceID: String) async throws

    /// Name a visitor and optionally bind a device. Permanent.
    func rememberVisitor(name: String, kind: HouseholdMember.Kind, deviceID: String?) async throws

    /// Remove a member. Their devices become unclaimed again.
    func forgetMember(_ memberID: String) async throws

    /// Refresh the roster and the unclaimed device list.
    func refreshHousehold() async
```

- [ ] **Step 3: Implement on the live client**

In `LiveHawkEyeClient.swift`, add alongside the other `private(set) var`s:

```swift
    private(set) var household: [HouseholdMember] = []
    private(set) var unclaimedDevices: [ObservedDevice] = []
```

Add the methods, using whatever helpers the file already has for REST calls
(`get`, `post`; read the existing `raiseIncident` and `sendContext` to match):

```swift
    func approvePresence(_ presenceID: String) async throws {
        _ = try await postNoBody("/v1/presences/\(presenceID)/approve")
    }

    func rememberVisitor(
        name: String, kind: HouseholdMember.Kind, deviceID: String?
    ) async throws {
        struct Body: Encodable {
            let name: String
            let kind: String
            let device_id: String?
        }
        let member: HouseholdMember = try await post(
            "/v1/household/remember",
            body: Body(name: name, kind: kind.rawValue, device_id: deviceID)
        )
        household.append(member)
        unclaimedDevices.removeAll { $0.deviceID == deviceID }
    }

    func forgetMember(_ memberID: String) async throws {
        _ = try await delete("/v1/household/members/\(memberID)")
        household.removeAll { $0.memberID == memberID }
    }

    func refreshHousehold() async {
        struct HouseholdResponse: Decodable { let members: [HouseholdMember] }
        struct DevicesResponse: Decodable { let devices: [ObservedDevice] }
        household = (try? await get("/v1/household", as: HouseholdResponse.self))?.members ?? household
        unclaimedDevices = (try? await get("/v1/household/unclaimed-devices", as: DevicesResponse.self))?.devices ?? unclaimedDevices
    }
```

If the file has no `delete` or `postNoBody` helper, add them next to the existing
request helpers rather than inlining `URLRequest` construction at the call sites.

- [ ] **Step 4: Implement on the mock client**

In `MockHawkEyeClient.swift`, add:

```swift
    private(set) var household: [HouseholdMember] = []
    private(set) var unclaimedDevices: [ObservedDevice] = [
        // The intruder's phone, so the judging demo can bind something without a
        // hub. The two resident phones are already claimed and so are not here.
        ObservedDevice(
            deviceID: "obs-visitor",
            fingerprint: "c8:..:2f",
            firstSeenAt: Date(),
            provenance: Provenance(
                source: .ruviewSim,
                producer: "MockHawkEyeClient",
                ansname: nil,
                detail: "association table, simulated",
                sourceClass: .simulated,
                simulated: true
            )
        )
    ]

    func approvePresence(_ presenceID: String) async throws {
        approvedPresences.insert(presenceID)
        notices.removeAll { $0.presenceID == presenceID }
    }

    func rememberVisitor(
        name: String, kind: HouseholdMember.Kind, deviceID: String?
    ) async throws {
        let devices: [KnownDevice] = deviceID.flatMap { id in
            unclaimedDevices.first { $0.deviceID == id }.map {
                [KnownDevice(deviceID: $0.deviceID, fingerprint: $0.fingerprint,
                             label: nil, addedAt: Date(), lastSeenAt: $0.firstSeenAt)]
            }
        } ?? []
        household.append(
            HouseholdMember(
                memberID: "mem-\(UUID().uuidString.prefix(8))",
                name: name, kind: kind, devices: devices,
                addedAt: Date(), addedBy: .approval
            )
        )
        if let deviceID { unclaimedDevices.removeAll { $0.deviceID == deviceID } }
    }

    func forgetMember(_ memberID: String) async throws {
        household.removeAll { $0.memberID == memberID }
    }

    func refreshHousehold() async {}
```

Add `private var approvedPresences: Set<String> = []` alongside the other state,
and in `raiseNoticeIfDue()` add `guard !approvedPresences.contains(intruder.presenceID) else { return }`
so an approved presence stops re-raising. Reset both in `disconnect()` and `resolve()`.

Check `Provenance`'s memberwise initializer before writing the mock device: if
`sourceClass` and `simulated` are stored rather than computed, they must be
supplied as shown.

- [ ] **Step 5: Parse-check**

```bash
cd app/ios && find HawkEye -name '*.swift' -print0 | xargs -0 swiftc -parse -swift-version 6
```

Expected: no output, exit 0.

- [ ] **Step 6: Regenerate and commit**

```bash
cd app/ios && xcodegen generate
git add app/ios/HawkEye/Models/Household.swift app/ios/HawkEye/Services/
git commit -m "Carry the household on both hub clients"
```

---

### Task 11: The app surface

**Files:**
- Create: `app/ios/HawkEye/Features/Home/RememberVisitorSheet.swift`
- Create: `app/ios/HawkEye/Features/Home/HouseholdList.swift`
- Modify: `app/ios/HawkEye/Features/Home/NoticeBanner.swift`
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift`

- [ ] **Step 1: Add the two actions to the banner**

In `NoticeBanner.swift`, change the initializer to take two closures:

```swift
    let notice: Notice
    let onApprove: () -> Void
    let onRemember: () -> Void
    let onDismiss: () -> Void
```

Below the existing title and body `VStack`, add an action row:

```swift
            HStack(spacing: Space.sm) {
                Button("This is expected", action: onApprove)
                    .buttonStyle(.plain)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.personUnexpected)

                Button("Remember this visitor", action: onRemember)
                    .buttonStyle(.plain)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }
            .padding(.top, 2)
```

Two buttons with different words, deliberately. One is a mute button and the
other changes what the house believes, and a single control for both would
persist strangers because someone wanted a banner to go away.

Keep the banner visual only. No haptic and no sound, now or later: a burglary
defaults to silent mode because a phone that buzzes gives away someone hiding.

Read `DesignSystem/` and substitute the real token names if any of the above do
not exist. Do not add new tokens.

- [ ] **Step 2: Write the remember sheet**

Create `app/ios/HawkEye/Features/Home/RememberVisitorSheet.swift`:

```swift
import SwiftUI

/// Naming a visitor, and choosing what to bind them to.
///
/// The device choice is explicit and defaults to nothing. Binding is an
/// inference from timing, not proof: "the device that just appeared" and "the
/// person I am approving" are correlated, and two people arriving together can
/// bind the wrong phone. So the sheet shows what it is about to remember and
/// makes the resident confirm it, rather than deciding quietly.
struct RememberVisitorSheet: View {
    let candidates: [ObservedDevice]
    let onSave: (String, HouseholdMember.Kind, String?) -> Void
    let onCancel: () -> Void

    @State private var name: String = ""
    @State private var kind: HouseholdMember.Kind = .guest
    @State private var deviceID: String?

    private var canSave: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Who is this?") {
                    TextField("Name", text: $name)
                    Picker("They", selection: $kind) {
                        ForEach(HouseholdMember.Kind.allCases, id: \.self) { k in
                            Text(k.label).tag(k)
                        }
                    }
                }

                Section("Device") {
                    Picker("Recognise by", selection: $deviceID) {
                        Text("No device").tag(String?.none)
                        ForEach(candidates) { device in
                            Text(device.fingerprint).tag(String?.some(device.deviceID))
                        }
                    }
                    Text(deviceID == nil
                         ? "Without a device they will not be recognised automatically next time."
                         : "This phone joined the network just now. If someone else arrived at the same moment, pick theirs instead.")
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }
            }
            .navigationTitle("Remember visitor")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: onCancel)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { onSave(name, kind, deviceID) }
                        .disabled(!canSave)
                }
            }
        }
    }
}
```

- [ ] **Step 3: Write the household list**

Create `app/ios/HawkEye/Features/Home/HouseholdList.swift`:

```swift
import SwiftUI

/// Who the house knows. Read-only, plus delete.
///
/// There is no add button on purpose. `app/CLAUDE.md` says this app is not a
/// dashboard, and adding happens by approving a real detection, which is also
/// the only moment the system actually has a device to bind.
struct HouseholdList: View {
    let members: [HouseholdMember]
    let onForget: (String) -> Void
    let onClose: () -> Void

    var body: some View {
        NavigationStack {
            Group {
                if members.isEmpty {
                    ContentUnavailableView(
                        "Nobody yet",
                        systemImage: "person.2",
                        description: Text("People are added when you recognise them on an alert.")
                    )
                } else {
                    List {
                        ForEach(members) { member in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(member.name).font(TypeScale.body)
                                Text(detail(for: member))
                                    .font(TypeScale.caption)
                                    .foregroundStyle(Palette.inkMuted)
                            }
                        }
                        .onDelete { indexes in
                            indexes.map { members[$0].memberID }.forEach(onForget)
                        }
                    }
                }
            }
            .navigationTitle("Household")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: onClose)
                }
            }
        }
    }

    /// Says plainly when someone cannot be recognised, rather than leaving the
    /// line blank and letting the roster look like it can see everyone.
    private func detail(for member: HouseholdMember) -> String {
        guard member.isRecognisable else {
            return "\(member.kind.label) · no device, will not be recognised automatically"
        }
        let fingerprints = member.devices.map(\.fingerprint).joined(separator: ", ")
        return "\(member.kind.label) · \(fingerprints)"
    }
}
```

- [ ] **Step 4: Wire both into HomeView**

In `HomeView.swift`, add state:

```swift
    @State private var rememberingNotice: Notice?
    @State private var showingHousehold = false
```

Change the notice `ForEach` to pass the new closures:

```swift
            ForEach(client.notices) { notice in
                NoticeBanner(
                    notice: notice,
                    onApprove: {
                        // A notice with no presence is nothing to vouch for, so
                        // dismissing is the whole action. Passing an empty id
                        // would approve a presence that does not exist.
                        guard let presenceID = notice.presenceID else {
                            withAnimation(Motion.standard) { client.dismissNotice(notice.id) }
                            return
                        }
                        Task {
                            try? await client.approvePresence(presenceID)
                            withAnimation(Motion.standard) { client.dismissNotice(notice.id) }
                        }
                    },
                    onRemember: { rememberingNotice = notice },
                    onDismiss: {
                        withAnimation(Motion.standard) { client.dismissNotice(notice.id) }
                    }
                )
                .transition(.move(edge: .top).combined(with: .opacity))
            }
```

Add the sheets to the outermost view:

```swift
        .sheet(item: $rememberingNotice) { notice in
            RememberVisitorSheet(
                candidates: client.unclaimedDevices,
                onSave: { name, kind, deviceID in
                    Task {
                        try? await client.rememberVisitor(name: name, kind: kind, deviceID: deviceID)
                        if let presenceID = notice.presenceID {
                            try? await client.approvePresence(presenceID)
                        }
                        client.dismissNotice(notice.id)
                        rememberingNotice = nil
                    }
                },
                onCancel: { rememberingNotice = nil }
            )
        }
        .sheet(isPresented: $showingHousehold) {
            HouseholdList(
                members: client.household,
                onForget: { id in Task { try? await client.forgetMember(id) } },
                onClose: { showingHousehold = false }
            )
        }
        .task { await client.refreshHousehold() }
```

Remembering a visitor also approves the presence, because the resident has just
said who it is and leaving the banner up afterwards would read as the system not
having listened.

Add a Household entry point to the existing header, matching whatever control the
header already uses:

```swift
                Button { showingHousehold = true } label: {
                    Image(systemName: "person.2")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Palette.inkMuted)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Household")
```

`Notice` must be `Identifiable` for `.sheet(item:)`. It already is, via
`noticeID`. Read the view's property declarations and use its real accessor name
rather than assuming `client`.

- [ ] **Step 5: Parse-check and build**

```bash
cd app/ios && find HawkEye -name '*.swift' -print0 | xargs -0 swiftc -parse -swift-version 6
cd app/ios && xcodegen generate
cd app/ios && xcodebuild -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' build
```

Expected: `** BUILD SUCCEEDED **`.

- [ ] **Step 6: Add a UI tour and look at it**

Create `app/ios/HawkEyeUITests/HouseholdTour.swift`:

```swift
import XCTest

/// Remembering a visitor, in the built app.
///
/// This is the flow shown at the judging table, and it runs entirely on the mock
/// path, so it cannot be broken by the room.
final class HouseholdTour: XCTestCase {

    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
    }

    func testRememberingAVisitorClearsTheNoticeAndPopulatesTheHousehold() {
        let home = app.buttons.containing(.staticText, identifier: "Home").firstMatch
        XCTAssertTrue(home.waitForExistence(timeout: 20), "no hub row appeared")
        home.tap()

        let remember = app.buttons["Remember this visitor"].firstMatch
        XCTAssertTrue(remember.waitForExistence(timeout: 60), "no notice with a remember action")
        remember.tap()

        let name = app.textFields["Name"].firstMatch
        XCTAssertTrue(name.waitForExistence(timeout: 10), "the remember sheet did not open")
        name.tap()
        name.typeText("Grandma")
        app.buttons["Save"].firstMatch.tap()

        // The banner goes, because the resident just said who that is.
        XCTAssertFalse(
            app.buttons["Remember this visitor"].firstMatch.waitForExistence(timeout: 5),
            "the notice survived being resolved"
        )

        app.buttons["Household"].firstMatch.tap()
        XCTAssertTrue(
            app.staticTexts["Grandma"].firstMatch.waitForExistence(timeout: 10),
            "the remembered visitor is not in the household"
        )
    }
}
```

Run it:

```bash
cd app/ios && xcodegen generate
cd app/ios && xcodebuild test -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:HawkEyeUITests/HouseholdTour
```

Expected: `** TEST SUCCEEDED **`.

Then look at it. Be picky: check the two banner actions do not wrap onto two
lines on the narrowest device, that the sheet's device picker reads clearly when
there is exactly one candidate, and that the household list's "no device" line is
legible rather than crowded. Fix anything that looks off.

- [ ] **Step 7: Commit**

```bash
git add app/ios/HawkEye/Features/Home/ app/ios/HawkEyeUITests/HouseholdTour.swift
git commit -m "Approve and remember, from the notice"
```

---

### Task 12: Documentation

**Files:**
- Modify: `app/CLAUDE.md`, `app/ios/README.md`, `app/backend/README.md`, `docs/swapping-in-real-parts.md`

- [ ] **Step 1: `app/CLAUDE.md`**

In the notices paragraph under "Raising an incident", add after the trigger-rule
sentence:

```markdown
A notice is answerable, not just readable.
**This is expected** vouches for that presence for this session and nothing persists.
**Remember this visitor** names the person and optionally binds the device that just joined the
network, so the next visit raises nothing at all.
They are separate controls with separate words on purpose: one is a mute button and the other
changes what the house believes, and a single control for both would persist strangers because
someone wanted a banner to go away.

The roster is reached through the notice and through a read-only Household list in the header.
There is still no settings screen, and that rule still holds: adding someone happens by approving a
real detection, which is also the only moment the system has a device to bind.
```

- [ ] **Step 2: `app/ios/README.md`**

Add to the list describing what the app renders, matching the neighbouring style:

```markdown
- **The household.** A notice carries two actions. "This is expected" vouches for that presence for
  the session; "Remember this visitor" opens a sheet that names them and optionally binds the device
  that just appeared. The Household list in the header is read-only plus swipe-to-delete, and it says
  plainly when a member has no device and so will not be recognised automatically. `HouseholdTour`
  covers the whole flow on the mock path, which is what makes it safe to show at a judging table.
```

- [ ] **Step 3: `app/backend/README.md`**

Add a `## Household` section after `## Notices`:

```markdown
## Household

Who the house is not surprised by. `hawkeye_backend/household/` is standalone, with no FastAPI and
no hub imports, the way `verification/` is, so it moves into `agents/intruder` as an import change.

| Route | What it does |
|---|---|
| `GET /v1/household` | The roster. |
| `GET /v1/household/unclaimed-devices` | Devices seen associated that no member claims. |
| `POST /v1/household/remember` | Name a person, optionally bind a device. 404 if the device was never observed. |
| `DELETE /v1/household/members/{id}` | Forget a member; their devices become unclaimed. |
| `POST /v1/presences/{id}/approve` | Vouch for a presence. Session-scoped, never persisted. |

Device identifiers are stored as HMAC-SHA256 under the site salt, never in the clear. A roster is a
list of which humans were in a building and what they carry, which is exactly the file that should
not be useful to whoever steals it.

`household/accounting.py` holds the surplus rule and is the only copy of it. `agents/intruder` imports
this when it exists rather than reimplementing it, because two versions of the rule that decides
whether someone is an intruder will drift.
```

- [ ] **Step 4: `docs/swapping-in-real-parts.md`**

Add a section after the notice one, matching the file's format:

```markdown
## The household roster

**What is simulated: the association table.** No router integration exists, so `associated_devices`
on a state frame comes from `master/simulated.py` with `Provenance` saying `ruview-sim` and a detail
of "association table, simulated". Swapping in the real table is a producer change behind a field
that already exists, and nothing above it moves.

**What is real:** the roster itself, the hashing, the matching, the approval, and the record that a
human made the decision.

**How to tell which you are looking at:** the Household list shows a device fingerprint per member.
Simulated ones come from the fixed set in `master/simulated.py`. Real ones will not.

**The half-flipped state that looks like something else:** a member remembered with no device is
legal and is not a bug. They were named by a resident and carry no phone the system can see, so they
will never be auto-recognised. The Household list says "no device, will not be recognised
automatically" for exactly this reason. If every member reads that way, the association table is not
arriving at all, which is a different problem: check `associated_devices` on a state frame.
```

- [ ] **Step 5: Check for em dashes and commit**

```bash
grep -rn "—" app/CLAUDE.md app/ios/README.md app/backend/README.md docs/swapping-in-real-parts.md
```

Expected: nothing you added.

```bash
git add app/CLAUDE.md app/ios/README.md app/backend/README.md docs/swapping-in-real-parts.md
git commit -m "Document the household roster and approval"
```

---

## Final verification

- [ ] **Backend suite green**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `131 passed`.

- [ ] **Schema and client agree**

```bash
cd app/backend && .venv/bin/python tools/gen_schema.py && git diff --stat schema/
```

Expected: no diff.

- [ ] **App builds and every tour passes**

```bash
cd app/ios && xcodegen generate
cd app/ios && xcodebuild test -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:HawkEyeUITests
```

Expected: `** TEST SUCCEEDED **` with four tours passing.

- [ ] **The whole flow, end to end against a real hub**

```bash
cd app/backend && HAWKEYE_MODE=simulated HAWKEYE_SIM_AUTOSTART=true .venv/bin/python -m hawkeye_backend.main
```

In another shell:

```bash
curl -s localhost:8787/v1/household/unclaimed-devices | head -c 400
curl -s -X POST localhost:8787/v1/household/remember \
  -H 'content-type: application/json' \
  -d '{"name":"Grandma","kind":"guest","device_id":"obs-resident-1"}'
curl -s localhost:8787/v1/household | head -c 400
```

Expected: the devices list is non-empty, the remember call returns 201 with a
member carrying one device, and the household then lists Grandma. Kill the hub
afterwards.

## One spec requirement deliberately not implemented here

The spec says every roster change is sealed into `agents/replay`, for the same reason an incident is:
the decision that a stranger was welcome is exactly the decision an investigator would want
afterwards.

This plan does not do that, and the omission is deliberate rather than an oversight.

Sealing a roster change means putting it on the event log, which means a tenth `EventKind` and a
matching Swift case, and the replay surface that would read it is itself unbuilt. Adding the event
without the surface produces an audit trail nobody can look at, which is the shape of a feature that
gets called done and never finishes.

What this plan does instead keeps the facts: every member carries `added_at`, `added_by`, and
`USER_INPUT` provenance, so the record of who was vouched for and how exists in the roster itself. A
deletion is the lossy case, and that is the gap.

Pick it up with the replay work, not before, and implement both halves together.

## Final verification, continued

- [ ] **The rule has exactly one implementation**

```bash
grep -rn "max(0, people\|people - known" app/backend/hawkeye_backend/ | grep -v accounting.py
```

Expected: no output. If anything else computes a surplus, it is a second copy of
the rule and must be replaced with a call to `unaccounted_count`.
