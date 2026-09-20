from __future__ import annotations

from agents.caller.transport.twiml import connect_relay_twiml, dial_conference_twiml


def test_dial_conference_twiml_names_the_conference():
    xml = dial_conference_twiml("incident-inc-001")
    assert "<Conference>incident-inc-001</Conference>" in xml
    assert xml.startswith("<?xml")


def test_connect_relay_twiml_carries_the_websocket_url_and_voice():
    xml = connect_relay_twiml("wss://example.ngrok-free.app/twilio/conversation-relay", "voice123")
    assert 'url="wss://example.ngrok-free.app/twilio/conversation-relay"' in xml
    assert 'ttsProvider="ElevenLabs"' in xml
    assert 'voice="voice123"' in xml


def test_connect_relay_twiml_never_embeds_the_mock_911_number():
    """The destination is bound in config, never in a TwiML string this
    endpoint could be tricked into building differently."""
    xml = connect_relay_twiml("wss://example.ngrok-free.app/twilio/conversation-relay", "voice123")
    assert "+1555" not in xml
