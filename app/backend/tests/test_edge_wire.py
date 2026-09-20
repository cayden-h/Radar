"""The Pi-to-Mac wire types.

These are the only shapes that cross an untrusted LAN into this process, so
they are strict: extra members are a parse failure rather than a field somebody
later reads. Same rule the claim envelope lives by.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeError,
    EdgeFrameHeader,
    EdgeGrant,
    EdgeHello,
    decode_edge_message,
)
from hawkeye_backend.models.common import Source, utc_now


def test_hello_carries_the_source_the_pi_claims():
    hello = EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC)
    assert hello.kind == "hello"
    assert hello.source is Source.CAMERA_UVC


def test_frame_header_round_trips():
    at = utc_now()
    header = EdgeFrameHeader(index=7, captured_at=at, bytes=1234)
    decoded = decode_edge_message(header.model_dump_json())
    assert isinstance(decoded, EdgeFrameHeader)
    assert decoded.index == 7
    assert decoded.bytes == 1234


def test_decode_dispatches_on_kind():
    hello = EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC)
    assert isinstance(decode_edge_message(hello.model_dump_json()), EdgeHello)

    err = EdgeError(code="camera_lost", message="device went away")
    assert isinstance(decode_edge_message(err.model_dump_json()), EdgeError)


def test_an_unknown_kind_is_refused_not_guessed():
    with pytest.raises(ValidationError):
        decode_edge_message('{"kind": "something_else"}')


def test_smuggled_members_are_a_parse_failure():
    """Same rule as the claim envelope: extra="forbid", not charitable reading."""
    with pytest.raises(ValidationError):
        decode_edge_message(
            '{"kind": "hello", "edge_id": "pi-01", "source": "camera-uvc", "admin": true}'
        )


def test_a_frame_header_claiming_zero_bytes_is_refused():
    """A header promising no payload has no honest meaning and would desync the
    pairing between header and binary message."""
    with pytest.raises(ValidationError):
        EdgeFrameHeader(index=1, captured_at=utc_now(), bytes=0)


def test_grant_carries_the_signed_string_opaquely():
    """The bytes that were signed must be the bytes that are verified, so the
    grant crosses as an opaque string and is never re-serialized on the way."""
    grant = EdgeGrant(grant_json='{"nonce":"chal-1"}', request_id="req-1")
    assert grant.grant_json == '{"nonce":"chal-1"}'


def test_attestation_carries_the_request_it_answers():
    att = EdgeAttestation(
        request_id="req-1", attestation_json='{"position":"open"}', refused=False
    )
    assert att.request_id == "req-1"
    assert att.refused is False
