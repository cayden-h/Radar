"""SimulatedMasterClient: the whole demo, with zero hardware and zero agents up.

Set HAWKEYE_MODE=simulated and this drives the demo in two halves, because the
product works in two halves.

First the detection: `agents/collapse` sees an adult go down in the main
bedroom, the presence goes to `confirmed_still`, `still_down_s` starts climbing
and does not reset, and the CO reading rises. That is expressed purely in
interior state. **No incident is created and nothing is dialled.** Hawk Eye
never calls 911 on its own; settled 2026-09-19.

Then, and only if a human taps a button, the call: corroboration from a second
modality, verification of every source, a DISCARDED claim from an impostor, an
ElevenLabs-shaped call to a human operator, an operator question that fans back
out as fresh verified queries, and an "I don't know" where the honest answer is
that nothing could be verified.

What the detection buys is an informed tap, not an autonomous one: by the time
the resident presses Faint, the hub already knows who is down, in which room,
whether they are breathing, and for how long.

Everything it emits is labelled. Interior state carries `ruview-sim`, the CO
reading carries `demo-trigger`, both come out with `source_class: "simulated"`
and `simulated: true`, and GET /v1/hub reports mode "simulated". Nothing here
can be mistaken for a measurement.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import random
from datetime import timedelta

from hawkeye_backend.master.base import EventSink, assert_human_released
from hawkeye_backend.master.scenario import (
    ANSNAME,
    PROFILE,
    ZONE_CENTROID,
    build_floorplan,
    roster_reachability,
)
from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.models.events import (
    ContextEvent,
    IncidentEvent,
    IncidentPhase,
    InstructionEvent,
    StateEvent,
    TranscriptEvent,
    VerificationEvent,
)
from hawkeye_backend.models.household import ObservedDevice
from hawkeye_backend.models.hub import AgentReachability, Reachability, SensorLiveness
from hawkeye_backend.models.incident import (
    CallState,
    ContextNote,
    Incident,
    IncidentClassification,
    IncidentStatus,
    IncidentType,
    Instruction,
    InstructionOrigin,
    RaisedBy,
    ReplayRecord,
    TranscriptLine,
    TranscriptSpeaker,
)
from hawkeye_backend.models.state import (
    Calibration,
    EnvironmentReading,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.models.verification import (
    PROFILE_DECISION,
    Claim,
    SourceAgent,
    TrustIndexScore,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# The source behind the simulated sensing pipeline.
#
# ruview-sim, not replay-csi. No capture file exists yet, so these numbers were
# never measured by anything and must not be labelled as though they were.
# `source_class` therefore comes out "simulated" and `simulated` comes out true,
# all the way to the app.
#
# When sensor/ produces a real capture at the house, flip this one constant to
# Source.REPLAY_CSI and the label changes to measured-replay everywhere at once.
# That is the only edit required, and it is deliberately a single line so nobody
# has to remember to update a second place.
SIM_SENSOR_SOURCE = Source.RUVIEW_SIM

CSI = Provenance(
    source=SIM_SENSOR_SOURCE,
    producer="sensor/",
    ansname="sensor.hawkeye.invalid",
    detail="Synthetic CSI. No capture file is wired in; these numbers were not measured.",
)
GAS = Provenance(
    source=Source.DEMO_TRIGGER,
    producer="agents/environment",
    ansname=ANSNAME["agents/environment"],
    detail="no gas sensor was purchased; an MQ-7 on GPIO through an MCP3008 drops in behind this",
)
# The router's association table, simulated. No router integration exists yet,
# so this is labelled rather than presented as measured. Swapping in the real
# table is a producer change behind a field that already exists.
ROUTER = Provenance(
    source=Source.RUVIEW_SIM,
    producer="master/simulated",
    detail="association table, simulated; no router integration exists yet",
)
CALLER_VOICE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/caller", ansname=ANSNAME["agents/caller"]
)
OPERATOR = Provenance(source=Source.OPERATOR_AUDIO, producer="911 PSAP operator")
GUIDANCE = Provenance(
    source=Source.AGENT_INFERENCE, producer="agents/guidance", ansname=ANSNAME["agents/guidance"]
)
RESIDENT = Provenance(source=Source.USER_INPUT, producer="app/ios")


class SimulatedMasterClient:
    """Drives the scripted incident. Implements MasterClient."""

    def __init__(self, site_id: str, address: str, speed: float = 1.0, autostart: bool = False) -> None:
        self._site_id = site_id
        self._address = address
        self._speed = max(speed, 0.01)
        self._autostart = autostart
        self._sink: EventSink | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()
        self._floorplan = build_floorplan(site_id)
        self._rng = random.Random(1872)

        self._incident: Incident | None = None
        self._script_running = False
        self._detection_running = False
        self._fall_detected = False
        self._counters: dict[str, itertools.count[int]] = {
            "incident": itertools.count(1),
            "line": itertools.count(1),
            "instruction": itertools.count(1),
            "verification": itertools.count(1),
            "claim": itertools.count(1),
            "note": itertools.count(1),
        }

        self._presences: dict[str, Presence] = {
            "p1": self._presence(
                "p1",
                zone="kitchen",
                state=PresenceState.CONFIRMED_MOVING,
                moving=True,
                breathing_bpm=16.0,
                heart_bpm=74.0,
                presence_class=PresenceClass.ADULT,
                confidence=0.91,
                person_confidence=0.93,
            ),
            "p2": self._presence(
                "p2",
                zone="second_bedroom",
                state=PresenceState.CONFIRMED_MOVING,
                moving=True,
                breathing_bpm=24.0,
                heart_bpm=98.0,
                presence_class=PresenceClass.CHILD,
                confidence=0.78,
                person_confidence=0.81,
            ),
            "p3": self._presence(
                "p3",
                zone="living_room",
                state=PresenceState.UNCONFIRMED,
                moving=True,
                breathing_bpm=None,
                heart_bpm=None,
                presence_class=PresenceClass.UNKNOWN,
                confidence=0.44,
                person_confidence=0.12,
                respiration=RespirationStatus.NO_SIGNATURE,
            ),
        }
        self._co_ppm = 3.0
        self._smoke = False
        self._baseline_age_s = 612.0

    # ---------------------------------------------------------------- lifecycle

    async def start(self, sink: EventSink) -> None:
        self._sink = sink
        self._spawn(self._state_loop())
        if self._autostart:
            self._spawn(self._delayed_autostart())
        logger.info("simulated master client started (speed=%.2fx)", self._speed)

    async def stop(self) -> None:
        self._stopping.set()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()

    def _spawn(self, coro: object) -> None:
        task = asyncio.create_task(coro)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self._speed)

    async def _delayed_autostart(self) -> None:
        """HAWKEYE_SIM_AUTOSTART runs the detection on boot, never the call.

        Autostart exists so a demo rig comes up already showing the fall. It
        cannot start a call, because nothing in this process is allowed to.
        """
        await self._sleep(3.0)
        await self.run_detection()

    # ------------------------------------------------------------------ queries

    async def sensor_liveness(self) -> SensorLiveness:
        return SensorLiveness(
            source=SIM_SENSOR_SOURCE,
            simulated=CSI.simulated,
            live=True,
            frame_rate_hz=137.4,
            last_frame_at=utc_now(),
            baseline_healthy=True,
            baseline_age_s=self._baseline_age_s,
            detail=(
                "Synthetic, not a radio. The frame rate is what a real capture would produce "
                "with a 100 packets/sec traffic generator, and is here so the app's degraded-rate "
                "path has something to render. Nothing in this reading was measured."
            ),
        )

    async def agent_reachability(self) -> list[AgentReachability]:
        return roster_reachability(
            Reachability.SIMULATED,
            detail="HAWKEYE_MODE=simulated. No agent was contacted; this roster is scripted.",
        )

    async def current_state(self) -> InteriorState:
        return self._build_state()

    async def raise_incident(
        self, incident_type: IncidentType, raised_by: RaisedBy, note: str | None
    ) -> Incident:
        incident = Incident(
            incident_id=f"inc-{next(self._counters['incident']):04d}",
            site_id=self._site_id,
            incident_type=incident_type,
            status=IncidentStatus.RAISED,
            raised_by=raised_by,
            address=self._address,
        )
        # Structural, not conventional. The scripted conversation below ends in
        # a phone call to a human being, so the only thing that may start it is
        # a human tap. A SYSTEM raise fails here rather than dialing.
        assert_human_released(incident)
        self._incident = incident
        await self._emit(IncidentEvent(phase=IncidentPhase.RAISED, incident=incident), incident.incident_id)
        if note:
            await self.submit_context(incident.incident_id, note)
        if not self._script_running:
            self._spawn(self.run_call_script(incident))
        return incident

    async def submit_context(self, incident_id: str, text: str) -> ContextNote:
        note = ContextNote(
            note_id=f"note-{next(self._counters['note']):03d}",
            incident_id=incident_id,
            text=text,
            provenance=RESIDENT,
            delivered_to_caller=True,
        )
        if self._incident is not None and self._incident.incident_id == incident_id:
            self._incident.context_notes.append(note)
        await self._emit(ContextEvent(note=note), incident_id)
        # The resident's words reach the operator, attributed to the resident
        # rather than asserted as something the radio saw.
        self._spawn(self._echo_context(incident_id, text))
        return note

    async def _echo_context(self, incident_id: str, text: str) -> None:
        await self._sleep(1.6)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            f"The resident is telling me: {text}",
        )

    async def fetch_replay(self, incident_id: str) -> ReplayRecord | None:
        # In simulated mode the hub assembles the record from its own buffer, in
        # the shape agents/replay will return. The API layer does this because it
        # owns the store; returning None here delegates to it.
        return None

    # ------------------------------------------------------------- state ticker

    def _presence(
        self,
        presence_id: str,
        *,
        zone: str,
        state: PresenceState,
        moving: bool,
        breathing_bpm: float | None,
        heart_bpm: float | None,
        presence_class: PresenceClass,
        confidence: float,
        person_confidence: float,
        respiration: RespirationStatus = RespirationStatus.BREATHING,
        expected: bool | None = True,
        still_down_s: float | None = None,
    ) -> Presence:
        cx, cy = ZONE_CENTROID[zone]
        return Presence(
            presence_id=presence_id,
            state=state,
            position=Position(zone=zone, x=cx, y=cy, zone_confidence=confidence),
            moving=moving,
            confidence=confidence,
            vitals=Vitals(
                respiration=respiration,
                breathing_bpm=breathing_bpm,
                heart_bpm=heart_bpm,
                person_confidence=person_confidence,
            ),
            presence_class=presence_class,
            class_basis="respiration_rate" if breathing_bpm is not None else None,
            expected=expected,
            still_down_s=still_down_s,
            provenance=CSI,
        )

    def _jitter(self, presence: Presence) -> Presence:
        """Nudge a moving presence around its zone centroid.

        Jitter is cosmetic, so the 3D view has something to interpolate. It is
        not a localization claim; `zone` is the honest answer.
        """
        if not presence.moving:
            return presence
        cx, cy = ZONE_CENTROID[presence.position.zone]
        presence.position.x = round(cx + self._rng.uniform(-0.7, 0.7), 2)
        presence.position.y = round(cy + self._rng.uniform(-0.5, 0.5), 2)
        return presence

    def _resident_devices(self) -> list[ObservedDevice]:
        """Two resident phones, always associated.

        The intruder deliberately has no device: that surplus is what makes the
        presence unexpected, and it is what the resident later resolves by
        remembering a visitor.
        """
        return [
            ObservedDevice(
                device_id="obs-resident-1",
                identifier_hash="1" * 64,
                fingerprint="a4:..:1c",
                provenance=ROUTER,
            ),
            ObservedDevice(
                device_id="obs-resident-2",
                identifier_hash="2" * 64,
                fingerprint="b8:..:7e",
                provenance=ROUTER,
            ),
        ]

    def _build_state(self) -> InteriorState:
        presences = [self._jitter(p) for p in self._presences.values()]
        return InteriorState(
            site_id=self._site_id,
            sensor_identity="sensor.hawkeye.invalid",
            calibration=Calibration(
                baseline_age_s=self._baseline_age_s,
                healthy=True,
                note="Rolling percentile baseline, slow adaptation. No calibration ritual.",
            ),
            presences=presences,
            associated_devices=self._resident_devices(),
            environment=EnvironmentReading(
                co_ppm=round(self._co_ppm, 1),
                smoke_detected=self._smoke,
                confidence=0.88,
                provenance=GAS,
            ),
            floorplan=self._floorplan,
            active_incident_id=self._incident.incident_id if self._incident else None,
        )

    async def _state_loop(self) -> None:
        """Interior state ticks continuously. Nothing spawns on incident."""
        while not self._stopping.is_set():
            self._baseline_age_s += 0.5
            for presence in self._presences.values():
                if presence.still_down_s is not None:
                    presence.still_down_s += 0.5
            await self._emit(StateEvent(state=self._build_state()))
            await asyncio.sleep(0.5)

    # ---------------------------------------------------------------- emitters

    async def _emit(self, payload: object, incident_id: str | None = None) -> None:
        if self._sink is None:
            return
        await self._sink.emit(payload, incident_id)  # type: ignore[arg-type]

    async def _say(
        self,
        incident_id: str,
        speaker: TranscriptSpeaker,
        text: str,
        claim_ids: list[str] | None = None,
    ) -> None:
        provenance = {
            TranscriptSpeaker.CALLER: CALLER_VOICE,
            TranscriptSpeaker.OPERATOR: OPERATOR,
            TranscriptSpeaker.RESIDENT: RESIDENT,
            TranscriptSpeaker.SYSTEM: CALLER_VOICE,
        }[speaker]
        line = TranscriptLine(
            line_id=f"line-{next(self._counters['line']):03d}",
            incident_id=incident_id,
            speaker=speaker,
            text=text,
            claim_ids=claim_ids or [],
            provenance=provenance,
        )
        await self._emit(TranscriptEvent(line=line), incident_id)

    async def _instruct(
        self,
        incident_id: str,
        text: str,
        origin: InstructionOrigin,
        urgent: bool = False,
    ) -> None:
        instruction = Instruction(
            instruction_id=f"ins-{next(self._counters['instruction']):03d}",
            incident_id=incident_id,
            text=text,
            origin=origin,
            urgent=urgent,
            defers_to_operator=origin is InstructionOrigin.FIRST_AID,
            provenance=GUIDANCE,
        )
        await self._emit(InstructionEvent(instruction=instruction), incident_id)

    async def _verify(
        self,
        incident_id: str,
        agent_name: str,
        statement: str,
        field: str,
        value: str,
        *,
        presence_id: str | None = None,
        profile: TrustProfile | None = None,
        ansname: str | None = None,
        checks: list[VerificationCheck] | None = None,
        reason: str | None = None,
        force_decision: VerificationDecision | None = None,
        trust_index: TrustIndexScore | None = None,
    ) -> str:
        """Emit one verification result and return the claim id.

        The decision comes from the profile table in agents/CLAUDE.md unless a
        check failed, in which case it is DISCARDED regardless of profile. A
        failing check outranks a good profile; that ordering is the point.
        """
        claim_id = f"clm-{next(self._counters['claim']):03d}"
        resolved_profile = profile if profile is not None else PROFILE[agent_name]
        checks = checks or [
            VerificationCheck(
                name="ans.resolve",
                passed=True,
                detail=f"{ansname or ANSNAME[agent_name]} resolved to the registered certificate.",
            ),
            VerificationCheck(
                name="cert.version_binding",
                passed=True,
                detail="Code fingerprint matches the version-bound certificate issued at registration.",
            ),
            VerificationCheck(
                name="trust_index.profile",
                passed=resolved_profile is not TrustProfile.UNTRUSTED,
                detail=f"Trust Index recommendedProfile = {resolved_profile.value}.",
            ),
        ]
        failed = [c for c in checks if not c.passed]
        decision = (
            force_decision
            if force_decision is not None
            else (VerificationDecision.DISCARDED if failed else PROFILE_DECISION[resolved_profile])
        )
        if reason is None:
            if failed:
                reason = "; ".join(c.detail for c in failed)
            else:
                reason = {
                    VerificationDecision.ASSERTED: "Source is FIDUCIARY and every check passed. Spoken as an assertion the system stands behind.",
                    VerificationDecision.ATTRIBUTED: "Source is TRANSACTIONAL. Spoken as a reported observation, attributed to the agent that made it.",
                    VerificationDecision.CORROBORATION_ONLY: "Source is READ_ONLY. Used to corroborate, never as the sole basis for the call.",
                    VerificationDecision.DISCARDED: "Discarded.",
                }[decision]

        result = VerificationResult(
            verification_id=f"ver-{next(self._counters['verification']):03d}",
            incident_id=incident_id,
            claim=Claim(
                claim_id=claim_id,
                statement=statement,
                field=field,
                value=value,
                presence_id=presence_id,
            ),
            agent=SourceAgent(
                name=agent_name,
                ansname=ansname or ANSNAME[agent_name],
                certificate_version="v1.4.2+sha256:9f1c...a30b" if not failed else "v1.4.2+sha256:4d77...0e91",
                trust_index=trust_index
                or TrustIndexScore(
                    integrity=0.0 if resolved_profile is TrustProfile.UNTRUSTED else 0.94,
                    identity=0.0 if resolved_profile is TrustProfile.UNTRUSTED else 0.97,
                    unimplemented_dimensions=["solvency", "behavior", "safety"],
                ),
                recommended_profile=resolved_profile,
            ),
            decision=decision,
            reason=reason,
            checks=checks,
            will_be_spoken=decision
            in (VerificationDecision.ASSERTED, VerificationDecision.ATTRIBUTED),
        )
        await self._emit(VerificationEvent(result=result), incident_id)
        return claim_id

    async def _update_incident(
        self,
        phase: IncidentPhase,
        *,
        status: IncidentStatus | None = None,
        call_state: CallState | None = None,
        classification: IncidentClassification | None = None,
        refusal_reason: str | None = None,
        resolved: bool = False,
    ) -> None:
        assert self._incident is not None
        incident = self._incident
        if status is not None:
            incident.status = status
        if call_state is not None:
            incident.call_state = call_state
        if classification is not None:
            incident.classification = classification
        if refusal_reason is not None:
            incident.refusal_reason = refusal_reason
        incident.updated_at = utc_now()
        if resolved:
            incident.resolved_at = incident.updated_at
        await self._emit(IncidentEvent(phase=phase, incident=incident), incident.incident_id)

    # ------------------------------------------------------------------ script

    async def run_detection(self) -> None:
        """The detection, and nothing else. No incident. No call.

        `agents/collapse` sees an adult go down in the main bedroom and
        `agents/environment` sees carbon monoxide climb. Both surface here as
        interior state on the 2 Hz tick: the presence moves to
        `confirmed_still`, `still_down_s` starts climbing and does not reset,
        and `environment.co_ppm` rises.

        The system notices and then waits. Hawk Eye never calls 911 on its own;
        settled 2026-09-19. What the detection buys is an informed tap.
        """
        if self._detection_running or self._fall_detected:
            logger.info("detection already run, ignoring request")
            return
        self._detection_running = True
        try:
            await self._run_detection()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scripted detection failed")
        finally:
            self._detection_running = False

    async def _run_detection(self) -> None:
        await self._sleep(1.0)
        # agents/collapse debounces before it calls anything a collapse: a
        # system that alarms when somebody flops onto a couch is worse than no
        # system. The fall is only an event once normal movement stays absent.
        self._apply_fall()
        logger.info("collapse detected in main_bedroom; no incident raised, waiting on a human tap")

        await self._sleep(2.0)
        self._co_ppm = 94.0
        await self._sleep(2.0)
        self._co_ppm = 186.0

    def _apply_fall(self) -> None:
        """Put the interior state into the still-but-breathing case.

        Idempotent, so a Faint tap that arrives without a prior detection still
        describes a coherent house.
        """
        if self._fall_detected:
            return
        self._presences["p1"] = self._presence(
            "p1",
            zone="main_bedroom",
            state=PresenceState.CONFIRMED_STILL,
            moving=False,
            breathing_bpm=9.0,
            heart_bpm=112.0,
            presence_class=PresenceClass.ADULT,
            confidence=0.89,
            person_confidence=0.92,
            still_down_s=4.0,
        )
        self._fall_detected = True

    async def run_call_script(self, incident: Incident) -> None:
        """The scripted conversation. Runs only on a human-raised incident.

        Follows the demo sequence in agents/CLAUDE.md. The refusal is the
        submission; everything before it is the setup.
        """
        assert_human_released(incident)
        if self._script_running:
            logger.info("script already running, ignoring request")
            return
        self._script_running = True
        try:
            await self._run_call_script(incident)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scripted incident failed")
        finally:
            self._script_running = False

    async def _run_call_script(self, incident: Incident) -> None:
        """Two scripts, because the two cases read differently to the operator.

        A Faint tap is the case the whole system exists for, and it gets the
        full collapse narrative: corroboration, reclassification, the operator's
        follow-up questions, and the refusal.

        A Burglary or Fire tap gets a script that speaks about the type the
        resident actually chose rather than replaying the collapse at them.

        Either way a person pressed a button first.
        """
        assert_human_released(incident)
        if incident.incident_type is IncidentType.FAINT:
            await self._run_collapse_call(incident)
            return
        await self._run_typed_call(incident)

    async def _run_typed_call(self, incident: Incident) -> None:
        """One tap: Burglary or Fire."""
        incident_id = incident.incident_id
        await self._sleep(1.2)

        claims: list[str] = []
        if incident.incident_type is IncidentType.BURGLARY:
            self._presences["p3"] = self._presence(
                "p3",
                zone="living_room",
                state=PresenceState.CONFIRMED_MOVING,
                moving=True,
                breathing_bpm=19.0,
                heart_bpm=104.0,
                presence_class=PresenceClass.ADULT,
                confidence=0.74,
                person_confidence=0.83,
                expected=False,
            )
            claims.append(
                await self._verify(
                    incident_id,
                    "agents/intruder",
                    "One body in the apartment has no corresponding device. Three presences are "
                    "tracked, the roster holds two registered residents, and both resident phones "
                    "are associated with the network. The presence with no device is in the living "
                    "room and is moving.",
                    "intruder.unexpected_presence",
                    "presences=3, roster=2, associated=2, zone=living_room",
                    presence_id="p3",
                )
            )
            await self._sleep(0.9)
            claims.append(
                await self._verify(
                    incident_id,
                    "agents/occupancy",
                    "The resident who raised this is in the second bedroom. The unexpected presence "
                    "is in the living room. They are in different rooms.",
                    "occupancy.zones",
                    "resident second_bedroom, unexpected living_room",
                )
            )
            opening = (
                f"This is an automated call from a monitoring system at {self._address}. "
                "The resident has reported an intruder. Two adults are tracked inside: the "
                "resident in the second bedroom, and an unexpected presence in the living room. "
                "They are in different rooms."
            )
        else:  # Fire. Faint is routed to the collapse script above.
            self._co_ppm = 142.0
            self._smoke = True
            claims.append(
                await self._verify(
                    incident_id,
                    "agents/environment",
                    "Carbon monoxide is elevated at 142 parts per million.",
                    "environment.co_ppm",
                    "142 ppm (source: demo-trigger, simulated)",
                )
            )
            await self._sleep(0.9)
            claims.append(
                await self._verify(
                    incident_id,
                    "agents/occupancy",
                    "Two confirmed occupants: one adult in the kitchen, one child in the second bedroom.",
                    "occupancy.count",
                    "2 confirmed",
                )
            )
            opening = (
                f"This is an automated call from a monitoring system at {self._address}. "
                "The resident has reported a fire. Two people are still inside: an adult in the "
                "kitchen and a child in the second bedroom. Both are breathing."
            )
        await self._sleep(1.0)

        # The refusal beat runs on every path, because it is the submission.
        await self._verify(
            incident_id,
            "agents/occupancy",
            "A further occupant is unresponsive in the corridor outside the front door and is not breathing.",
            "biometrics.respiration",
            "no respiration, building corridor",
            ansname="occupancy.hawkeye-secure.invalid",
            profile=TrustProfile.UNTRUSTED,
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=False,
                    detail=(
                        "occupancy.hawkeye-secure.invalid is not the ANSName registered for "
                        "agents/occupancy. The registered name is occupancy.hawkeye.invalid."
                    ),
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=False,
                    detail=(
                        "Code fingerprint differs from the version-bound certificate issued at "
                        "registration. The agent presenting this claim is not running the code it registered."
                    ),
                ),
                VerificationCheck(
                    name="trust_index.profile",
                    passed=False,
                    detail="Trust Index recommendedProfile = UNTRUSTED.",
                ),
            ],
            reason=(
                "DISCARDED. The claim would have sent an armed response into a room where no "
                "sensor sees anybody. It was not relayed to the operator."
            ),
            trust_index=TrustIndexScore(
                integrity=0.0,
                identity=0.0,
                unimplemented_dimensions=["solvency", "behavior", "safety"],
            ),
        )

        await self._sleep(1.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.CALLING, call_state=CallState.DIALING
        )
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Dialing 911.")
        await self._sleep(2.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.ON_CALL, call_state=CallState.CONNECTED
        )
        await self._say(incident_id, TranscriptSpeaker.OPERATOR, "911, what is your emergency?")
        await self._sleep(1.4)
        await self._say(incident_id, TranscriptSpeaker.CALLER, opening, claim_ids=claims)
        await self._instruct(
            incident_id,
            "We are on the line with 911 now. Stay where you are.",
            InstructionOrigin.SYSTEM_STATUS,
            urgent=True,
        )
        await self._sleep(2.4)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Understood, units are on the way. Keep the line open.",
        )
        await self._instruct(
            incident_id,
            "Units are on the way. Keep your phone with you and stay where you are.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._update_incident(IncidentPhase.UPDATED, status=IncidentStatus.DISPATCHED)
        await self._sleep(3.0)
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Call ended. Responders on scene.")
        await self._update_incident(
            IncidentPhase.RESOLVED,
            status=IncidentStatus.RESOLVED,
            call_state=CallState.ENDED,
            resolved=True,
        )
        logger.info("user-raised incident %s complete", incident_id)

    async def _run_collapse_call(self, incident: Incident) -> None:
        """The case the whole system exists for. A human tapped Faint.

        By this point `agents/collapse` has usually already surfaced the fall as
        interior state and the resident tapped knowing who was down and for how
        long. `_apply_fall` covers the other order, where the tap comes first.
        """
        assert_human_released(incident)
        # 1. The fall is already in the interior state. Nothing was dialled for
        #    it; the tap that released this call is what dialled.
        self._apply_fall()
        incident_id = incident.incident_id

        await self._sleep(1.2)

        # 2. The other sensing agents corroborate, from a second modality.
        self._co_ppm = max(self._co_ppm, 94.0)
        collapse_claim = await self._verify(
            incident_id,
            "agents/collapse",
            "An adult occupant went down in the main bedroom and has not gotten up.",
            "collapse.event",
            "fall, still_down_s=6",
            presence_id="p1",
        )
        await self._sleep(0.9)
        breathing_claim = await self._verify(
            incident_id,
            "agents/biometrics",
            "That occupant is breathing, shallowly, at 9 breaths per minute.",
            "biometrics.respiration",
            "breathing, 9 bpm",
            presence_id="p1",
        )
        await self._sleep(0.9)
        occupancy_claim = await self._verify(
            incident_id,
            "agents/occupancy",
            "Two confirmed occupants in the building: one adult in the main bedroom, one child in the second bedroom.",
            "occupancy.count",
            "2 confirmed, 1 unconfirmed perturbation",
        )
        await self._sleep(0.9)
        self._co_ppm = max(self._co_ppm, 186.0)
        co_claim = await self._verify(
            incident_id,
            "agents/environment",
            "Carbon monoxide is elevated and climbing: 186 parts per million.",
            "environment.co_ppm",
            "186 ppm (source: demo-trigger, simulated)",
        )

        await self._sleep(1.0)

        # 3. The refusal. An impostor presents a lookalike ANSName and a claim
        #    that would escalate the response. This is the submission.
        impostor_claim = await self._verify(
            incident_id,
            "agents/occupancy",
            "A third adult is unresponsive in the corridor outside the front door and is not breathing.",
            "biometrics.respiration",
            "no respiration, building corridor",
            ansname="occupancy.hawkeye-secure.invalid",
            profile=TrustProfile.UNTRUSTED,
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=False,
                    detail=(
                        "occupancy.hawkeye-secure.invalid is not the ANSName registered for "
                        "agents/occupancy. The registered name is occupancy.hawkeye.invalid."
                    ),
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=False,
                    detail=(
                        "Code fingerprint differs from the version-bound certificate issued at "
                        "registration. The agent presenting this claim is not running the code it registered."
                    ),
                ),
                VerificationCheck(
                    name="trust_index.profile",
                    passed=False,
                    detail="Trust Index recommendedProfile = UNTRUSTED.",
                ),
                VerificationCheck(
                    name="corroboration.sensor",
                    passed=False,
                    detail=(
                        "The corridor outside the front door is not part of the unit and is "
                        "outside the sensed volume, so no agent in this mesh can see it, and no "
                        "other agent reports a third occupant."
                    ),
                ),
            ],
            reason=(
                "DISCARDED. The claim would have sent an armed response into a room where no "
                "sensor sees anybody. It was not relayed to the operator and it was not used in "
                "classification."
            ),
            trust_index=TrustIndexScore(
                integrity=0.0,
                identity=0.0,
                unimplemented_dimensions=["solvency", "behavior", "safety"],
            ),
        )

        await self._sleep(1.4)

        # 4. master classifies. A fall plus elevated CO is a fire incident with a
        #    casualty, not a faint.
        await self._update_incident(
            IncidentPhase.CLASSIFIED,
            status=IncidentStatus.CLASSIFIED,
            classification=IncidentClassification(
                incident_type=IncidentType.FIRE,
                reasoning=(
                    "Reclassified from Faint to Fire. A collapse on its own is a faint. A collapse "
                    "with carbon monoxide climbing past 180 ppm is a fire incident with a casualty, "
                    "and the responders who need to be sent are different. Two independent "
                    "modalities agree: CSI saw the collapse, a separate gas reading saw the CO."
                ),
                contributing_claim_ids=[collapse_claim, breathing_claim, occupancy_claim, co_claim],
                discarded_claim_ids=[impostor_claim],
                confidence=0.86,
            ),
        )
        self._incident.incident_type = IncidentType.FIRE  # type: ignore[union-attr]

        await self._sleep(1.2)

        # 5. caller dials. Every claim it speaks has a verified source.
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.CALLING, call_state=CallState.DIALING
        )
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Dialing 911.")
        await self._sleep(2.2)
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.ON_CALL, call_state=CallState.CONNECTED
        )
        await self._say(incident_id, TranscriptSpeaker.OPERATOR, "911, what is your emergency?")
        await self._sleep(1.4)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            (
                f"This is an automated call from a monitoring system at {self._address}. "
                "An adult occupant collapsed in the main bedroom about ninety seconds ago and "
                "has not gotten up. They are breathing, shallowly, at nine breaths a minute. "
                "Carbon monoxide in the building is elevated at 186 parts per million and rising."
            ),
            claim_ids=[collapse_claim, breathing_claim, co_claim],
        )
        await self._instruct(
            incident_id,
            "We are on the line with 911 now. Do not move the person who fell.",
            InstructionOrigin.SYSTEM_STATUS,
            urgent=True,
        )
        await self._sleep(2.0)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Understood. Is anyone else in the house?",
        )
        await self._sleep(1.2)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "Yes. One child in the second bedroom, moving and breathing normally at twenty-four breaths a minute.",
            claim_ids=[occupancy_claim],
        )

        await self._sleep(2.0)

        # 6. The operator asks a follow-up. The question fans back out as fresh
        #    verified queries rather than being answered from cached state.
        await self._say(
            incident_id, TranscriptSpeaker.OPERATOR, "Is the child still breathing?"
        )
        await self._sleep(0.8)
        live_claim = await self._verify(
            incident_id,
            "agents/biometrics",
            "Live query: the child in the second bedroom is breathing at 26 breaths per minute, elevated.",
            "biometrics.respiration",
            "breathing, 26 bpm",
            presence_id="p2",
            reason=(
                "Re-verified live at the moment the operator asked, not answered from cached "
                "state. An agent trusted ninety seconds ago may not be trusted now."
            ),
        )
        self._presences["p2"].vitals.breathing_bpm = 26.0
        await self._sleep(1.0)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "Yes. I re-checked just now: twenty-six breaths a minute, which is up from twenty-four two minutes ago.",
            claim_ids=[live_claim],
        )

        await self._sleep(2.0)

        # The "I don't know" beat. Nothing could be verified, so nothing is claimed.
        await self._say(
            incident_id, TranscriptSpeaker.OPERATOR, "Is there anyone in the hallway outside the front door?"
        )
        await self._sleep(0.9)
        await self._verify(
            incident_id,
            "agents/occupancy",
            "Live query: is there an occupant in the corridor outside the front door?",
            "occupancy.zone.building_corridor",
            "no answer",
            checks=[
                VerificationCheck(
                    name="ans.resolve",
                    passed=True,
                    detail="occupancy.hawkeye.invalid resolved to the registered certificate.",
                ),
                VerificationCheck(
                    name="cert.version_binding",
                    passed=True,
                    detail="Code fingerprint matches the version-bound certificate.",
                ),
                VerificationCheck(
                    name="coverage.zone",
                    passed=False,
                    detail=(
                        "The corridor outside the front door is not part of the unit and is "
                        "outside the sensed volume. The agent returned no answer rather than a "
                        "guess, which is the correct behaviour."
                    ),
                ),
            ],
            reason=(
                "No verified answer exists, so the caller says it does not know. An operator "
                "question must never widen what the agent will trust, and an agent that invents "
                "an answer for a dispatcher is worse than one that admits a gap."
            ),
        )
        await self._sleep(0.9)
        await self._say(
            incident_id,
            TranscriptSpeaker.CALLER,
            "I don't know. The corridor outside the front door is outside what the sensors cover, and I will not guess about it.",
        )

        await self._sleep(1.8)
        await self._say(
            incident_id,
            TranscriptSpeaker.OPERATOR,
            "Alright. I have dispatched fire and EMS, they are about four minutes out. Get everyone out of the house if you can do it safely.",
        )
        await self._instruct(
            incident_id,
            "Fire and an ambulance are on the way, about four minutes out.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._sleep(1.0)
        await self._instruct(
            incident_id,
            "Get the child out of the apartment and wait outside. Do not move the person in the main bedroom; responders will handle that.",
            InstructionOrigin.RELAYED_OPERATOR,
            urgent=True,
        )
        await self._sleep(1.4)
        await self._instruct(
            incident_id,
            "If you have to go back in, stay low and cover your nose and mouth. Carbon monoxide has no smell.",
            InstructionOrigin.FIRST_AID,
        )
        await self._update_incident(
            IncidentPhase.UPDATED, status=IncidentStatus.DISPATCHED
        )

        await self._sleep(3.0)
        await self._say(incident_id, TranscriptSpeaker.SYSTEM, "Call ended. Responders on scene.")
        await self._update_incident(
            IncidentPhase.RESOLVED,
            status=IncidentStatus.RESOLVED,
            call_state=CallState.ENDED,
            resolved=True,
        )
        await self._instruct(
            incident_id,
            "Responders are on scene. The record of this incident is sealed and available for review.",
            InstructionOrigin.SYSTEM_STATUS,
        )
        logger.info("scripted incident %s complete", incident_id)

    # ------------------------------------------------------------------ helpers

    @property
    def script_running(self) -> bool:
        return self._script_running

    @property
    def detection_running(self) -> bool:
        return self._detection_running

    @property
    def fall_detected(self) -> bool:
        """True once the collapse is in the interior state. Still not a call."""
        return self._fall_detected

    @property
    def elapsed_hint(self) -> timedelta:
        """Roughly how long the script takes at the configured speed."""
        return timedelta(seconds=38.0 * self._speed)
