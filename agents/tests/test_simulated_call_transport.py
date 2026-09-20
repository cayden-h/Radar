from __future__ import annotations

import pytest

from agents.caller.transport.simulated import SimulatedCallTransport


@pytest.mark.asyncio
async def test_create_conference_call_returns_a_fake_sid_with_no_network():
    """No Twilio account, no network. The fallback still returns something call-shaped."""
    transport = SimulatedCallTransport()
    sid = await transport.create_conference_call(
        to="+15550004444",
        from_="+15550003333",
        conference_name="incident-inc-001",
        status_callback_url="https://unused.example/status",
    )
    assert sid.startswith("SIM-CA")


@pytest.mark.asyncio
async def test_set_participant_mode_is_recorded_not_sent_anywhere():
    """No REST call exists to send this to; it is recorded so a test can assert on it."""
    transport = SimulatedCallTransport()
    await transport.set_participant_mode(conference_name="inc-1", call_sid="SIM-CA1", muted=True)
    assert transport.mode_changes[-1] == {"call_sid": "SIM-CA1", "muted": True, "coaching": False}


@pytest.mark.asyncio
async def test_scripted_turns_yields_operator_and_caller_lines_in_order():
    """The orchestrator needs a deterministic script to turn into TranscriptLines."""
    transport = SimulatedCallTransport()
    turns = [turn async for turn in transport.scripted_turns()]
    assert turns[0][0] == "operator"
    assert any(speaker == "caller" for speaker, _ in turns)
    assert len(turns) >= 4
