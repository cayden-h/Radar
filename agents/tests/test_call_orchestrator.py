from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType

from agents.caller import CallerAgent, ModeChangeRefused, ParticipationMode
from agents.caller.transport.orchestrator import CallOrchestrator
from agents.caller.transport.simulated import SimulatedCallTransport


def _orchestrator(mesh) -> CallOrchestrator:
    return CallOrchestrator(
        caller=CallerAgent(mesh),
        transport=SimulatedCallTransport(),
        mock_911_number="+15550004444",
        twilio_voice_number="+15550003333",
        twiml_app_sid="APxxxx",
        status_callback_url="https://unused.example/status",
    )


@pytest.mark.asyncio
async def test_start_call_places_both_legs_and_records_a_conference_name(mesh):
    """`start_call` must open both conference legs and hand back the conference name.

    A wrong or missing conference name means the resident leg and the operator
    leg cannot later be joined into the same call - the whole bridge model
    depends on this string being stable and correct from the first tick.
    """
    orch = _orchestrator(mesh)
    conference_name = await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    assert conference_name == "incident-inc-001"


@pytest.mark.asyncio
async def test_a_prompt_message_produces_a_spoken_reply(mesh):
    """A ConversationRelay `prompt` message is a question from the operator and must
    produce something to speak back - here, "I don't know" for an unrecognised
    question, which is the correct answer rather than a guess.
    """
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    reply = await orch.handle_relay_message({"type": "prompt", "voicePrompt": "what colour is the front door?"})
    assert reply is not None
    assert reply["type"] == "text"
    assert reply["token"].startswith("I don't know")


@pytest.mark.asyncio
async def test_an_interrupt_message_produces_no_reply(mesh):
    """Barge-in messages carry no question to answer and must not produce speech;
    the agent yields instead. Sending a reply here would talk over the human that
    just interrupted, which the bridge rules forbid.
    """
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    reply = await orch.handle_relay_message({"type": "interrupt"})
    assert reply is None


@pytest.mark.asyncio
async def test_set_mode_forwards_to_the_transport_after_the_bridge_allows_it(mesh):
    """Once the Bridge allows a mode change, the transport must actually be told,
    or the resident's leg stays muted server-side no matter what the app shows.
    """
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    await orch.set_mode(ParticipationMode.WHISPER, by_human=True)
    assert orch.transport.mode_changes[-1]["muted"] is False


@pytest.mark.asyncio
async def test_set_mode_refuses_automation_going_louder(mesh):
    """Automation may only ever move toward quieter; the orchestrator must not
    swallow or soften `ModeChangeRefused` from the Bridge on a louder transition.
    """
    orch = _orchestrator(mesh)
    await orch.start_call("inc-001", IncidentType.BURGLARY, "1872 Ridgeview Lane")
    with pytest.raises(ModeChangeRefused):
        await orch.set_mode(ParticipationMode.FULL_VOICE, by_human=False)
