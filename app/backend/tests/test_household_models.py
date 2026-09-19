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


def test_recognisable_crosses_the_wire():
    """Serialized, not left for each client to recompute.

    Same reason `Provenance.source_class` is computed server-side: a derived
    fact with one source of truth cannot drift between consumers.
    """
    m = HouseholdMember(
        member_id="mem-01", name="Grandma", kind=MemberKind.GUEST,
        added_at=AT, added_by="approval",
    )

    assert m.model_dump()["recognisable"] is False
    assert '"recognisable":false' in m.model_dump_json().replace(" ", "")


def test_a_non_hex_identifier_is_rejected():
    """A digest that is not hex means the producer is broken, and a device that
    silently never matches is the worst way to find that out."""
    with pytest.raises(ValidationError):
        KnownDevice(
            device_id="dev-01",
            identifier_hash="z" * 64,
            fingerprint="a4:..:91",
            added_at=AT,
        )
