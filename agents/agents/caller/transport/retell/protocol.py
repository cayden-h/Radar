"""agents/agents/caller/transport/retell/protocol.py

Wire-shape for Retell's Custom LLM WebSocket protocol. Field names verified
against Retell's llm-websocket docs at implementation time. Pure parse/build,
no I/O, so it is unit-testable without a socket - the same split as the Twilio
transport's models.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetellPingPong:
    timestamp: int


@dataclass(frozen=True)
class RetellCallDetails:
    call: dict


@dataclass(frozen=True)
class RetellUpdateOnly:
    transcript: tuple[dict, ...]


@dataclass(frozen=True)
class RetellResponseRequired:
    """Retell is asking the agent to speak. Covers both `response_required` and
    `reminder_required` - a reminder is the same request after a silence, and
    the agent answers it the same way."""

    response_id: int
    transcript: tuple[dict, ...]


RetellInbound = RetellPingPong | RetellCallDetails | RetellUpdateOnly | RetellResponseRequired


def parse_retell_message(raw: dict) -> RetellInbound:
    kind = raw.get("interaction_type")
    if kind == "ping_pong":
        return RetellPingPong(timestamp=int(raw["timestamp"]))
    if kind == "call_details":
        return RetellCallDetails(call=raw.get("call", {}))
    if kind == "update_only":
        return RetellUpdateOnly(transcript=tuple(raw.get("transcript", [])))
    if kind in ("response_required", "reminder_required"):
        return RetellResponseRequired(
            response_id=int(raw["response_id"]),
            transcript=tuple(raw.get("transcript", [])),
        )
    raise ValueError(f"unknown Retell interaction_type: {kind!r}")


def build_config_message() -> dict:
    """Sent once, when the socket opens. Ask Retell to send call_details so we
    can bind the transcript, and to auto-reconnect with ping_pong keepalives."""
    return {
        "response_type": "config",
        "config": {"auto_reconnect": True, "call_details": True},
    }


def build_response_message(
    response_id: int, content: str, *, content_complete: bool = True, end_call: bool = False
) -> dict:
    return {
        "response_type": "response",
        "response_id": response_id,
        "content": content,
        "content_complete": content_complete,
        "end_call": end_call,
    }


def build_pong_message(timestamp: int) -> dict:
    return {"response_type": "ping_pong", "timestamp": timestamp}


def latest_user_utterance(transcript: tuple[dict, ...] | list[dict]) -> str | None:
    """The operator's most recent line, or None if they have not spoken yet.

    Retell's transcript uses role `user` for the far end (the operator) and
    `agent` for us. The opening report is what we say when this is None.
    """
    for item in reversed(list(transcript)):
        if item.get("role") == "user":
            return item.get("content")
    return None
