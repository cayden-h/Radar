"""Decides what opens a record, what goes into it, and what seals it.

Wired into `HubRuntime.emit`, which is already the single path every event takes
on its way to a phone. That is the only place a record can be complete by
construction rather than by everyone remembering to call it.

Two rules are structural rather than conventional:

- **A record opens on a human tap and on nothing else.** `RaisedBy.SYSTEM` does
  not open one, because Hawk Eye never dials on its own and there is no call to
  record. `assert_human_released` enforces the same boundary one layer down.
- **A record seals when the call ends and never reopens.** Appending to a sealed
  record raises. See `ReplaySession.seal`.
"""

from __future__ import annotations

import logging
from datetime import datetime

from hawkeye_backend.models.events import (
    ContextEvent,
    EventPayload,
    IncidentEvent,
    IncidentPhase,
    InstructionEvent,
    NoticeEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.models.hub import SensorLiveness
from hawkeye_backend.models.incident import CallState, Incident, RaisedBy
from hawkeye_backend.models.state import InteriorState
from hawkeye_backend.replay.session import RecordSealed, ReplaySession

logger = logging.getLogger(__name__)


def _presence_signature(state: InteriorState) -> str:
    """What must change for a throttled frame to be recorded anyway.

    Presence state, zone and motion. Not vitals or position: breathing_bpm
    jitters every tick and would defeat the throttle entirely, while a presence
    going from CONFIRMED_MOVING to CONFIRMED_STILL is the single most important
    transition the system can record and must never be dropped.
    """
    return "|".join(
        f"{p.presence_id}:{p.state.value}:{p.position.zone}:{int(p.moving)}"
        for p in sorted(state.presences, key=lambda p: p.presence_id)
    )


def _rf_block(state: InteriorState, sensor: SensorLiveness | None) -> dict[str, object]:
    """The radio-side telemetry recorded with every frame.

    Derived, and labelled as derived. There is no raw CSI anywhere in this
    service, so `raw_csi` is null and stays null until the capture path exists.
    Root CLAUDE.md: never claim a sensing capability the physics does not
    support, and never present a simulated reading as a measured one.

    `frame_rate_hz` is the field that catches the quiet failure. Without a
    traffic generator a real capture drops to roughly 10 Hz, which barely
    resolves breathing and never resolves a short motion transient, with every component
    still reporting healthy. Recording it puts that on the record.
    """
    block: dict[str, object] = {
        "sensor_identity": state.sensor_identity,
        "baseline_age_s": round(state.calibration.baseline_age_s, 2),
        "baseline_healthy": state.calibration.healthy,
        "baseline_note": state.calibration.note,
        "raw_csi": None,
        "raw_csi_note": (
            "No raw Channel State Information is recorded. This block is telemetry "
            "derived from the sensing pipeline, not a radio capture."
        ),
        "respiration": [
            {
                "presence_id": p.presence_id,
                "breathing_bpm": p.vitals.breathing_bpm,
                "heart_bpm": p.vitals.heart_bpm,
                "respiration": p.vitals.respiration.value,
                "moving": p.moving,
                "confidence": round(p.confidence, 3),
            }
            for p in state.presences
        ],
    }
    if sensor is None:
        block["frame_rate_hz"] = None
        block["min_useful_frame_rate_hz"] = None
        block["source"] = None
        block["simulated"] = None
        block["sensor_note"] = "Sensor liveness was not available when this frame was recorded."
    else:
        block["frame_rate_hz"] = sensor.frame_rate_hz
        block["min_useful_frame_rate_hz"] = sensor.min_useful_frame_rate_hz
        block["source"] = sensor.source.value
        block["simulated"] = sensor.simulated
        block["live"] = sensor.live
        block["sensor_note"] = sensor.detail
    return block


def _frame_detail(state: InteriorState, sensor: SensorLiveness | None) -> dict[str, object]:
    """One recorded frame: enough to redraw the map, and the radio behind it."""
    return {
        "captured_at": state.captured_at.isoformat(),
        "presences": [
            {
                "presence_id": p.presence_id,
                "state": p.state.value,
                "zone": p.position.zone,
                "x": round(p.position.x, 3),
                "y": round(p.position.y, 3),
                "zone_confidence": round(p.position.zone_confidence, 3),
                "moving": p.moving,
                "confidence": round(p.confidence, 3),
                "presence_class": p.presence_class.value,
                "expected": p.expected,
                "respiration_lost_s": p.respiration_lost_s,
                "breathing_bpm": p.vitals.breathing_bpm,
                "heart_bpm": p.vitals.heart_bpm,
                "respiration": p.vitals.respiration.value,
                "person_confidence": round(p.vitals.person_confidence, 3),
                "source": p.provenance.source.value,
                "simulated": p.provenance.simulated,
            }
            for p in state.presences
        ],
        "environment": (
            None
            if state.environment is None
            else {
                "co_ppm": state.environment.co_ppm,
                "smoke_detected": state.environment.smoke_detected,
                "confidence": state.environment.confidence,
                "source": state.environment.provenance.source.value,
                "simulated": state.environment.provenance.simulated,
            }
        ),
        "rf": _rf_block(state, sensor),
    }


class ReplayRecorder:
    """Holds the open sessions and routes events into them."""

    def __init__(
        self,
        *,
        caller_ansname: str,
        frame_interval_s: float = 0.5,
        max_entries: int = 10000,
        floorplan_kept: bool = True,
    ) -> None:
        self.caller_ansname = caller_ansname
        self.frame_interval_s = frame_interval_s
        self.max_entries = max_entries
        self.floorplan_kept = floorplan_kept
        self._sessions: dict[str, ReplaySession] = {}
        self._order: list[str] = []
        #: Refreshed by HubRuntime's slow poll. Never fetched from inside the
        #: event path: a live-mode sensor probe is an HTTP call, and an HTTP call
        #: inside emit() would put the mesh's latency in front of the resident.
        self.sensor: SensorLiveness | None = None
        #: The floorplan the map is drawn against. Captured once per session from
        #: the first frame, because it is static geometry and repeating it in
        #: every frame would multiply the record's size for nothing.
        self._floorplans: dict[str, dict[str, object]] = {}
        #: Incident ids sealed since the last drain, waiting to be archived.
        #:
        #: The recorder is synchronous on purpose - it runs inside
        #: `HubRuntime.emit`, the one path every event takes to a phone, and an
        #: awaited network write in there would put Atlas's latency in front of
        #: the resident. So it does not archive anything. It names what it
        #: sealed, and the runtime, which is already async, does the writing.
        self._sealed_pending: list[str] = []

    # ------------------------------------------------------------------ reading

    def get(self, incident_id: str) -> ReplaySession | None:
        return self._sessions.get(incident_id)

    def sessions(self) -> list[ReplaySession]:
        """Newest first. What the website's index lists."""
        return [self._sessions[i] for i in reversed(self._order)]

    def floorplan(self, incident_id: str) -> dict[str, object] | None:
        return self._floorplans.get(incident_id)

    def drain_sealed(self) -> list[str]:
        """Incident ids sealed since the last call. Empties the queue.

        A hand-off rather than a log. Re-archiving is harmless because the write
        upserts on the incident id, but a queue that never emptied would mean
        every event after a seal did a round trip to Atlas for a record that is
        already stored.
        """
        pending, self._sealed_pending = self._sealed_pending, []
        return pending

    # ------------------------------------------------------------------ writing

    def observe(self, payload: EventPayload, incident_id: str | None) -> None:
        """Route one event. Never raises: recording must not break the stream."""
        try:
            self._observe(payload, incident_id)
        except RecordSealed as exc:
            # Expected whenever an event trails the call's end, e.g. a final
            # state tick. Worth a line, not a traceback.
            logger.info("replay: %s", exc)
        except Exception:
            logger.exception("replay: failed to record a %s event", type(payload).__name__)

    def _observe(self, payload: EventPayload, incident_id: str | None) -> None:
        if isinstance(payload, IncidentEvent):
            self._on_incident(payload)
            return

        # A state tick belongs to whichever incident is open, since the tick
        # itself carries no incident id until one is active.
        if isinstance(payload, StateEvent):
            target = incident_id or payload.state.active_incident_id
            session = self._sessions.get(target) if target else None
            if session is not None and not session.sealed:
                self._on_state(session, payload.state)
            return

        if incident_id is None:
            return
        session = self._sessions.get(incident_id)
        if session is None or session.sealed:
            return

        match payload:
            case VerificationEvent():
                session.append_verification(payload.result)
            case TranscriptEvent():
                line = payload.line
                session.append(
                    kind="transcript",
                    actor=line.speaker.value,
                    summary=f"{line.speaker.value}: {line.text}",
                    detail=line.model_dump(mode="json"),
                    at=line.at,
                )
            case InstructionEvent():
                ins = payload.instruction
                session.append(
                    kind="instruction",
                    actor=self.caller_ansname,
                    summary=ins.text,
                    detail=ins.model_dump(mode="json"),
                    at=ins.at,
                )
            case ContextEvent():
                note = payload.note
                session.append(
                    kind="context",
                    actor="resident",
                    summary=f"resident: {note.text}",
                    detail=note.model_dump(mode="json"),
                    at=note.at,
                )
            case NoticeEvent():
                notice = payload.notice
                session.append(
                    kind="notice",
                    actor="hub",
                    summary=getattr(notice, "headline", None) or str(notice),
                    detail=notice.model_dump(mode="json"),
                )
            case _:
                pass

    # ------------------------------------------------------------- the two ends

    def _on_incident(self, event: IncidentEvent) -> None:
        incident = event.incident
        session = self._sessions.get(incident.incident_id)

        if session is None:
            if event.phase is not IncidentPhase.RAISED:
                # An incident this recorder never saw raised. Recording from the
                # middle would produce a chain that silently omits its own
                # beginning, which is exactly the shape of a doctored record.
                return
            if incident.raised_by is not RaisedBy.USER:
                logger.info(
                    "replay: not recording %s, raised by %s and not by a person",
                    incident.incident_id,
                    incident.raised_by.value,
                )
                return
            self._open(incident)
            return

        if session.sealed:
            return

        session.append(
            kind="incident",
            actor="agents/master",
            summary=f"{event.phase.value}: {incident.status.value} / call {incident.call_state.value}",
            detail=incident.model_dump(mode="json"),
            at=incident.updated_at,
        )

        if incident.call_state is CallState.ENDED:
            session.seal(f"911 call ended, incident {incident.status.value}")
            self._sealed_pending.append(session.incident_id)
            logger.info(
                "replay: sealed %s, %d entries, root %s",
                session.incident_id,
                len(session),
                (session.root_hash or "")[:12],
            )
        elif incident.call_state is CallState.NOT_PLACED and incident.resolved_at is not None:
            # Resolved without a call ever being placed. There is no call end to
            # wait for, and leaving the record open forever would be worse.
            session.seal("incident resolved without a call being placed")
            self._sealed_pending.append(session.incident_id)

    def _open(self, incident: Incident) -> ReplaySession:
        session = ReplaySession(incident, self.caller_ansname)
        self._sessions[incident.incident_id] = session
        self._order.append(incident.incident_id)
        session.append(
            kind="lifecycle",
            actor="resident",
            summary=(
                f"Recording opened: {incident.incident_type.value} raised by "
                f"{incident.raised_by.value} at {incident.address}"
            ),
            detail={
                "incident": incident.model_dump(mode="json"),
                "recorder": "hawkeye_backend.replay",
                "hash_algorithm": "sha256",
                "opened_by": "human tap",
            },
            at=incident.raised_at,
        )
        logger.info("replay: opened record for %s", incident.incident_id)
        return session

    # ----------------------------------------------------------------- throttle

    def _on_state(self, session: ReplaySession, state: InteriorState) -> None:
        signature = _presence_signature(state)
        changed = signature != session.last_presence_signature
        now = state.captured_at
        due = self._frame_due(session.last_frame_at, now)

        if not changed and not due:
            session.frames_dropped += 1
            return

        if len(session) >= self.max_entries:
            # Frames only. Every claim, discard, transcript and instruction keeps
            # being recorded: they are the record's point, and they are bounded
            # by the length of a phone call rather than by a tick rate.
            session.frames_dropped += 1
            if not session.frames_suspended:
                session.frames_suspended = True
                session.append(
                    kind="lifecycle",
                    actor="hub",
                    summary=(
                        f"Frame recording suspended at {self.max_entries} entries. "
                        "Claims, transcript and instructions continue to be recorded."
                    ),
                    detail={"max_entries": self.max_entries},
                )
            return

        session.last_presence_signature = signature
        session.last_frame_at = now
        detail = _frame_detail(state, self.sensor)

        # The floorplan rides on the first recorded frame and on no other. It is
        # static geometry, so repeating it 200 times would multiply the record's
        # size for nothing; putting it inside the chain rather than alongside it
        # means the map a reviewer redraws is provably the one the incident was
        # recorded against, and it travels in the export for free.
        #
        # Worth stating on the record itself: the plan is authored from a
        # one-time enrollment walk, not sensed. Walls are the static baseline the
        # radio subtracts to see people, so it cannot map them and must not look
        # as though it did.
        if session.incident_id not in self._floorplans and self.floorplan_kept:
            plan = state.floorplan.model_dump(mode="json")
            plan["origin"] = "authored-enrollment-walk"
            plan["origin_note"] = (
                "Drawn once during enrollment. Not sensed: walls are the static baseline "
                "the radio subtracts in order to see people, so the system cannot map them."
            )
            self._floorplans[session.incident_id] = plan
            detail["floorplan"] = plan

        session.append(
            kind="frame",
            actor=state.sensor_identity,
            summary=self._frame_summary(state, changed),
            detail=detail,
            at=now,
        )

    def _frame_due(self, last: datetime | None, now: datetime) -> bool:
        if last is None:
            return True
        return (now - last).total_seconds() >= self.frame_interval_s

    @staticmethod
    def _frame_summary(state: InteriorState, changed: bool) -> str:
        people = len(state.presences)
        still = sum(1 for p in state.presences if p.state.value == "confirmed_still")
        zones = ", ".join(sorted({p.position.zone for p in state.presences})) or "none"
        head = "presence change" if changed else "frame"
        tail = f", {still} still" if still else ""
        return f"{head}: {people} in [{zones}]{tail}"
