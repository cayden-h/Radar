"""Where a notice goes.

Two sinks today. The stream sink puts a `NoticeEvent` on the websocket, which is
what draws the in-app banner. The Twilio sink sends an SMS, which is the only
one of the two that reaches a resident whose phone is locked and whose app is
closed.

APNs is the third sink and is **not implemented**. It is the reason this is a
protocol rather than a function call: adding it changes nothing above this file.
There is deliberately no local-notification sink - a `UNUserNotificationCenter`
notification only fires while the app holds the socket, which is exactly the
case the resident does not need help with, and on stage it is indistinguishable
from a real push.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import httpx

from hawkeye_backend.models.events import NoticeEvent
from hawkeye_backend.models.notice import Notice

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com"


@runtime_checkable
class NoticeSink(Protocol):
    """One way a notice reaches a person."""

    async def deliver(self, notice: Notice) -> None: ...


async def deliver(notice: Notice, sinks: Sequence[NoticeSink]) -> None:
    """Fan out to every sink. One sink failing never stops another.

    This is load-bearing for demo day: a Twilio trial that starts refusing
    A2P sends on Sunday morning must leave the in-app banner intact.
    """
    for sink in sinks:
        try:
            await sink.deliver(notice)
        except Exception:
            logger.exception("notice sink %s failed for %s", type(sink).__name__, notice.notice_id)


class StreamSink:
    """Publishes the notice onto the websocket, via the runtime's one emit path."""

    def __init__(self, emit: Callable[[NoticeEvent], Awaitable[None]]) -> None:
        self._emit = emit

    async def deliver(self, notice: Notice) -> None:
        await self._emit(NoticeEvent(notice=notice))


class TwilioSink:
    """Sends an SMS through the Twilio REST API.

    Uses `httpx` directly rather than the `twilio` package: the API is one form
    POST with basic auth, `httpx` is already a dependency, and the service holds
    the line on adding dependencies it does not need.

    Trial-account limits, stated where someone debugging will find them:
    the trial only sends to numbers verified in the Twilio console, every
    message is prefixed "Sent from your Twilio trial account", and US A2P 10DLC
    enforcement can begin refusing trial sends without warning.
    """

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        timezone: str,
        client: httpx.AsyncClient | None = None,
        min_interval_s: float = 60.0,
        max_per_process: int = 5,
    ) -> None:
        self._sid = account_sid
        self._from = from_number
        self._to = to_number
        self._tz = ZoneInfo(timezone)
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._auth = (account_sid, auth_token)
        self._min_interval_s = min_interval_s
        self._max_per_process = max_per_process
        self._sent = 0
        self._last_at: float | None = None
        self._lock = asyncio.Lock()

    def _body(self, notice: Notice) -> str:
        """The message. The street address is never in it.

        The dispatch address is bound at registration and sealed; it does not
        travel in claims and it does not travel here. An SMS is plaintext to a
        device that can be stolen, which is the threat model that put the
        address out of claims in the first place.

        The room comes off `notice.room`, which the detector resolved from the
        floorplan. The sink never re-derives it: one place decides what a zone
        is called, and a sink that parsed the rendered prose back apart would
        break the first time anyone reworded it.
        """
        local = notice.raised_at.astimezone(self._tz).strftime("%H:%M")
        where = f" in the {notice.room.lower()}" if notice.room else ""
        return f"Hawk Eye: unexpected person{where}, {local}.\nNot accounted for."

    async def deliver(self, notice: Notice) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._sent >= self._max_per_process:
                logger.warning("twilio: process cap of %d reached, dropping %s",
                               self._max_per_process, notice.notice_id)
                return
            if self._last_at is not None and (now - self._last_at) < self._min_interval_s:
                logger.warning("twilio: within %.0fs of the last send, dropping %s",
                               self._min_interval_s, notice.notice_id)
                return
            self._sent += 1
            self._last_at = now

        resp = await self._client.post(
            f"{TWILIO_API}/2010-04-01/Accounts/{self._sid}/Messages.json",
            auth=self._auth,
            data={"From": self._from, "To": self._to, "Body": self._body(notice)},
        )
        if resp.status_code >= 400:
            logger.error("twilio refused %s: %s %s", notice.notice_id, resp.status_code, resp.text)
            return
        logger.info("twilio sent %s", notice.notice_id)

    async def aclose(self) -> None:
        await self._client.aclose()
