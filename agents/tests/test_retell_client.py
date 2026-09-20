"""Retell REST client: real httpx shape and the simulated stand-in."""

from __future__ import annotations

import httpx
import pytest

from agents.caller.transport.retell.client import (
    RealRetellVoiceClient,
    SimulatedRetellVoiceClient,
)


@pytest.mark.asyncio
async def test_real_client_posts_create_phone_call_and_returns_call_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"call_id": "call_abc123"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="key_test", agent_id="agent_9", client=http)
        call_id = await client.create_phone_call(
            from_number="+15550001111", to_number="+15550002222", metadata={"incident_id": "i1"}
        )

    assert call_id == "call_abc123"
    assert seen["url"] == "https://api.retellai.com/v2/create-phone-call"
    assert seen["auth"] == "Bearer key_test"
    assert seen["body"]["from_number"] == "+15550001111"
    assert seen["body"]["to_number"] == "+15550002222"
    assert seen["body"]["metadata"] == {"incident_id": "i1"}
    assert seen["body"]["override_agent_id"] == "agent_9"


@pytest.mark.asyncio
async def test_real_client_raises_on_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="payment required")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="k", client=http)
        with pytest.raises(RuntimeError):
            await client.create_phone_call(from_number="+1", to_number="+2", metadata={})


@pytest.mark.asyncio
async def test_real_client_omits_agent_id_when_blank():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"call_id": "c"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RealRetellVoiceClient(api_key="k", client=http)
        await client.create_phone_call(from_number="+1", to_number="+2", metadata={})

    assert "override_agent_id" not in seen["body"]


@pytest.mark.asyncio
async def test_simulated_client_returns_incrementing_ids_and_records():
    client = SimulatedRetellVoiceClient()
    first = await client.create_phone_call(from_number="+1", to_number="+2", metadata={"incident_id": "i"})
    second = await client.create_phone_call(from_number="+1", to_number="+3", metadata={})
    assert first == "SIM-RETELL-0001"
    assert second == "SIM-RETELL-0002"
    assert client.calls[0]["to_number"] == "+2"
    assert client.calls[1]["to_number"] == "+3"
