"""agents/agents/caller/transport/orchestrator.py

The seam between Bridge/CallerAgent's pure decision logic and whichever
TwilioVoiceClient is behind it (real or SimulatedCallTransport). Nothing in
here knows or cares which one it has.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hawkeye_backend.models.incident import IncidentType

from ..agent import CallerAgent
from ..bridge import Leg, ParticipationMode
from .models import RelayInterruptMessage, RelayPromptMessage, RelaySetupMessage, build_text_message, parse_relay_message
from .twilio_client import TwilioVoiceClient


@dataclass
class CallOrchestrator:
    caller: CallerAgent
    transport: TwilioVoiceClient
    mock_911_number: str
    twilio_voice_number: str
    twiml_app_sid: str
    status_callback_url: str
    conference_name: str | None = field(default=None, init=False)
    resident_call_sid: str | None = field(default=None, init=False)
    transcript: list[tuple[str, str]] = field(default_factory=list, init=False)

    async def start_call(self, incident_id: str, incident_type: IncidentType, address_spoken: str) -> str:
        self.conference_name = f"incident-{incident_id}"
        await self.transport.create_conference_call(
            to=self.mock_911_number,
            from_=self.twilio_voice_number,
            conference_name=self.conference_name,
            status_callback_url=self.status_callback_url,
        )
        await self.transport.add_conference_participant(
            conference_name=self.conference_name,
            twiml_app_sid=self.twiml_app_sid,
            from_=self.twilio_voice_number,
            status_callback_url=self.status_callback_url,
        )
        for utterance in self.caller.opening_report(incident_type, address_spoken):
            self.transcript.append(("caller", utterance.text))
        return self.conference_name

    async def handle_relay_message(self, raw: dict) -> dict | None:
        message = parse_relay_message(raw)
        if isinstance(message, RelaySetupMessage):
            return None
        if isinstance(message, RelayInterruptMessage):
            self.caller.bridge.yield_to_human()
            return None
        if isinstance(message, RelayPromptMessage):
            self.transcript.append(("operator", message.text))
            reply = self.caller.answer_operator(message.text)
            self.transcript.append(("caller", reply.text))
            return build_text_message(reply.text)
        return None

    async def set_mode(self, mode: ParticipationMode, *, by_human: bool) -> str:
        announcement = self.caller.bridge.set_mode(mode, by_human=by_human)
        if self.conference_name is not None:
            # The resident's leg may not have a Twilio call_sid yet - per
            # `agents/CLAUDE.md` the resident is added on demand, never by
            # default, and their leg is a WebRTC connection to our own bridge
            # rather than a conference participant from the start. The mode
            # flip must still be forwarded to the transport the instant the
            # Bridge allows it, so silence is enforced there rather than
            # missed because nobody had joined yet.
            state = self.caller.bridge.leg_state(Leg.RESIDENT)
            await self.transport.set_participant_mode(
                conference_name=self.conference_name,
                call_sid=self.resident_call_sid or "",
                muted=not state.send,
            )
        return announcement

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
