"""Fan-out from the master client to every connected websocket.

One publisher (whichever MasterClient is running), many subscribers (each iOS
app connection). A slow subscriber is dropped rather than allowed to back up the
publisher: during an incident a stale frame is worthless and blocking the mesh
on a phone that went to sleep is unacceptable.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from hawkeye_backend.models.events import Envelope

logger = logging.getLogger(__name__)


class Subscription:
    """One subscriber's queue."""

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=maxsize)
        self.dropped: int = 0

    async def __aiter__(self) -> AsyncIterator[Envelope]:
        while True:
            yield await self.queue.get()


class EventBus:
    """In-process pub/sub for stream envelopes."""

    def __init__(self, per_subscriber_buffer: int = 256) -> None:
        self._subscribers: set[Subscription] = set()
        self._buffer = per_subscriber_buffer
        self._lock = asyncio.Lock()

    async def subscribe(self) -> Subscription:
        sub = Subscription(self._buffer)
        async with self._lock:
            self._subscribers.add(sub)
        logger.info("stream subscriber joined (%d total)", len(self._subscribers))
        return sub

    async def unsubscribe(self, sub: Subscription) -> None:
        async with self._lock:
            self._subscribers.discard(sub)
        logger.info("stream subscriber left (%d total)", len(self._subscribers))

    async def publish(self, envelope: Envelope) -> None:
        """Deliver to every subscriber. Never blocks on a slow one."""
        async with self._lock:
            targets = list(self._subscribers)
        for sub in targets:
            try:
                sub.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                sub.dropped += 1
                logger.warning(
                    "subscriber buffer full, dropped seq=%d (dropped %d total)",
                    envelope.seq,
                    sub.dropped,
                )

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
