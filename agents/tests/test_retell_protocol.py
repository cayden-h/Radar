"""Retell Custom LLM WebSocket wire shape. Pure parse/build, no I/O."""

from __future__ import annotations

import pytest

from agents.caller.transport.retell.protocol import (
    RetellCallDetails,
    RetellPingPong,
    RetellResponseRequired,
    RetellUpdateOnly,
    build_config_message,
    build_pong_message,
    build_response_message,
    latest_user_utterance,
    parse_retell_message,
)


def test_parses_ping_pong():
    msg = parse_retell_message({"interaction_type": "ping_pong", "timestamp": 1234})
    assert msg == RetellPingPong(timestamp=1234)


def test_parses_call_details():
    msg = parse_retell_message({"interaction_type": "call_details", "call": {"call_id": "c1"}})
    assert isinstance(msg, RetellCallDetails)
    assert msg.call == {"call_id": "c1"}


def test_parses_update_only():
    raw = {"interaction_type": "update_only", "transcript": [{"role": "user", "content": "hi"}]}
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellUpdateOnly)
    assert msg.transcript == ({"role": "user", "content": "hi"},)


def test_parses_response_required():
    raw = {
        "interaction_type": "response_required",
        "response_id": 3,
        "transcript": [{"role": "agent", "content": "hello"}, {"role": "user", "content": "help"}],
    }
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellResponseRequired)
    assert msg.response_id == 3
    assert msg.transcript[-1] == {"role": "user", "content": "help"}


def test_reminder_required_is_a_response_required():
    raw = {"interaction_type": "reminder_required", "response_id": 5, "transcript": []}
    msg = parse_retell_message(raw)
    assert isinstance(msg, RetellResponseRequired)
    assert msg.response_id == 5


def test_unknown_interaction_type_raises():
    with pytest.raises(ValueError):
        parse_retell_message({"interaction_type": "nonsense"})


def test_build_config_message_shape():
    cfg = build_config_message()
    assert cfg["response_type"] == "config"
    assert "config" in cfg


def test_build_response_message_defaults_complete():
    msg = build_response_message(7, "units are two minutes out")
    assert msg == {
        "response_type": "response",
        "response_id": 7,
        "content": "units are two minutes out",
        "content_complete": True,
        "end_call": False,
    }


def test_build_pong_echoes_timestamp():
    assert build_pong_message(99) == {"response_type": "ping_pong", "timestamp": 99}


def test_latest_user_utterance_picks_last_user_line():
    transcript = [
        {"role": "user", "content": "first"},
        {"role": "agent", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    assert latest_user_utterance(transcript) == "second"


def test_latest_user_utterance_none_when_no_user():
    assert latest_user_utterance([{"role": "agent", "content": "only me"}]) is None
    assert latest_user_utterance([]) is None
