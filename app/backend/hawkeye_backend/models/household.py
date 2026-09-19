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
