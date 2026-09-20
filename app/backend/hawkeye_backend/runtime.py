"""HubRuntime: the seam where the mesh, the store, and the websocket bus meet.

Implements EventSink. Every event a MasterClient produces passes through here,
which is where it gets a sequence number, gets persisted into the typed store,
and gets fanned out to connected apps. One path in, so nothing can reach a phone
without being recorded.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time

from hawkeye_backend.bus import EventBus
from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.config import Settings
from hawkeye_backend.household import Roster, unaccounted_count
from hawkeye_backend.master.base import MasterClient
from hawkeye_backend.models.common import Source, utc_now
from hawkeye_backend.models.events import (
    ContextEvent,
    CourierEvent,
    Envelope,
    FrameEvent,
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
from hawkeye_backend.replay import RecordSealed, ReplayRecorder
from hawkeye_backend.notices.detector import PERSON_STATES
from hawkeye_backend.replay.archive import NullArchive, ReplayArchive
from hawkeye_backend.replay.courier import (
    AddressProvenance,
    Courier,
    CourierReceipt,
    NullCourier,
)
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
        courier: Courier | None = None,
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
        # Who mails a sealed record to the responding department. Defaults to
        # NullCourier, which sends nothing and says so in terms the chain can
        # carry. Off by default because an accidental send cannot be recalled.
        self.courier: Courier = courier or NullCourier()

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
        self._thumb_warned = False
        #: Notices raised this session, by id, so a dismissal can republish
        #: the whole notice rather than a bare id. Not persisted: a notice
        #: is about a presence, and presence ids are reused across sessions.
        self._notices: dict[str, object] = {}
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

    def dismiss_notice(self, notice_id: str) -> "Notice":
        """Mark a notice cleared, and hand back the notice to republish.

        The hub keeps the notices it has raised this session so a dismissal can
        carry the original title, body, narration and frame rather than a bare
        id. A surface that joined after the dismissal then renders a complete,
        already-cleared notice instead of an empty banner.

        Unknown ids produce a minimal dismissed notice rather than a 404. The
        resident may be clearing something raised before a restart, and refusing
        would leave a banner they cannot get rid of.
        """
        from hawkeye_backend.models.common import Provenance, Source
        from hawkeye_backend.models.notice import Notice, NoticeSeverity

        existing = self._notices.get(notice_id)
        if existing is None:
            existing = Notice(
                notice_id=notice_id,
                severity=NoticeSeverity.INFO,
                title="Notice",
                body="This notice was raised before the hub restarted.",
                provenance=Provenance(
                    source=Source.AGENT_INFERENCE,
                    producer="app/backend",
                    detail=(
                        "Reconstructed for a dismissal. The hub no longer holds "
                        "the notice this clears, so nothing here is a claim about "
                        "what was originally observed."
                    ),
                ),
            )
        dismissed = existing.model_copy(
            update={"dismissed": True, "dismissed_at": utc_now()}
        )
        self._notices[notice_id] = dismissed
        return dismissed

    async def emit_notice(self, event: NoticeEvent) -> None:
        """The stream sink's callback. Separate so the recursion is visible.

        Every notice is remembered on the way past so a later dismissal can
        republish the whole thing rather than a bare id.
        """
        self._notices[event.notice.notice_id] = event.notice
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

    def cancel_attestation(self, request_id: str) -> None:
        """Stop waiting for an attestation that is never coming.

        Called on every path out of the shutter endpoint that is not a delivered
        attestation. Without it a failed grant leaves an entry in the pending
        map forever, and a process that runs for days accumulates one per
        failure.
        """
        future = self._pending_attestations.pop(request_id, None)
        if future is not None and not future.done():
            future.cancel()

    async def request_challenge(self, request_id: str) -> None:
        """Ask the edge's shutter for a fresh nonce.

        Phase one of two. The grant must be bound to a nonce the shutter itself
        issued, so there is no way to collapse this into a single message, and a
        cached nonce would leave a window in which a captured grant is still
        live.
        """
        from hawkeye_backend.edge.wire import EdgeChallengeRequest

        edge = self.edge
        if edge is None:
            raise EdgeUnavailable("no edge box is connected, so there is no shutter to ask")
        await edge.send_text(EdgeChallengeRequest(request_id=request_id).model_dump_json())

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
            # The courier runs first, and then the record is archived once.
            # Ordered this way so the archived copy carries the send receipt;
            # archiving first would store a record that is immediately stale
            # and would need writing twice for no gain.
            await self.deliver(incident_id, to=self.settings.courier_to, provenance="configured")
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

    async def deliver(
        self, incident_id: str, *, to: str, provenance: AddressProvenance
    ) -> CourierReceipt:
        """Send one sealed record to the responding department, and record it.

        Three things happen and all three are the point: the bundle goes out,
        the outcome is chained onto the sealed record, and every surface is
        told. A send whose outcome reached none of those is the failure this
        whole path exists to make impossible.

        Fails soft, like `_archive_sealed` and for the same reason - the moment
        this runs is the moment a 911 call ended. Anything that escapes the
        courier becomes a `failed` receipt that is chained and published,
        rather than an exception that silently loses the record's last fact.
        """
        session = self.recorder.get(incident_id)
        if session is None:
            raise KeyError(incident_id)
        if not session.sealed:
            raise RecordSealed(f"{incident_id} is not sealed; there is nothing to send yet")

        if not to:
            receipt = CourierReceipt(
                outcome="skipped",
                detail="no destination address; none was supplied and none is configured",
            )
        else:
            try:
                receipt = await self.courier.send(
                    session.to_record(), to=to, provenance=provenance
                )
            except Exception as exc:  # noqa: BLE001
                # Broad on purpose. A courier is an HTTP client talking to a
                # third party, and the one outcome that must not be possible
                # here is a record that says nothing about its own delivery.
                logger.exception("courier: unexpected failure sending %s", incident_id)
                receipt = CourierReceipt(
                    outcome="failed",
                    to=to,
                    provenance=provenance,
                    detail=f"unexpected failure: {type(exc).__name__}: {exc}",
                )

        try:
            session.append_courier_receipt(
                summary=receipt.summary,
                detail=receipt.model_dump(mode="json"),
                at=receipt.at,
            )
        except RecordSealed as exc:
            # Already delivered. Not an error: a re-send of a record that
            # arrived is a no-op worth logging and nothing more.
            logger.info("courier: not chaining a receipt for %s (%s)", incident_id, exc)

        await self.emit(
            CourierEvent(
                incident_id=incident_id,
                outcome=receipt.outcome,
                to=receipt.to,
                provenance=receipt.provenance,
                detail=receipt.detail,
                at=receipt.at,
            ),
            incident_id,
        )
        return receipt

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
        self._thumbnail_task = asyncio.create_task(self._publish_thumbnails())
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

    async def _publish_thumbnails(self) -> None:
        """Push a small frame onto the event stream, for the watch.

        Publishes nothing at all when there is no frame. Silence is the honest
        output: a watch drawing a grey rectangle labelled as a camera frame is
        precisely the lie this design exists to prevent.

        Re-encoding happens here rather than on the Pi because the Pi already
        ships one size, and a second encode on a Pi 4B costs frames off the
        stream a human is watching.
        """
        interval = self.settings.camera_thumbnail_interval_s
        last_index: int | None = None
        while True:
            try:
                frame = self.camera.latest
                if frame is not None and frame.index != last_index:
                    last_index = frame.index
                    status = self.camera.status()
                    thumb = self._thumbnail(frame.jpeg)
                    await self.emit(
                        FrameEvent(
                            jpeg_base64=base64.b64encode(thumb).decode(),
                            captured_at=frame.captured_at,
                            source=status.source or Source.CAMERA_SIM,
                            live=status.live,
                            room=self.settings.camera_room,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Broad on purpose, same as _poll_sensor. This task runs for the
                # life of the process and must not die of one bad frame during
                # an emergency.
                logger.exception("thumbnail publish failed")
            await asyncio.sleep(interval)

    def _thumbnail(self, jpeg: bytes) -> bytes:
        """Shrink a frame for the wrist, or hand back what we were given.

        OpenCV is not a hard dependency of this service, and a hub that refused
        to start because a thumbnail could not be resized would be trading the
        whole demo for a few kilobytes. Falls back to the full frame and says so
        once.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            if not self._thumb_warned:
                logger.warning(
                    "thumbnails: OpenCV is not installed, so full frames are going "
                    "to the watch. Install opencv-python-headless to shrink them."
                )
                self._thumb_warned = True
            return jpeg

        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jpeg
        height, width = image.shape[:2]
        longest = max(height, width)
        edge = self.settings.camera_thumbnail_long_edge
        if longest > edge:
            scale = edge / longest
            image = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        return buffer.tobytes() if ok else jpeg

    async def stop(self) -> None:
        if self._thumbnail_task is not None:
            self._thumbnail_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._thumbnail_task
            self._thumbnail_task = None
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
