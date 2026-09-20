"""agents/agents/caller/transport/twiml.py

Builds the TwiML this feature returns from its Twilio webhooks. Deliberately
takes no phone number as an argument anywhere in this module: the mock 911
destination is bound once in Settings and dialed by the orchestrator via the
REST Add Participant call, never interpolated into a TwiML string a webhook
builds per-request.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

_XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def dial_conference_twiml(conference_name: str) -> str:
    safe_name = escape(conference_name)
    return f"{_XML_HEADER}<Response><Dial><Conference>{safe_name}</Conference></Dial></Response>"


def connect_relay_twiml(websocket_url: str, voice_id: str, welcome_greeting: str | None = None) -> str:
    safe_url = escape(websocket_url)
    safe_voice = escape(voice_id)
    greeting_attr = f' welcomeGreeting="{escape(welcome_greeting)}"' if welcome_greeting else ""
    return (
        f"{_XML_HEADER}<Response><Connect>"
        f'<ConversationRelay url="{safe_url}" ttsProvider="ElevenLabs" voice="{safe_voice}"{greeting_attr}/>'
        "</Connect></Response>"
    )
