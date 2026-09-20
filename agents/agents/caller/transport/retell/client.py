"""agents/agents/caller/transport/retell/client.py

Raw httpx calls to Retell's REST API, matching transport/twilio_client.py's
style: no `retell` SDK, Bearer auth, own-vs-injected client tracked so aclose()
only closes what this object created.

Retell is free for calling, which is why it replaced the paywalled Twilio Voice
transport as the real path. See docs/superpowers/specs/2026-09-20-retell-call-transport-design.md.
"""

from __future__ import annotations

from typing import Protocol

import httpx

RETELL_API = "https://api.retellai.com"


class RetellVoiceClient(Protocol):
    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str: ...


class RealRetellVoiceClient:
    def __init__(
        self, *, api_key: str, agent_id: str = "", client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self._agent_id = agent_id
        self._client = client or httpx.AsyncClient(timeout=10.0)
        # Only close what we created; an injected client is owned elsewhere.
        self._owns_client = client is None

    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str:
        body: dict = {
            "from_number": from_number,
            "to_number": to_number,
            "metadata": metadata,
        }
        # Bind the agent explicitly when configured. Retell otherwise uses the
        # agent bound to from_number. The destination number is a server-side
        # setting, never request input - the swatting-address rule.
        if self._agent_id:
            body["override_agent_id"] = self._agent_id
        resp = await self._client.post(
            f"{RETELL_API}/v2/create-phone-call",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Retell refused create-phone-call: {resp.status_code} {resp.text}"
            )
        return resp.json()["call_id"]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SimulatedRetellVoiceClient:
    """No network, no Retell account. Drives the identical orchestrator path so
    the demo's fallback and everyday development exercise real CallerAgent logic.
    """

    def __init__(self) -> None:
        self._counter = 0
        self.calls: list[dict] = []

    async def create_phone_call(
        self, *, from_number: str, to_number: str, metadata: dict
    ) -> str:
        self._counter += 1
        self.calls.append(
            {"from_number": from_number, "to_number": to_number, "metadata": metadata}
        )
        return f"SIM-RETELL-{self._counter:04d}"

    async def aclose(self) -> None:
        return None
