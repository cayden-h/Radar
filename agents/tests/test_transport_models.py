from __future__ import annotations

import pytest

from agents.caller.transport.models import (
    RelayInterruptMessage,
    RelayPromptMessage,
    RelaySetupMessage,
    build_text_message,
    parse_relay_message,
)


def test_setup_message_carries_the_call_sid():
    """The first frame on the socket identifies which call this is, so a
    reconnect or a second incident's socket is never confused with this one."""
    msg = parse_relay_message({"type": "setup", "callSid": "CAxxxx", "from": "+15550002222"})
    assert isinstance(msg, RelaySetupMessage)
    assert msg.call_sid == "CAxxxx"


def test_prompt_message_carries_the_transcribed_speech():
    msg = parse_relay_message({"type": "prompt", "voicePrompt": "what is your emergency"})
    assert isinstance(msg, RelayPromptMessage)
    assert msg.text == "what is your emergency"


def test_interrupt_message_is_recognised():
    """Barge-in: the operator or resident started talking while the agent
    was speaking. The agent must yield, never talk over a human."""
    msg = parse_relay_message({"type": "interrupt"})
    assert isinstance(msg, RelayInterruptMessage)


def test_unknown_message_type_raises_rather_than_silently_dropping():
    with pytest.raises(ValueError, match="unknown ConversationRelay message type"):
        parse_relay_message({"type": "something-new-twilio-added"})


def test_build_text_message_shape():
    assert build_text_message("units are on the way") == {
        "type": "text",
        "token": "units are on the way",
        "last": True,
    }
