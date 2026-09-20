"""agents/agents/caller/transport/twilio_client.py

Raw httpx calls to Twilio's REST API, matching the style of
app/backend/hawkeye_backend/notices/sinks.py's TwilioSink: no `twilio`
package, Basic Auth tuple, own-vs-injected client tracked so aclose() only
closes what this object created.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import httpx

from .twiml import dial_conference_twiml

TWILIO_API = "https://api.twilio.com"


class TwilioVoiceClient(Protocol):
    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str: ...

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str: ...

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None: ...

    async def end_conference(self, *, conference_name: str) -> None: ...


class RealTwilioVoiceClient:
    def __init__(
        self, *, account_sid: str, auth_token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._sid = account_sid
        self._auth = (account_sid, auth_token)
        self._client = client or httpx.AsyncClient(timeout=10.0)
        # Only close what we created. A caller that injected a client owns its
        # lifetime, and closing it here would break every other user of it.
        self._owns_client = client is None

    async def _post(self, path: str, data: dict[str, str]) -> dict:
        resp = await self._client.post(
            f"{TWILIO_API}{path}", auth=self._auth, data=data
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Twilio refused {path}: {resp.status_code} {resp.text}")
        return resp.json()

    async def create_conference_call(
        self, *, to: str, from_: str, conference_name: str, status_callback_url: str
    ) -> str:
        result = await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Calls.json",
            {
                "To": to,
                "From": from_,
                "Twiml": dial_conference_twiml(conference_name),
                "StatusCallback": status_callback_url,
            },
        )
        return result["sid"]

    async def add_conference_participant(
        self, *, conference_name: str, twiml_app_sid: str, from_: str, status_callback_url: str
    ) -> str:
        result = await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}/Participants.json",
            {
                "To": f"app:{twiml_app_sid}",
                "From": from_,
                "StatusCallback": status_callback_url,
            },
        )
        return result["sid"]

    async def set_participant_mode(
        self,
        *,
        conference_name: str,
        call_sid: str,
        muted: bool,
        coaching: bool = False,
        call_sid_to_coach: str | None = None,
    ) -> None:
        data = {"Muted": "true" if muted else "false", "Coaching": "true" if coaching else "false"}
        if call_sid_to_coach:
            data["CallSidToCoach"] = call_sid_to_coach
        await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}/Participants/{call_sid}.json",
            data,
        )

    async def end_conference(self, *, conference_name: str) -> None:
        await self._post(
            f"/2010-04-01/Accounts/{self._sid}/Conferences/{quote(conference_name)}.json",
            {"Status": "completed"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
