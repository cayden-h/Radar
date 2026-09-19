"""HubRuntime: the seam where the mesh, the store, and the websocket bus meet.

Implements EventSink. Every event a MasterClient produces passes through here,
which is where it gets a sequence number, gets persisted into the typed store,
and gets fanned out to connected apps. One path in, so nothing can reach a phone
without being recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from hawkeye_backend.master.base import MasterUnavailable
from hawkeye_backend.notices import NoticeDetector, NoticeSink, StreamSink, deliver
from hawkeye_backend.replay import ReplayRecorder
from hawkeye_backend.store import InMemoryStore, Store

logger = logging.getLogger(__name__)

#: How often the cached SensorLiveness is refreshed for the recorder. Slow on
#: purpose: it annotates frames, it does not gate anything.
SENSOR_POLL_INTERVAL_S = 2.0


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
        recorder: ReplayRecorder | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.bus = bus
        self.client = client
        self.started_at = time.monotonic()
        self.detector = detector or NoticeDetector(
            hold_s=settings.notice_hold_s,
            forget_after_s=settings.notice_forget_after_s,
        )
        # The stream sink is always present, so the in-app banner never depends
        # on Twilio being configured or on Twilio being up.
        self.notice_sinks: list[NoticeSink] = [StreamSink(self.emit_notice)]
        self.notice_sinks.extend(notice_sinks or [])

        # The incident recorder. Opens a record on a human tap, seals it when the
        # 911 call ends. It sits on emit() because that is the one path every
        # event takes, which is what makes the record complete by construction
        # rather than by every producer remembering to call it.
        self.recorder = recorder or ReplayRecorder(
            caller_ansname=settings.caller_ansname,
            frame_interval_s=settings.replay_frame_interval_s,
            max_entries=settings.replay_max_entries,
        )
        self._sensor_task: asyncio.Task[None] | None = None

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

        # After publishing, so recording can never delay an event reaching the
        # resident during a live call. `observe` swallows its own exceptions for
        # the same reason: a bug in the recorder must not be able to stop a
        # transcript line or a discard notice getting through.
        self.recorder.observe(payload, incident_id)

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
        self._sensor_task = asyncio.create_task(self._poll_sensor())
        logger.info("hub runtime started in %s mode", self.settings.mode)

    async def _poll_sensor(self) -> None:
        """Keep a recent SensorLiveness where the recorder can read it.

        The recorder stamps every recorded frame with the radio's state, and in
        live mode fetching that is an HTTP call to the mesh. Doing it from inside
        emit() would put the mesh's latency in front of the resident, so it is
        polled slowly out here instead. A failure leaves the cached reading stale
        and the recorder records it as stale; it never invents one.
        """
        while True:
            try:
                self.recorder.sensor = await self.client.sensor_liveness()
            except (MasterUnavailable, Exception) as exc:  # noqa: B014 - see below
                # Broad on purpose. This task runs for the life of the process
                # and must not die of an unexpected client error, because the
                # frames it feeds are recorded during an emergency.
                logger.debug("sensor poll failed: %s", exc)
            await asyncio.sleep(SENSOR_POLL_INTERVAL_S)

    async def stop(self) -> None:
        if self._sensor_task is not None:
            self._sensor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sensor_task
            self._sensor_task = None
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
