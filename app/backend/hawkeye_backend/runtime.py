"""HubRuntime: the seam where the mesh, the store, and the websocket bus meet.

Implements EventSink. Every event a MasterClient produces passes through here,
which is where it gets a sequence number, gets persisted into the typed store,
and gets fanned out to connected apps. One path in, so nothing can reach a phone
without being recorded.
"""

from __future__ import annotations

import logging
import time

from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings
from hawkeye_backend.master.base import MasterClient
from hawkeye_backend.models.events import (
    ContextEvent,
    Envelope,
    EventPayload,
    IncidentEvent,
    InstructionEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.store import InMemoryStore, Store

logger = logging.getLogger(__name__)


class HubRuntime:
    """Holds everything with a lifetime longer than one request."""

    def __init__(self, settings: Settings, store: Store, bus: EventBus, client: MasterClient) -> None:
        self.settings = settings
        self.store = store
        self.bus = bus
        self.client = client
        self.started_at = time.monotonic()

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_at

    async def emit(self, payload: EventPayload, incident_id: str | None = None) -> None:
        """Sequence, persist, publish. The only way an event reaches the app."""
        seq = await self.store.next_seq()
        env = Envelope(seq=seq, payload=payload, incident_id=incident_id)
        await self._persist(env)
        await self.store.append_event(env)
        await self.bus.publish(env)

    async def _persist(self, env: Envelope) -> None:
        """Write the typed record behind an event into the store."""
        payload = env.payload
        match payload:
            case StateEvent():
                await self.store.put_state(payload.state)
            case IncidentEvent():
                await self.store.put_incident(payload.incident)
            case TranscriptEvent():
                await self.store.append_transcript(payload.line)
            case InstructionEvent():
                await self.store.append_instruction(payload.instruction)
            case VerificationEvent():
                await self.store.append_verification(payload.result)
            case ContextEvent():
                await self.store.append_context(payload.note)
            case _:
                pass

    async def start(self) -> None:
        await self.client.start(self)
        logger.info("hub runtime started in %s mode", self.settings.mode)

    async def stop(self) -> None:
        await self.client.stop()

    def in_memory_store(self) -> InMemoryStore | None:
        """The in-memory store, when that is what is configured.

        Used for the locally-assembled replay record in simulated mode. Returns
        None rather than pretending, so the caller has to handle the other case.
        """
        return self.store if isinstance(self.store, InMemoryStore) else None
