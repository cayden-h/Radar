"""agents/agents/caller/transport/retell/orchestrator.py

The seam between CallerAgent's transport-agnostic decision logic and whichever
RetellVoiceClient is behind it (real or simulated). Nothing here composes
speech: it only routes Retell's WebSocket messages onto opening_report and
answer_operator, which already enforce the verified-claims rule.

Retell places a 1:1 call to the operator, not a Twilio-style conference, so
there is no resident leg to mute here. The resident whisper/silent path remains
the Twilio conference's; see the design doc's divergence note.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hawkeye_backend.models.incident import IncidentType

from ...agent import CallerAgent
from .client import RetellVoiceClient
from .protocol import (
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


@dataclass
class RetellCallOrchestrator:
    caller: CallerAgent
    transport: RetellVoiceClient
    from_number: str
    operator_number: str
    call_id: str | None = field(default=None, init=False)
    incident_id: str | None = field(default=None, init=False)
    transcript: list[tuple[str, str]] = field(default_factory=list, init=False)

    async def start_call(
        self, incident_id: str, incident_type: IncidentType, address_spoken: str
    ) -> str:
        self.incident_id = incident_id
        # The destination is the operator number from settings, never request
        # input. The opening report is delivered on the first response_required,
        # not here, because Retell drives turn-taking once the WS opens.
        self.call_id = await self.transport.create_phone_call(
            from_number=self.from_number,
            to_number=self.operator_number,
            metadata={"incident_id": incident_id, "incident_type": incident_type.value},
        )
        self._incident_type = incident_type
        self._address_spoken = address_spoken
        return self.call_id

    def config_message(self) -> dict:
        return build_config_message()

    async def handle_ws_message(self, raw: dict) -> dict | None:
        message = parse_retell_message(raw)
        if isinstance(message, RetellPingPong):
            return build_pong_message(message.timestamp)
        if isinstance(message, (RetellCallDetails, RetellUpdateOnly)):
            return None
        if isinstance(message, RetellResponseRequired):
            operator_line = latest_user_utterance(message.transcript)
            if operator_line is None:
                text = self._opening_text()
                self.transcript.append(("caller", text))
                return build_response_message(message.response_id, text)
            self.transcript.append(("operator", operator_line))
            reply = self.caller.answer_operator(operator_line)
            self.transcript.append(("caller", reply.text))
            return build_response_message(message.response_id, reply.text)
        return None

    def _opening_text(self) -> str:
        utterances = self.caller.opening_report(self._incident_type, self._address_spoken)
        return " ".join(u.text for u in utterances)

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
