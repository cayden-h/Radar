"""agents/agents/caller/transport/simulated.py

No network, no Twilio account, no ElevenLabs account. Drives the exact same
orchestrator code path as RealTwilioVoiceClient (Task 7) so the demo's
fallback and everyday development exercise real Bridge/CallerAgent logic,
never a UI-only stub.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

_SCRIPT: tuple[tuple[str, str], ...] = (
    ("operator", "911, what's your emergency?"),
    ("caller", "A person entered through the back door and does not match anyone on the household roster."),
    ("operator", "Can you describe them?"),
    ("caller", "Dark jacket, medium build, currently in the living room, captured 4 seconds ago."),
    ("operator", "Units are on the way, two minutes out."),
)


class SimulatedCallTransport:
    def __init__(self) -> None:
        self._call_counter = 0
        self.mode_changes: list[dict] = []
        self.ended_conferences: list[str] = []

    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str:
        self._call_counter += 1
        return f"SIM-CA{self._call_counter:04d}"

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str:
        self._call_counter += 1
        return f"SIM-CA{self._call_counter:04d}"

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None:
        self.mode_changes.append({"call_sid": call_sid, "muted": muted, "coaching": coaching})

    async def end_conference(self, *, conference_name: str) -> None:
        self.ended_conferences.append(conference_name)

    async def scripted_turns(self) -> AsyncIterator[tuple[str, str]]:
        for speaker, text in _SCRIPT:
            await asyncio.sleep(0)  # cooperative yield; real timing lives in the orchestrator
            yield speaker, text

    async def aclose(self) -> None:
        return None
