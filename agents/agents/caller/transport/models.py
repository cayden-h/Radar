"""agents/agents/caller/transport/models.py

Wire-shape for Twilio's ConversationRelay WebSocket protocol. Field names
verified against Twilio's WebSocket-messages reference at implementation
time (docs/superpowers/plans/2026-09-20-twilio-call-bridge.md Task 2 has the
verification note) rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelaySetupMessage:
    call_sid: str
    from_number: str


@dataclass(frozen=True)
class RelayPromptMessage:
    text: str


@dataclass(frozen=True)
class RelayInterruptMessage:
    pass


def parse_relay_message(raw: dict) -> RelaySetupMessage | RelayPromptMessage | RelayInterruptMessage:
    kind = raw.get("type")
    if kind == "setup":
        return RelaySetupMessage(call_sid=raw["callSid"], from_number=raw.get("from", ""))
    if kind == "prompt":
        return RelayPromptMessage(text=raw["voicePrompt"])
    if kind == "interrupt":
        return RelayInterruptMessage()
    raise ValueError(f"unknown ConversationRelay message type: {kind!r}")


def build_text_message(text: str) -> dict:
    return {"type": "text", "token": text, "last": True}
