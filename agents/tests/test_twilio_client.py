from __future__ import annotations

import httpx
import pytest

from agents.caller.transport.twilio_client import RealTwilioVoiceClient

ACCOUNT_SID = "ACxxxx"


def _client(handler) -> RealTwilioVoiceClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return RealTwilioVoiceClient(account_sid=ACCOUNT_SID, auth_token="tok", client=http_client)


@pytest.mark.asyncio
async def test_create_conference_call_posts_the_expected_form():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json={"sid": "CA0001"})

    client = _client(handler)
    sid = await client.create_conference_call(
        to="+15550004444",
        from_="+15550003333",
        conference_name="incident-inc-001",
        status_callback_url="https://example.ngrok-free.app/twilio/status",
    )
    assert sid == "CA0001"
    assert len(captured) == 1
    body = captured[0].read().decode()
    assert "To=%2B15550004444" in body
    assert "incident-inc-001" in body  # inside the TwiML in the request
    await client.aclose()


@pytest.mark.asyncio
async def test_add_conference_participant_targets_the_twiml_app():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "app%3AAPxxxx" in body or "app:APxxxx" in body
        return httpx.Response(201, json={"sid": "CA0002"})

    client = _client(handler)
    sid = await client.add_conference_participant(
        conference_name="incident-inc-001",
        twiml_app_sid="APxxxx",
        from_="+15550003333",
        status_callback_url="https://example.ngrok-free.app/twilio/status",
    )
    assert sid == "CA0002"
    await client.aclose()


@pytest.mark.asyncio
async def test_a_twilio_error_response_raises_rather_than_returning_a_fake_sid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "invalid number"})

    client = _client(handler)
    with pytest.raises(RuntimeError, match="Twilio refused"):
        await client.create_conference_call(
            to="+1bad",
            from_="+15550003333",
            conference_name="incident-inc-001",
            status_callback_url="https://example.ngrok-free.app/twilio/status",
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_set_participant_mode_sends_muted_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "Muted=true" in body
        return httpx.Response(200, json={})

    client = _client(handler)
    await client.set_participant_mode(conference_name="incident-inc-001", call_sid="CA0003", muted=True)
    await client.aclose()
