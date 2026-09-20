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
from enum import Enum

from hawkeye_backend.models.incident import IncidentType

from ...agent import OPERATOR_CUES, CallerAgent
from .client import RetellVoiceClient
from .courier_client import BackendCourierClient, find_email
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
from .transcript_sink import TranscriptSink

#: Cue intents that mark the operator winding the call down. When one of these
#: trips, the caller asks for the department email before the line closes.
#:
#: These names are the source of truth in `agents/caller/agent.py`'s
#: `OPERATOR_CUES` - `dispatched` ("units are rolling", "help is coming") and
#: `eta` ("two minutes out", "almost there"). We match on the same phrase lists
#: rather than a parallel keyword set, so the two stay in step: the moment the
#: operator commits a response is the moment to capture where to mail the record.
_CLOSING_CUE_INTENTS = frozenset({"dispatched", "eta"})


def _trips_closing_cue(operator_line: str) -> bool:
    """Whether the operator line reads as a dispatch/ETA close.

    Reuses `OPERATOR_CUES` from `agent.py` (the source of truth for cue
    phrasing) rather than duplicating its keyword lists, mirroring the
    meaning-not-strings matching in `CallerAgent.operator_said`.
    """
    lowered = operator_line.lower()
    for intent, phrases in OPERATOR_CUES:
        if intent in _CLOSING_CUE_INTENTS and any(p in lowered for p in phrases):
            return True
    return False


class _EmailCapture(Enum):
    """Where the email-capture flow is on this call.

    NORMAL until a closing cue trips, ASKED_EMAIL once the caller has asked for
    the department address, CONFIRMED once an address has been read back and
    handed to the courier. It only ever moves forward, so the caller cannot be
    talked into re-asking or re-sending, and every non-email turn in
    ASKED_EMAIL falls through to the normal verified-answer path.
    """

    NORMAL = "normal"
    ASKED_EMAIL = "asked_email"
    CONFIRMED = "confirmed"


@dataclass
class RetellCallOrchestrator:
    caller: CallerAgent
    transport: RetellVoiceClient
    from_number: str
    operator_number: str
    #: How the sealed record reaches the responding department. Optional so the
    #: orchestrator runs unchanged where no courier is wired (the pre-pivot
    #: tests, a transport-only harness); the email is simply not captured then.
    #: The integrator constructs this with a base_url at caller startup - e.g.
    #: `HttpBackendCourierClient(base_url)` - and injects it here.
    courier: BackendCourierClient | None = None
    #: Best-effort fan-out of each transcript line to the hub, so the resident's
    #: app can render the live operator <-> agent conversation. Optional for the
    #: same reason `courier` is: the orchestrator runs unchanged where nothing
    #: is wired to receive lines, and never raises into the call loop when it is.
    transcript_sink: TranscriptSink | None = None
    call_id: str | None = field(default=None, init=False)
    incident_id: str | None = field(default=None, init=False)
    transcript: list[tuple[str, str]] = field(default_factory=list, init=False)
    _email_capture: _EmailCapture = field(default=_EmailCapture.NORMAL, init=False)

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
                if self.transcript_sink:
                    await self.transcript_sink.line(self.incident_id or "", "caller", text)
                return build_response_message(message.response_id, text)
            self.transcript.append(("operator", operator_line))
            if self.transcript_sink:
                await self.transcript_sink.line(self.incident_id or "", "operator", operator_line)
            text = await self._respond_to_operator(operator_line)
            self.transcript.append(("caller", text))
            if self.transcript_sink:
                await self.transcript_sink.line(self.incident_id or "", "caller", text)
            return build_response_message(message.response_id, text)
        return None

    async def _respond_to_operator(self, operator_line: str) -> str:
        """Pick the caller's reply for this operator turn.

        The email-capture flow is *additive*: it only ever front-runs the normal
        `answer_operator` reply when the operator is closing the call or has just
        read an address aloud, and it never widens what claims the agent will
        speak. An email is a destination, never authorization - the same rule the
        courier records with `operator_supplied` provenance and never treats as a
        grant. Everything outside those two moments still routes through the
        verified-claims path unchanged.
        """
        if self._email_capture is _EmailCapture.ASKED_EMAIL:
            email = find_email(operator_line)
            if email is not None:
                if self.courier is not None:
                    # Best-effort by contract: the client fails soft, so this
                    # never raises into the call loop, and the backend chain -
                    # not this call - is the record of the send's real outcome.
                    await self.courier.deliver(self.incident_id or "", email)
                self._email_capture = _EmailCapture.CONFIRMED
                # Read back verbatim so the operator can catch a mishearing.
                return f"Thank you - I'll send the record to {email}."
            # No address in that line. Fall back to the normal verified answer
            # and stay in ASKED_EMAIL so the operator can repeat it.
            return self.caller.answer_operator(operator_line).text

        if self._email_capture is _EmailCapture.NORMAL and _trips_closing_cue(operator_line):
            # The operator is winding the call down. Ask where to mail the sealed
            # record before the line closes; the address is only knowable now,
            # once a department has committed a response.
            self._email_capture = _EmailCapture.ASKED_EMAIL
            return (
                "Before you go - what email address should I send the sealed "
                "incident record to?"
            )

        return self.caller.answer_operator(operator_line).text

    def _opening_text(self) -> str:
        utterances = self.caller.opening_report(self._incident_type, self._address_spoken)
        tail = " ".join(u.text for u in utterances)
        return (
            f"This is Radar's agent, and there is an incident in progress at "
            f"{self._address_spoken}. {tail}"
        )

    def transcript_so_far(self) -> list[tuple[str, str]]:
        return list(self.transcript)
