"""agents/agents/caller/transport/retell/courier_client.py

The seam between the live 911 call and the backend courier. When the operator
gives a department email on the call, the orchestrator reads it back for
confirmation and hands it here; this posts it to
`POST {base_url}/v1/incident/{incident_id}/courier`, where the backend chains
what happened and mails the sealed bundle.

Real-vs-simulated split, mirroring `client.py`'s RetellVoiceClient: a Protocol
plus an httpx implementation for the wired path and a recording implementation
for the demo fallback and the parent's tests. The two exercise the identical
orchestrator path, so nothing about the email flow is special-cased to whether
a backend is actually up.

**The email is a destination, never authorization.** It is `operator_supplied`
- a human statement on a phone call, read back and recorded as what it is,
never promoted to permission for anything. This mirrors the "reported, never
trusted" doctrine in `app/backend/hawkeye_backend/replay/courier.py`: an agent
that can change where a response is sent is a swatting tool no matter how well
the claims upstream verify, so the address is carried with its provenance
attached and nothing downstream reads it as a grant. This client only carries
it; the backend records the provenance and chains the real outcome.

**Fail soft, always.** The live call must not break because an email POST
failed. The backend's chain records the true outcome of the send; a failure
here is logged and swallowed rather than raised into the WebSocket call loop,
because a dropped 911 call causes a dispatch and losing the sealed-record email
does not. Delivery is best-effort and re-triable through the backend endpoint;
the call is not.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

#: Pull one email address out of a spoken operator line.
#:
#: Deliberately conservative rather than RFC-5322 complete: an operator reading
#: an address aloud on a phone call produces a plain `local@domain.tld`, and a
#: greedy pattern would sooner match noise in a transcript than help. If nothing
#: matches, the orchestrator stays in its ASKED_EMAIL state and lets the
#: operator repeat it, which is the correct outcome for "I didn't catch that"
#: rather than a guess sent to a real inbox.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def find_email(text: str) -> str | None:
    """The first email address in a spoken line, or None if there is none."""
    match = _EMAIL_RE.search(text or "")
    return match.group(0) if match else None


class BackendCourierClient(Protocol):
    async def deliver(self, incident_id: str, to: str) -> None: ...


class HttpBackendCourierClient:
    """Posts the operator-supplied address to the backend courier endpoint.

    Own-vs-injected client tracked so `aclose()` only closes what this object
    created, matching `RealRetellVoiceClient`. Every failure path - transport
    error, timeout, non-2xx - is logged and swallowed: the backend chain is the
    record of the send's outcome, and this call sits on the live-call loop where
    an exception would be a self-inflicted dispatch.
    """

    def __init__(
        self, base_url: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10.0)
        # Only close what we created; an injected client is owned elsewhere.
        self._owns_client = client is None

    async def deliver(self, incident_id: str, to: str) -> None:
        # The email is the destination only. It is passed straight through as
        # `to`; the backend attaches `operator_supplied` provenance and never
        # reads it as authorization. See this module's docstring.
        url = f"{self._base_url}/v1/incident/{incident_id}/courier"
        try:
            resp = await self._client.post(url, json={"to": to})
        except httpx.HTTPError as exc:
            # Fail soft: the call outlives a courier POST that never landed.
            logger.warning("courier POST to %s failed to send: %s", url, exc)
            return
        if resp.status_code >= 400:
            # The endpoint returns 202 even for a failed *send*; a 4xx/5xx here
            # is the request itself being rejected. Still swallowed - the call
            # continues - but logged loudly so it is not silent in the demo.
            logger.warning(
                "courier POST to %s rejected: %s %s",
                url,
                resp.status_code,
                resp.text,
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SimulatedBackendCourierClient:
    """No network, no backend. Records every deliver call so the demo's fallback
    and the parent's tests can assert the operator's address reached the courier
    seam, and drives the identical orchestrator path the real client does.
    """

    def __init__(self) -> None:
        self.deliveries: list[dict[str, str]] = []

    async def deliver(self, incident_id: str, to: str) -> None:
        self.deliveries.append({"incident_id": incident_id, "to": to})
