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
    #: One-time token for the current call's `/twilio/conversation-relay` WS
    #: leg. Minted fresh by `transport/server.py`'s `/twilio/agent-leg` route
    #: for each call; the WS route refuses any connection that does not
    #: present it. See that module's docstring.
    relay_ws_token: str | None = field(default=None, init=False)
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
        if self.conference_name is not None and self.resident_call_sid is not None:
            # `resident_call_sid` is populated once something reports the
            # resident leg's Twilio call_sid back to this orchestrator. As of
            # this writing nothing does: the resident joins via the iOS
            # TwilioVoiceSDK Access Token flow (`CallAudioSession.swift`,
            # `LiveHawkEyeClient.swift`), which is a client-side connect that
            # never phones home with the resulting call_sid, and there is no
            # status-callback route wired for it either. That plumbing is
            # open architectural scope, tracked separately - not something
            # this guard invents.
            #
            # So this is a real conditional, not a formality: forwarding a
            # mode change with `call_sid=""` would POST an empty call_sid to
            # Twilio and get a 400 back for no benefit, since there is no
            # resident leg on the bridge yet for the mute/unmute to apply to.
            # Skip the forward until a real call_sid exists rather than
            # sending a known-bad one.
            state = self.caller.bridge.leg_state(Leg.RESIDENT)
            await self.transport.set_participant_mode(
                conference_name=self.conference_name,
                call_sid=self.resident_call_sid,
                muted=not state.send,
            )
        return announcement

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
