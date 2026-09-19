"""Sink fan-out, failure isolation, and the Twilio request shape.

No test here sends a real message.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import NoticeEvent
from hawkeye_backend.models.notice import Notice, NoticeSeverity
from hawkeye_backend.notices.sinks import StreamSink, TwilioSink, deliver

pytestmark = pytest.mark.asyncio


def a_notice(**overrides) -> Notice:
    base = dict(
        notice_id="ntc-p4",
        severity=NoticeSeverity.ATTENTION,
        title="Unexpected person",
        body="Not accounted for. Living room.",
        zone="living_room",
        room="Living room",
        presence_id="p4",
        raised_at=datetime(2026, 9, 20, 1, 4, tzinfo=UTC),
        provenance=Provenance(source=Source.AGENT_INFERENCE, producer="agents/intruder"),
    )
    base.update(overrides)
    return Notice(**base)


class Recorder:
    """A sink that remembers what it was handed."""

    def __init__(self) -> None:
        self.seen: list[Notice] = []

    async def deliver(self, notice: Notice) -> None:
        self.seen.append(notice)


class Exploding:
    """A sink that always fails, standing in for Twilio refusing a trial send."""

    async def deliver(self, notice: Notice) -> None:
        raise RuntimeError("A2P 10DLC registration required")


async def test_every_sink_receives_the_notice():
    a, b = Recorder(), Recorder()

    await deliver(a_notice(), [a, b])

    assert len(a.seen) == 1
    assert len(b.seen) == 1


async def test_a_failing_sink_does_not_stop_the_others():
    """A Twilio failure must not take down the in-app banner. This is the
    mitigation the spec relies on for demo day."""
    good = Recorder()

    await deliver(a_notice(), [Exploding(), good])

    assert len(good.seen) == 1


async def test_the_stream_sink_emits_a_notice_event():
    """The in-app banner's whole path starts here, so it gets a real test.

    Task 5 wires this into the runtime's one emit path and Task 9 draws the
    banner off it.
    """
    emitted: list[NoticeEvent] = []

    async def emit(event: NoticeEvent) -> None:
        emitted.append(event)

    notice = a_notice()
    await StreamSink(emit).deliver(notice)

    assert len(emitted) == 1
    assert isinstance(emitted[0], NoticeEvent)
    assert emitted[0].notice is notice


def stub_twilio(captured: list[httpx.Request], status: int = 201) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json={"sid": "SM0000"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def a_sink(captured: list[httpx.Request], status: int = 201, **overrides) -> TwilioSink:
    """Each test gets a fresh sink, so the default 60s `min_interval_s` never
    engages unless a test overrides it - the sink has never sent before, so
    `_last_at` is `None` and the interval check does not fire on the first
    call. That is why `test_the_rate_limit_caps_a_rehearsal_loop` has to pass
    `min_interval_s=0.0` explicitly: it sends more than once per sink and would
    otherwise be capped by the interval rather than by the count it is testing.

    `overrides` is applied after `base` is built, including `client`, so a
    test that wants to inject its own client (rather than one built from
    `status`) can pass one and only one client is ever constructed.
    """
    base = dict(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured, status),
    )
    base.update(overrides)
    return TwilioSink(**base)


async def test_twilio_posts_the_expected_form():
    captured: list[httpx.Request] = []

    await a_sink(captured).deliver(a_notice())

    assert len(captured) == 1
    req = captured[0]
    assert req.url.path == "/2010-04-01/Accounts/ACfake/Messages.json"
    assert req.method == "POST"
    assert "Authorization" in req.headers
    body = req.content.decode()
    assert "From=%2B15550001111" in body
    assert "To=%2B15550002222" in body


async def test_the_sms_names_the_room_and_the_local_time():
    """01:04 UTC is 21:04 the previous evening in Blacksburg."""
    captured: list[httpx.Request] = []

    await a_sink(captured).deliver(a_notice())

    body = httpx.QueryParams(captured[0].content.decode())["Body"]
    assert body == (
        "Hawk Eye: unexpected person in the living room, 21:04.\nNot accounted for."
    )


async def test_the_sms_never_contains_the_street_address():
    """The dispatch address is bound at registration and does not travel."""
    captured: list[httpx.Request] = []

    await a_sink(captured).deliver(a_notice())

    body = httpx.QueryParams(captured[0].content.decode())["Body"]
    assert "Ridgeview" not in body
    assert "Blacksburg" not in body


async def test_the_rate_limit_caps_a_rehearsal_loop():
    """A bug in the trigger must not be able to burn the trial credit."""
    captured: list[httpx.Request] = []
    sink = a_sink(captured, min_interval_s=0.0, max_per_instance=3)

    for i in range(10):
        await sink.deliver(a_notice(notice_id=f"ntc-{i}"))

    assert len(captured) == 3


async def test_a_twilio_error_response_is_logged_not_raised():
    """Delivery failures are logged, never raised. The stream sink runs on."""
    captured: list[httpx.Request] = []

    await a_sink(captured, status=400).deliver(a_notice())  # must not raise


async def test_an_injected_client_is_not_closed_by_the_sink():
    """A caller that supplies a client owns its lifetime.

    Task 5 constructs this sink at app startup. If the sink closed a client it
    was handed, it would close it out from under everything else using it.
    """
    captured: list[httpx.Request] = []
    client = stub_twilio(captured)
    sink = a_sink(captured, client=client)

    await sink.aclose()

    assert not client.is_closed
