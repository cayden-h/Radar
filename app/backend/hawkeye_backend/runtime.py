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
    NoticeEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.notices import NoticeDetector, NoticeSink, StreamSink, deliver
from hawkeye_backend.store import InMemoryStore, Store

logger = logging.getLogger(__name__)


class HubRuntime:
    """Holds everything with a lifetime longer than one request."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        bus: EventBus,
        client: MasterClient,
        detector: NoticeDetector | None = None,
        notice_sinks: list[NoticeSink] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.bus = bus
        self.client = client
        self.started_at = time.monotonic()
        # Presences the resident has vouched for, this session only. Deliberately
        # not persisted: a new session reuses presence ids, so a stored approval
        # would silently vouch for a stranger.
        self.approved_presences: set[str] = set()
        self.detector = detector or NoticeDetector(
            hold_s=settings.notice_hold_s,
            forget_after_s=settings.notice_forget_after_s,
            is_suppressed=self.approved_presences.__contains__,
        )
        # The stream sink is always present, so the in-app banner never depends
        # on Twilio being configured or on Twilio being up.
        self.notice_sinks: list[NoticeSink] = [StreamSink(self.emit_notice)]
        self.notice_sinks.extend(notice_sinks or [])

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_at

    async def emit(self, payload: EventPayload, incident_id: str | None = None) -> None:
        """Sequence, persist, publish. The only way an event reaches the app.

        Because it is the only way, it is also the right place to run the notice
        detector: neither master client needs to know notices exist, and a
        future third client gets them for free.
        """
        seq = await self.store.next_seq()
        env = Envelope(seq=seq, payload=payload, incident_id=incident_id)
        await self._persist(env)
        await self.store.append_event(env)
        await self.bus.publish(env)

        # After publishing, so the frame the notice describes is already on the
        # wire when the notice arrives. Only StateEvent feeds the detector, which
        # is what bounds the recursion through emit_notice to one level.
        #
        # Guarded for the same reason `deliver` guards each sink, one level up:
        # `emit` is the single path every event takes to reach the app, and a
        # notice is an addition on top of that pipeline. A bug in the detector
        # must not be able to stop a transcript line or a verification result
        # reaching the resident during a live call.
        if isinstance(payload, StateEvent):
            try:
                notices = self.detector.observe(payload.state)
            except Exception:
                logger.exception("notice detector failed on seq=%d", seq)
                notices = []
            for notice in notices:
                await deliver(notice, self.notice_sinks)

    async def emit_notice(self, event: NoticeEvent) -> None:
        """The stream sink's callback. Separate so the recursion is visible."""
        await self.emit(event)

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
            # NoticeEvent has no typed record of its own: it is already in the
            # event log via append_event, and the app reads it off the stream.
            case _:
                pass

    async def start(self) -> None:
        await self.client.start(self)
        logger.info("hub runtime started in %s mode", self.settings.mode)

    async def stop(self) -> None:
        await self.client.stop()
        # The runtime owns the sinks, so it closes them. TwilioSink only closes
        # an HTTP client it created itself, so this is safe for an injected one.
        # Duck-typed rather than declared on NoticeSink: a sink that holds no
        # resource, like StreamSink, should not be forced to implement a no-op
        # aclose just to satisfy the protocol. Revisit if a third sink arrives.
        for sink in self.notice_sinks:
            closer = getattr(sink, "aclose", None)
            if closer is not None:
                await closer()

    def in_memory_store(self) -> InMemoryStore | None:
        """The in-memory store, when that is what is configured.

        Used for the locally-assembled replay record in simulated mode. Returns
        None rather than pretending, so the caller has to handle the other case.
        """
        return self.store if isinstance(self.store, InMemoryStore) else None
