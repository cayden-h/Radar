"""The notice model, and its place in the envelope union."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import EnvelopeAdapter, EventKind, NoticeEvent, envelope
from hawkeye_backend.models.notice import Notice, NoticeSeverity


def a_notice() -> Notice:
    return Notice(
        notice_id="ntc-p4",
        severity=NoticeSeverity.ATTENTION,
        title="Unexpected person",
        body="Not accounted for. Living room.",
        zone="living_room",
        presence_id="p4",
        raised_at=datetime(2026, 9, 19, 21, 4, tzinfo=UTC),
        provenance=Provenance(
            source=Source.AGENT_INFERENCE,
            producer="agents/intruder",
            ansname="ans://v1.0.0.intruder.hawkeye.example",
        ),
    )


def test_notice_carries_derived_provenance():
    """The honesty rule applies here exactly as it does to a reading."""
    n = a_notice()
    assert n.provenance.source_class == "derived"
    assert n.provenance.simulated is False


def test_notice_round_trips_through_the_envelope_union():
    """A notice decodes back as a NoticeEvent and not as something else."""
    env = envelope(seq=7, payload=NoticeEvent(notice=a_notice()))
    raw = env.model_dump_json()

    decoded = EnvelopeAdapter.validate_json(raw)

    assert decoded.kind is EventKind.NOTICE
    assert isinstance(decoded.payload, NoticeEvent)
    assert decoded.payload.notice.presence_id == "p4"
    assert decoded.payload.notice.title == "Unexpected person"


def test_notice_payload_key_is_notice():
    """The wire key is `notice`, matching the per-kind naming the app mirrors."""
    env = envelope(seq=7, payload=NoticeEvent(notice=a_notice()))
    assert env.model_dump(mode="json")["payload"]["notice"]["notice_id"] == "ntc-p4"


def test_a_notice_cannot_be_built_without_provenance():
    """The honesty rule is structural, not conventional.

    A notice with no stated origin is exactly the thing a compromised agent
    would emit, so the model refuses to construct one at all.
    """
    with pytest.raises(ValidationError):
        Notice(
            notice_id="ntc-p4",
            severity=NoticeSeverity.ATTENTION,
            title="Unexpected person",
            body="Not accounted for. Living room.",
        )
