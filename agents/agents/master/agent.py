"""The incident coordinator. Aggregates, classifies, routes, and refuses.

`master` is the trust boundary. It holds the only full picture, so it is the
place where verification must be strictest, and it is the last thing standing
between a compromised sensor and an armed response to someone's address.

Two properties are structural here rather than conventional:

**It never dials.** `master` has no method that places a call. The sensing
agents inform it continuously; it classifies and holds state; a human tap is
what releases `agents/caller`. `release_for_call` is the only path toward a
phone call and it raises on anything that was not raised by a person. Settled
2026-09-19, and saying so on stage is a feature rather than an apology - every
other agent demo this weekend argues its agent deserves more autonomy.

**It answers from live verification, never from cache.** `answer` re-admits the
current observations through the gate on every question, because an operator
asks now precisely because the answer may have changed, and an agent trusted
ninety seconds ago may not be trusted now.

The dispatch address is not here and must never be. It is bound at registration,
committed to in the card, and sealed. An agent that can change where a response
is sent is a swatting tool no matter how well the claims upstream verify.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from hawkeye_backend.models.common import Provenance, Source, utc_now
from hawkeye_backend.models.incident import IncidentType, RaisedBy
from hawkeye_backend.models.verification import (
    Claim,
    SourceAgent,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)
from hawkeye_backend.verification.envelope import Severity

from agents.core.base import Agent
from agents.core.identity import identity
from agents.master.episode import ShutterEpisode
from agents.master.shutter_client import ShutterClient
from agents.core.observations import AgentObservation, Assertion, Unknown
from agents.core.ports import GasSensor, ObservationSource
from agents.master.classify import Classification, classify
from agents.master.environment import ELEVATED_PPM, band_for
from agents.master.gate import AdmittedClaim, TrustGate

#: The agents master aggregates. Order is the order claims are admitted in,
#: which is also the order they appear in the verification feed, so `people`
#: first: its personhood verdict is what `intruder` is conditioned on.
# `people` became `presence` and `vision` joined when the shutter stopped being
# gated on a body count the radio can no longer produce. See
# docs/superpowers/specs/2026-09-20-motion-gated-shutter-design.md.
SENSING = ("presence", "intruder", "vision")


class AutonomousDialRefused(RuntimeError):
    """Something tried to put a non-human-raised incident on the dialing path.

    Raised rather than logged, because the failure it guards against is the
    whole project in reverse: a house that dials emergency services with nobody
    having asked it to.
    """


class ParticipationModeRefused(RuntimeError):
    """master declined to move a call's participation mode automatically.

    A local type rather than an import of `hawkeye_backend.master.base`'s
    class of the same name and the same shape: that module documents itself
    as living on the app/backend side of a process boundary this module
    already crosses in the other direction (this file already imports
    `hawkeye_backend.models.*`), but the two exceptions still belong to
    different processes and `agents/master/transport.py` is what translates
    this one into the 403 `LiveMasterClient` expects.

    Raised when automation - not a human hand - tries to move participation
    louder than it already is. See the `_MODE_LEVEL` table below: automation
    may only ever move a call toward quieter.
    """


#: Ordering for the "automation may only move quieter" rule in
#: `MasterAgent.set_participation_mode`. Mirrors
#: `app/backend/hawkeye_backend/master/simulated.py`'s `_MODE_LEVEL` exactly,
#: because the app and the agent must agree on what "louder" means.
_MODE_LEVEL = {"watching": 0, "whisper": 1, "full_voice": 2}


@dataclass
class Incident:
    """Master's own incident state. Small on purpose.

    The hub carries the rich model the app renders
    (`hawkeye_backend.models.incident.Incident`); this is what master needs to
    do its job, which is a type, a release gate and a trace.
    """

    incident_id: str
    incident_type: IncidentType
    raised_by: RaisedBy
    raised_at: datetime
    traceparent: str
    """Generated at incident open and propagated to every agent. One incident,
    one trace, across five independently registered services - which is the only
    way the sealed record in agents/replay reassembles into a timeline."""

    classification: Classification | None = None
    released_for_call: bool = False
    context_notes: list[str] = field(default_factory=list)
    participation_mode: str = "watching"
    """The resident's current call participation mode, as master last saw it
    set. Tracked here so `set_participation_mode` below has a current value
    to check "louder" against - the same guard
    `SimulatedMasterClient.set_participation_mode` holds in simulated mode,
    now held on the agents side for a live call."""


class MasterAgent(Agent):
    """Aggregates the five sensing agents behind one gate."""

    interval_s = 1.0

    def __init__(
        self,
        mesh: ObservationSource,
        *,
        gas: GasSensor | None = None,
        profiles: dict[str, TrustProfile] | None = None,
        shutter_client: ShutterClient | None = None,
    ) -> None:
        super().__init__(identity("master"))
        self._mesh = mesh
        # The gas sensor is read directly rather than through the gate, because
        # a sensor attached to this host has no counterparty to authenticate.
        # The full reasoning, and what we gave up by collapsing it out of its
        # own agent, is in `agents/master/environment.py`. What matters here is
        # that the reading is labelled unverified-by-construction rather than
        # quietly inheriting master's own FIDUCIARY standing.
        self._gas = gas
        self._profiles = profiles
        self._incident: Incident | None = None
        self._last_gate: TrustGate | None = None
        # None in tests that only exercise classification. A master with no
        # shutter client simply never issues a grant, which is the correct
        # degenerate behaviour rather than a crash.
        self._shutter = shutter_client
        self._episode = ShutterEpisode()
        self._vision_silent_ticks = 0

    # ------------------------------------------------------------------ the job

    def tick(self) -> AgentObservation:
        gate, admitted, unreachable = self._gather()
        self._last_gate = gate
        vision_silent = self._drive_shutter(admitted)

        classification = classify(
            admitted,
            requested=self._incident.incident_type if self._incident else None,
        )
        if self._incident is not None and classification is not None:
            self._incident.classification = classification

        provenance = Provenance(
            source=Source.AGENT_INFERENCE,
            producer=self.identity.name,
            ansname=self.identity.ansname,
            detail=f"{len(admitted)} admitted, {len(gate.discarded)} discarded",
        )

        assertions: list[Assertion] = []
        if classification is not None:
            assertions.extend(
                [
                    Assertion(
                        field="master.incident_type",
                        value=classification.incident_type.value,
                        severity_ceiling=Severity.ACTIONABLE,
                        confidence=classification.confidence,
                        basis=classification.reasoning,
                        provenance=provenance,
                    ),
                    Assertion(
                        field="master.classification_basis",
                        value=",".join(classification.contributing_fields) or "none",
                        severity_ceiling=Severity.INFORMATIONAL,
                        confidence=1.0,
                        basis=(
                            "The fields that contributed. A classification built from one "
                            "signal is a thermostat; this one combines independent modalities "
                            "and shows which."
                        ),
                        provenance=provenance,
                    ),
                ]
            )
        if vision_silent:
            assertions.append(
                Assertion(
                    field="master.vision_silent",
                    value="true",
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=1.0,
                    basis=(
                        "The lens is uncovered and the camera is not reporting. Nothing "
                        "closes it automatically, because a silence timeout is what an "
                        "attacker who can kill the vision agent would want. Close it from "
                        "the app if this is not expected."
                    ),
                    provenance=provenance,
                )
            )
        assertions.extend(
            [
                Assertion(
                    field="master.accepted",
                    value=str(len(admitted)),
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=f"{len(admitted)} claim(s) survived the gate.",
                    provenance=provenance,
                ),
                Assertion(
                    field="master.discarded",
                    value=str(len(gate.discarded)),
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=(
                        f"{len(gate.discarded)} claim(s) discarded and logged with a reason. The "
                        "discard log is what makes 'it tells you what it discarded' checkable "
                        "rather than assertable."
                    ),
                    provenance=provenance,
                ),
                Assertion(
                    field="master.speakable",
                    value=str(len(gate.speakable())),
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=(
                        f"{len(gate.speakable())} claim(s) agents/caller may repeat to an operator. "
                        + (
                            "Zero: no claim this pass arrived over a verified transport. Every "
                            "claim caller speaks has a verified source or it does not get spoken, "
                            "and that rule is not relaxed because a demo is running."
                            if not gate.speakable()
                            else ""
                        )
                    ),
                    provenance=provenance,
                ),
            ]
        )

        # The air reading, surfaced on master's own observation so the app can
        # render it alongside everything else. It is already in the verification
        # feed as a CORROBORATION_ONLY claim; this is the same fact, published.
        for claim in admitted:
            if claim.assertion.field.startswith("master.co_"):
                assertions.append(claim.assertion)

        unknowns = tuple(
            Unknown(
                field=f"{slug}.*",
                reason=(
                    f"agents/{slug} produced no observation. Unreachable and 'nothing to "
                    "report' are different facts and this is the first one."
                ),
            )
            for slug in unreachable
        )

        return self.observe(
            assertions=tuple(assertions),
            unknowns=unknowns,
            healthy=not unreachable,
            note=(
                f"{classification.incident_type.value if classification else 'unclassified'}, "
                f"{len(admitted)} admitted, {len(gate.discarded)} discarded"
            ),
        )

    # ------------------------------------------------------------- aggregation

    #: Ticks of vision silence, with the lens open, before the resident is told.
    #: Not a timeout: nothing closes on silence, because a silence timeout is
    #: precisely what an attacker who can kill `vision` wants. The condition is
    #: made loud and a human decides.
    VISION_SILENT_NOTICE_TICKS = 20

    def _drive_shutter(self, admitted: list[AdmittedClaim]) -> bool:
        """The two shutter decisions. True when the resident should be told
        that the lens is open and the camera has gone quiet.

        Decision A opens on motion alone. Decision B closes on the camera's own
        verdict. They are independent: neither reads the other's input, which is
        what let the body count the 2026-09-19 pivot deleted stop being
        load-bearing.

        Only admitted claims reach here, so an unverified `no_person` has
        already been capped by the gate and cannot retire a verified grant.
        """
        if self._shutter is None:
            return False

        rooms = {a.assertion.zone_scope for a in admitted}
        notice = False

        for room in sorted(rooms):
            moving = any(
                a.assertion.field == "presence.motion"
                and a.assertion.value == "true"
                and a.assertion.zone_scope == room
                and a.spoken
                for a in admitted
            )
            occupancy = next(
                (
                    a.assertion.value
                    for a in admitted
                    if a.assertion.field == "vision.occupancy"
                    and a.assertion.zone_scope == room
                    and a.spoken
                ),
                None,
            )

            # ------------------------------------------------ Decision B, close
            if self._episode.is_open(room):
                if occupancy is None:
                    # Nothing closes on silence. See VISION_SILENT_NOTICE_TICKS.
                    self._vision_silent_ticks += 1
                    if self._vision_silent_ticks >= self.VISION_SILENT_NOTICE_TICKS:
                        notice = True
                else:
                    self._vision_silent_ticks = 0
                    if occupancy == "no_person" and self._shutter.request(
                        action="close", reason=f"vision:{room}:no_person"
                    ):
                        self._episode.closed(room)
                continue

            # ------------------------------------------------- Decision A, open
            if not moving:
                self._episode.on_clear(room)
                continue
            if self._episode.on_motion(room) and self._shutter.request(
                action="open", reason=f"motion:{room}"
            ):
                self._episode.opened(room)
                self._vision_silent_ticks = 0

        return notice

    def _gather(self) -> tuple[TrustGate, list[AdmittedClaim], list[str]]:
        """Re-read and re-admit every sensing agent. Fresh, every time.

        Nothing is cached between ticks on purpose. Trust is a property of an
        agent at an instant, and a claim admitted a minute ago carries a verdict
        about a minute-old state of the world that may no longer hold.
        """
        gate = TrustGate(profiles=self._profiles)
        admitted: list[AdmittedClaim] = []
        unreachable: list[str] = []
        incident_id = self._incident.incident_id if self._incident else None
        for slug in SENSING:
            fetched = self._mesh.fetch(slug)
            if fetched is None:
                unreachable.append(slug)
                continue
            # Claims the transport already refused. Recorded first, so a discard
            # at the wire is as visible in the feed as one at the gate - and it
            # is the more interesting kind, because a failed signature is an
            # attack where a capped severity is only a policy.
            for rejection in fetched.rejected:
                gate.record_transport_rejection(rejection, incident_id=incident_id)
            admitted.extend(
                gate.admit(
                    fetched.observation,
                    incident_id=incident_id,
                    envelope_verified=fetched.envelope_verified,
                )
            )
        admitted.extend(self._local_air(gate, incident_id))
        return gate, admitted, unreachable

    def _local_air(self, gate: TrustGate, incident_id: str | None) -> list[AdmittedClaim]:
        """Read the gas sensor, and put the reading in the feed as what it is.

        This does not go through the gate, and pretending otherwise would be
        worse than not doing it at all. There is no signature to check because
        there is no counterparty: master is both the producer and the consumer.

        So the claim is manufactured here with a verification result that says
        so in its checks, and its severity is capped at CORROBORATING no matter
        how high the number climbs. A simulated reading from an unverified local
        input must never be able to move anybody on its own: it is never
        speakable to an operator, and it is marked simulated in its provenance
        wherever it is rendered.

        Be exact about how far that goes, because it is less than it once was.
        Elevated CO on its own *does* classify, as the weakest Fire row in
        `classify`: a person tapped the button and the air is bad, which is a
        fire whatever the radio can see. What it cannot do is say anything
        about the occupants. That row carries the lowest confidence of the four
        and its reasoning states plainly that no presence was resolved and
        occupancy is unknown. Every row that makes a claim about people
        requires a CSI-derived claim alongside this reading - a lost breathing
        signature, a still breathing presence, or a resolved presence that is
        up and moving. Nothing built on this number alone asserts something
        only the radio could know.
        """
        if self._gas is None:
            return []
        reading = self._gas.read()
        source = _gas_source(reading.source)
        simulated = source is Source.DEMO_TRIGGER
        provenance = Provenance(
            source=source,
            producer=self.identity.name,
            ansname=self.identity.ansname,
            detail=(
                "Simulated. No MQ-7 exists on this installation; a real one is a driver "
                "behind an interface that already exists and nothing above it changes."
                if simulated
                else "MQ-7 on the Pi's GPIO through an MCP3008 ADC."
            ),
        )
        band = band_for(reading.co_ppm)
        elevated = reading.co_ppm >= ELEVATED_PPM
        confidence = 0.3 if simulated else 0.6

        checks = [
            VerificationCheck(
                name="envelope_verified",
                passed=False,
                detail=(
                    "Not applicable: this is a sensor attached to this host, not a claim from "
                    "a registered agent. There is no counterparty to authenticate. If the gas "
                    "sensor moves onto separate hardware it gets its own ANS identity and "
                    "goes through the gate like everything else."
                ),
            ),
            VerificationCheck(
                name="modality_independence",
                passed=True,
                detail=(
                    "Not derived from CSI. Two independent modalities agreeing is real "
                    "corroboration; two views of one CSI stream agreeing is not."
                ),
            ),
            VerificationCheck(
                name="measured",
                passed=not simulated,
                detail=(
                    "SIMULATED: source is `demo-trigger`, which computes to simulated. No gas "
                    "sensor was purchased."
                    if simulated
                    else "Measured by an MQ-7 on the Pi's GPIO."
                ),
            ),
        ]

        claims: list[AdmittedClaim] = []
        for field, value, basis in (
            (
                "master.co_ppm",
                f"{reading.co_ppm:.1f}",
                (
                    f"{reading.co_ppm:.1f} ppm carbon monoxide: {band}. Read from a locally "
                    "attached sensor, which is a different modality from the radio. A "
                    "2.4/5 GHz radio cannot sense gas composition at any price."
                    + (" This reading is simulated." if simulated else "")
                ),
            ),
            (
                "master.co_band",
                band,
                "UL 2034 alarm threshold band. This is what a real CO alarm implements.",
            ),
            (
                "master.co_elevated",
                "true" if elevated else "false",
                (
                    f"{'Above' if elevated else 'Below'} the {ELEVATED_PPM:.0f} ppm UL 2034 "
                    "alarm floor. Elevated CO alongside a breathing signature that has gone "
                    "missing is a fire with an occupant who may not be able to respond."
                ),
            ),
        ):
            assertion = Assertion(
                field=field,
                value=value,
                # CORROBORATING is the ceiling and it is not negotiable.
                severity_ceiling=Severity.CORROBORATING,
                confidence=confidence,
                basis=basis,
                provenance=provenance,
            )
            result = VerificationResult(
                verification_id=f"v-{uuid.uuid4().hex[:12]}",
                incident_id=incident_id,
                claim=Claim(
                    claim_id=f"c-{uuid.uuid4().hex[:12]}",
                    statement=basis,
                    field=field,
                    value=value,
                ),
                agent=SourceAgent(
                    name=self.identity.name,
                    ansname=self.identity.ansname,
                    recommended_profile=TrustProfile.READ_ONLY,
                ),
                # READ_ONLY maps to CORROBORATION_ONLY: never the sole basis for
                # a call. That is the honest standing for an unverified local
                # reading, and for a simulated one it is generous.
                decision=VerificationDecision.CORROBORATION_ONLY,
                reason=(
                    "Local sensor read directly by master. Not ANS-verified, because there is "
                    "no counterparty. Corroboration only, never the sole basis for a call."
                ),
                checks=checks,
                will_be_spoken=False,
            )
            claim = AdmittedClaim(
                assertion=assertion, result=result, granted=Severity.CORROBORATING
            )
            gate.accepted.append(claim)
            claims.append(claim)
        return claims

    # -------------------------------------------------------------- the incident

    def raise_incident(
        self,
        incident_type: IncidentType,
        raised_by: RaisedBy,
        note: str | None = None,
        *,
        incident_id: str | None = None,
    ) -> Incident:
        """Open an incident. A person taps; master records and classifies.

        Accepts a SYSTEM raise deliberately: a lost breathing signature from
        `people`, an unexpected presence from `intruder`, or elevated CO on
        master's own gas reading should surface as incidents in the app,
        because surfacing them is the entire point of detecting them. What a
        SYSTEM raise cannot do is reach `release_for_call`.

        `incident_id` defaults to a fresh uuid, same as before this parameter
        existed. `agents/master/transport.py`'s `/a2a/start-call` handler
        passes the id `app/backend`'s hub already minted for this incident,
        so the hub's record and master's own carry the same id rather than
        two ids for one incident.
        """
        incident = Incident(
            incident_id=incident_id or f"i-{uuid.uuid4().hex[:12]}",
            incident_type=incident_type,
            raised_by=raised_by,
            raised_at=utc_now(),
            # W3C traceparent. Propagated to every agent so five independently
            # registered services produce one reassemblable timeline in the
            # sealed record. See the transparency-log section of ans/CLAUDE.md.
            traceparent=f"00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01",
        )
        if note:
            incident.context_notes.append(note)
        self._incident = incident
        return incident

    def submit_context(self, text: str) -> None:
        """The resident's free text from the "what is happening" box.

        Held for `caller` to use. It is human input and carries no authority
        over verification: an operator's question cannot widen what this agent
        will trust, and neither can a frightened resident's typing.
        """
        if self._incident is None:
            raise RuntimeError("no open incident to attach context to")
        self._incident.context_notes.append(text)

    def release_for_call(self) -> Incident:
        """The only path toward a phone call, and the only place it is gated.

        Structural rather than conventional, so a future change that
        reintroduces an autonomous raise fails loudly at the point it would have
        dialed rather than quietly at the point it was written.
        """
        if self._incident is None:
            raise AutonomousDialRefused("there is no incident to release.")
        if self._incident.raised_by is not RaisedBy.USER:
            raise AutonomousDialRefused(
                f"incident {self._incident.incident_id} was raised by "
                f"{self._incident.raised_by.value!r} and must not reach the dialing path. "
                "Hawk Eye never calls 911 on its own; a detection surfaces as interior state "
                "and a human tap releases the call."
            )
        self._incident.released_for_call = True
        return self._incident

    def set_participation_mode(self, mode: str, *, by_human: bool) -> str:
        """Change the tracked participation mode for the active call.

        Same rule as everywhere else this project enforces it: automation may
        only ever move a call toward quieter (watching -> whisper ->
        full_voice is "louder"). Going louder without `by_human=True` is
        refused rather than silently capped, for the same reason
        `AutonomousDialRefused` is raised rather than logged above - a
        refusal that fails loudly is checkable; one that fails quietly is
        not.

        This is a second, independent copy of the guard `agents/caller`'s own
        `Bridge.set_mode` already holds (`ModeChangeRefused` there). Holding
        it here too is deliberate: master is the trust boundary this
        `/a2a/set-mode` handler sits behind, and the fact that `caller` would
        also catch a bad request is not a reason for the boundary agent to
        skip its own check.
        """
        if self._incident is None:
            raise ParticipationModeRefused(
                "there is no active incident to change participation mode for."
            )
        current = self._incident.participation_mode
        if mode not in _MODE_LEVEL:
            raise ParticipationModeRefused(f"unknown participation mode {mode!r}.")
        if not by_human and _MODE_LEVEL[mode] > _MODE_LEVEL[current]:
            raise ParticipationModeRefused(
                f"automation may only move participation toward quieter; refusing "
                f"{current!r} -> {mode!r} for incident {self._incident.incident_id} "
                "without a human hand"
            )
        self._incident.participation_mode = mode
        return mode

    @property
    def incident(self) -> Incident | None:
        return self._incident

    # ------------------------------------------------------------- the fan-out

    def answer(self, field: str, *, zone: str | None = None) -> tuple[str | None, str]:
        """Answer one question from a fresh verified query. Returns (value, why).

        This is what an operator's mid-call question becomes: not a cache read,
        a fan-out. "Is the child still breathing?" causes every sensing agent to
        be re-read and re-admitted, and the answer comes back at the speed of
        the slowest single one rather than the sum of them.

        A `None` value is a real answer and must reach the operator as "I don't
        know". An agent that invents an answer for a dispatcher is worse than
        one that admits a gap.
        """
        gate, admitted, unreachable = self._gather()
        self._last_gate = gate

        for claim in admitted:
            if claim.assertion.field != field:
                continue
            if zone is not None and claim.assertion.zone_scope != zone:
                continue
            if not claim.spoken:
                # Verified-but-unspeakable is its own answer and it is not "no".
                # Saying which is what keeps the refusal legible on stage.
                return None, (
                    f"A claim for {field} exists and was admitted, but its source was not "
                    f"cryptographically verified, so it will not be spoken. "
                    f"{claim.result.reason}"
                )
            return claim.assertion.value, claim.assertion.basis

        # Nothing admitted. Say why, distinguishing the three reasons, because a
        # dispatcher hearing "I don't know" deserves to know which kind it is.
        for result in gate.discarded:
            if result.claim.field == field:
                return None, f"A claim for {field} was discarded: {result.reason}"
        slug = field.split(".", 1)[0]
        if slug in unreachable:
            return None, f"agents/{slug} is not reachable, so nothing can be said about {field}."
        for fetched in (self._mesh.fetch(s) for s in SENSING):
            for unknown in fetched.observation.unknowns if fetched else ():
                if unknown.field == field and (zone is None or unknown.zone_scope == zone):
                    return None, unknown.reason
        return None, f"No agent has anything to say about {field}."

    @property
    def discarded(self) -> list[VerificationResult]:
        """Everything the gate refused on the last pass, with reasons."""
        return list(self._last_gate.discarded) if self._last_gate else []

    @property
    def admitted(self) -> list[AdmittedClaim]:
        return list(self._last_gate.accepted) if self._last_gate else []


def _gas_source(sensor_source: str) -> Source:
    """Sensor's source string to the closed enum, failing toward simulated.

    Failing toward "simulated" is the only safe direction: mislabelling a
    generated number as measured is the exact failure the honesty rule exists
    to prevent.
    """
    try:
        return Source(sensor_source)
    except ValueError:
        return Source.DEMO_TRIGGER
