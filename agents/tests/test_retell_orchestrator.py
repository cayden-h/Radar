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
async def test_opening_text_uses_fixed_radar_script(mesh):
    orch, _ = _orchestrator(mesh)
    await orch.start_call("i1", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    text = orch._opening_text()
    assert text.startswith("This is Radar's agent, and there is an incident in progress")
    assert "1872 Ridgeview Lane" in text


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


class _FakeSink:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str]] = []

    async def line(self, incident_id: str, speaker: str, text: str) -> None:
        self.lines.append((incident_id, speaker, text))


@pytest.mark.asyncio
async def test_queued_resident_note_spoken_attributed_next_turn(mesh):
    orch, _ = _orchestrator(mesh)
    orch.incident_id = "inc-1"
    orch.enqueue_resident_note("he has a knife")
    reply = await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 1,
            "transcript": [{"role": "user", "content": "what's happening?"}],
        }
    )
    assert "The resident reports: he has a knife" in reply["content"]
    assert orch._context_resident_notes == ["he has a knife"]


@pytest.mark.asyncio
async def test_orchestrator_pushes_each_line_to_sink(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    transport = SimulatedRetellVoiceClient()
    sink = _FakeSink()
    orch = RetellCallOrchestrator(
        caller,
        transport,
        from_number="+15550001111",
        operator_number="+15550009999",
        transcript_sink=sink,
    )
    orch.incident_id = "inc-1"
    orch._incident_type = IncidentType.BURGLARY
    orch._address_spoken = "12 Elm Street"
    # Opening turn (no prior user utterance) -> one caller line.
    await orch.handle_ws_message(
        {"interaction_type": "response_required", "response_id": 0, "transcript": []}
    )
    assert sink.lines == [("inc-1", "caller", orch.transcript[-1][1])]


@pytest.mark.asyncio
async def test_orchestrator_pushes_operator_and_reply_lines_to_sink(mesh):
    caller = CallerAgent(mesh, MasterAgent(mesh))
    transport = SimulatedRetellVoiceClient()
    sink = _FakeSink()
    orch = RetellCallOrchestrator(
        caller,
        transport,
        from_number="+15550001111",
        operator_number="+15550009999",
        transcript_sink=sink,
    )
    await orch.start_call("i1", IncidentType.BURGLARY, "12 Elm Street")
    sink.lines.clear()
    await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 2,
            "transcript": [
                {"role": "agent", "content": "opening"},
                {"role": "user", "content": "what colour is the front door?"},
            ],
        }
    )
    assert sink.lines == [
        ("i1", "operator", "what colour is the front door?"),
        ("i1", "caller", orch.transcript[-1][1]),
    ]


@pytest.mark.asyncio
async def test_context_so_far_includes_transcript_and_notes(mesh):
    orch, _ = _orchestrator(mesh)
    orch.incident_id = "inc-1"
    orch.enqueue_resident_note("child asthmatic")
    await orch.handle_ws_message(
        {
            "interaction_type": "response_required",
            "response_id": 1,
            "transcript": [{"role": "user", "content": "anything else?"}],
        }
    )
    ctx = orch.context_so_far()
    assert "child asthmatic" in ctx["resident_notes"]
    assert any(t == "caller" for t, _ in ctx["transcript"])
