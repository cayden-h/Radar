"""RetellCallOrchestrator: adapts Retell's WS onto CallerAgent, no new speech."""

from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent
from agents.caller.transport.retell.client import SimulatedRetellVoiceClient
from agents.caller.transport.retell.orchestrator import RetellCallOrchestrator
from agents.master import MasterAgent


def _orchestrator(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    transport = SimulatedRetellVoiceClient()
    orch = RetellCallOrchestrator(
        caller, transport, from_number="+15550001111", operator_number="+15550009999"
    )
    return orch, transport


@pytest.mark.asyncio
async def test_start_call_dials_the_operator_number_from_settings(mesh):
    orch, transport = _orchestrator(mesh)
    call_id = await orch.start_call("incident-7", IncidentType.BURGLARY, "12 Elm Street")
    assert call_id.startswith("SIM-RETELL-")
    assert transport.calls[0]["to_number"] == "+15550009999"
    assert transport.calls[0]["from_number"] == "+15550001111"
    assert transport.calls[0]["metadata"]["incident_id"] == "incident-7"
    assert orch.call_id == call_id


@pytest.mark.asyncio
async def test_ping_pong_is_echoed(mesh):
    orch, _ = _orchestrator(mesh)
    reply = await orch.handle_ws_message({"interaction_type": "ping_pong", "timestamp": 42})
    assert reply == {"response_type": "ping_pong", "timestamp": 42}


@pytest.mark.asyncio
async def test_update_only_and_call_details_do_not_speak(mesh):
    orch, _ = _orchestrator(mesh)
    assert await orch.handle_ws_message({"interaction_type": "call_details", "call": {}}) is None
    assert await orch.handle_ws_message(
        {"interaction_type": "update_only", "transcript": [{"role": "user", "content": "hi"}]}
    ) is None


@pytest.mark.asyncio
async def test_first_response_required_delivers_opening_report(mesh):
    orch, _ = _orchestrator(mesh)
    await orch.start_call("i1", IncidentType.BURGLARY, "12 Elm Street")
    reply = await orch.handle_ws_message(
        {"interaction_type": "response_required", "response_id": 0, "transcript": []}
    )
    assert reply["response_type"] == "response"
    assert reply["response_id"] == 0
    assert reply["content_complete"] is True
    # The opening report identifies itself as not a person.
    assert "not a person" in reply["content"]


@pytest.mark.asyncio
async def test_later_response_required_answers_the_operator(mesh):
    orch, _ = _orchestrator(mesh)
    await orch.start_call("i1", IncidentType.BURGLARY, "12 Elm Street")
    reply = await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 2,
            "transcript": [
                {"role": "agent", "content": "opening"},
                {"role": "user", "content": "what colour is the front door?"},
            ],
        }
    )
    assert reply["response_id"] == 2
    # An unrecognised question is "I don't know", never a guess to 911.
    assert reply["content"].startswith("I don't know")
    assert ("operator", "what colour is the front door?") in orch.transcript_so_far()
