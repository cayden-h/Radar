"""agents/caller/transport/retell/transcript_sink.py

The best-effort side channel that fans out each transcript line to the hub as
it is spoken, so the resident's app can render the live operator <-> agent
conversation via the hub's existing `TRANSCRIPT` stream events.

Fail-soft by contract: a call in progress must never break because the hub is
unreachable. Any exception from the push is swallowed and logged; nothing
here raises into the call loop.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class TranscriptSink(Protocol):
    async def line(self, incident_id: str, speaker: str, text: str) -> None: ...


class HttpTranscriptSink:
    """Best-effort: pushes each transcript line to the hub. Never raises into
    the call loop."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def line(self, incident_id: str, speaker: str, text: str) -> None:
        try:
            await self._client.post(
                f"{self._base}/v1/incident/{incident_id}/transcript",
                json={"speaker": speaker, "text": text},
            )
        except Exception:
            logger.warning(
                "transcript sink: failed to push line for %s", incident_id, exc_info=True
            )
