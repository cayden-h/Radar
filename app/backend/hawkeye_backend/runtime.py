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
from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.config import Settings
from hawkeye_backend.household import Roster, unaccounted_count
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
from hawkeye_backend.notices.detector import PERSON_STATES
from hawkeye_backend.replay.archive import NullArchive, ReplayArchive
from hawkeye_backend.store import InMemoryStore, Store

logger = logging.getLogger(__name__)

#: How often the cached SensorLiveness is refreshed for the recorder. Slow on
#: purpose: it annotates frames, it does not gate anything.
SENSOR_POLL_INTERVAL_S = 2.0


class EdgeUnavailable(RuntimeError):
    """There is no edge box connected.

    Raised rather than queued. A grant has a ten second TTL, and one delivered
    after the situation that produced it has passed is a replay waiting to
    happen rather than a late success.
    """


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
        archive: ReplayArchive | None = None,
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
        self.roster = Roster(store)
        self.detector = detector or NoticeDetector(
            hold_s=settings.notice_hold_s,
            forget_after_s=settings.notice_forget_after_s,
            is_suppressed=self.approved_presences.__contains__,
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
        # Where a sealed record goes so it outlives this process. Defaults to
        # NullArchive, which persists nothing and says so; see replay/archive.py.
        self.archive: ReplayArchive = archive or NullArchive()

        # The newest camera frame and everyone who wants a copy. Owned by the
        # runtime rather than by the endpoint, because it outlives any one
        # websocket: the edge reconnecting must not reset what the phone sees.
        self.camera = LiveCamera(stale_after_s=settings.camera_stale_after_s)

        # The connected edge websocket, when there is one. Held so a shutter
        # grant has somewhere to go. `None` is the honest answer when the Pi is
        # not there, and the shutter endpoint says so rather than timing out.
        self.edge: object | None = None

        #: request_id -> the future waiting on that attestation.
        self._pending_attestations: dict[str, asyncio.Future[object]] = {}
        self._thumbnail_task: asyncio.Task[None] | None = None
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

        # A record that just sealed leaves the process here. The recorder is
        # synchronous and cannot await a write; this is the first async frame
        # above it, and it runs after publish so archiving can never delay an
        # event reaching the resident.
        await self._archive_sealed()

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
            # Record before detecting. A device that arrived on this frame should
            # be a binding candidate by the time the notice about it lands.
            for device in payload.state.associated_devices:
                await self.roster.observe(device)

            # This is where remembering a visitor starts to mean something.
            #
            # `Presence.expected` is decided upstream and knows nothing about
            # this hub's roster, so without this the roster would be a list
            # nobody consults and "Remember this visitor" would change nothing
            # about the next visit.
            #
            # The rule lives in household/accounting.py and is called rather
            # than reimplemented, so `agents/intruder` and the hub cannot drift
            # on whether someone is unaccounted for.
            #
            # It can only ever lower an alarm. With no devices reported,
            # `known_devices_present` is 0, the surplus equals the headcount,
            # and nothing is suppressed: an absent field means not reported,
            # never that everyone is accounted for.
            people = sum(1 for p in payload.state.presences if p.state in PERSON_STATES)
            known = await self.roster.known_devices_present(payload.state.associated_devices)
            if unaccounted_count(people=people, known_devices_present=known) == 0:
                return

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

    # --------------------------------------------------------------- the edge

    def resolve_attestation(self, attestation: object) -> None:
        """Hand an attestation back to whoever asked for the move.

        Called from the edge link's receive loop. Unknown request ids are logged
        and dropped rather than raising: an attestation arriving after its
        caller gave up is stale, not dangerous.
        """
        request_id = getattr(attestation, "request_id", "")
        future = self._pending_attestations.pop(request_id, None)
        if future is None:
            logger.warning(
                "attestation for unknown request %r, dropped. Its caller has "
                "already given up.",
                request_id,
            )
            return
        if not future.done():
            future.set_result(attestation)

    def await_attestation(self, request_id: str) -> asyncio.Future[object]:
        """Register interest in an attestation before the grant is sent.

        Registered first so an attestation that comes back faster than the
        caller resumes still has somewhere to land.
        """
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending_attestations[request_id] = future
        return future

    async def send_grant(self, grant_json: str, request_id: str) -> None:
        """Push a signed grant down the edge link.

        `grant_json` crosses as the opaque string it arrived as. Nothing on this
        path parses or re-serializes it, because `shutter` verifies the
        signature over exactly those bytes and any reformatting would look
        exactly like tampering.
        """
        from hawkeye_backend.edge.wire import EdgeGrant

        edge = self.edge
        if edge is None:
            raise EdgeUnavailable("no edge box is connected, so there is no servo to move")
        await edge.send_text(
            EdgeGrant(request_id=request_id, grant_json=grant_json).model_dump_json()
        )

    async def _archive_sealed(self) -> None:
        """Write out every record sealed since the last event.

        Fails soft in two layers, deliberately. The archive itself returns False
        rather than raising, and this catches anything that gets past it. A
        record is already complete in memory by the time it seals, so losing the
        archive costs durability and nothing else - and the moment this runs is
        the moment a 911 call ends, which is the worst possible moment to raise.
        """
        for incident_id in self.recorder.drain_sealed():
            session = self.recorder.get(incident_id)
            if session is None:
                continue
            incident = await self.store.get_incident(incident_id)
            try:
                await self.archive.save(
                    session.to_record(),
                    incident_type=incident.incident_type.value if incident else "unknown",
                    opened_at=session.opened_at,
                    frames_dropped=session.frames_dropped,
                    seal_reason=session.seal_reason,
                )
            except Exception:
                logger.exception("replay archive: unexpected failure persisting %s", incident_id)

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
