"""Detects and tracks a presence that no registered device accounts for.

Distinct from `agents/people` in the question it asks, which is why it stayed a
separate agent through the 2026-09-19 merge. `people` says how many and where;
`intruder` says **which of them is not supposed to be here**, and keeps a
continuous track once it decides.

They were not merged because they do not share an input. `people` reads the
radio; this reads `people` plus the network. Different evidence, different
failure modes, and a claim from each one corroborating the other is worth
something - which is exactly what two views of the same CSI stream would not be.

The decision rule, settled 2026-09-19, and it is stateable on a stage in four
lines:

    CSI:        3 distinct presences
    Roster:     2 registered residents      (configuration, not discovery)
    Associated: 2 resident phones on the network
                -------------------------------------
                1 body with no corresponding device

The household is known, not discovered. That is what survives the question a
judge will certainly ask - how do you tell a burglar from a roommate - because
the roommate's phone is on the network.

**Name the holes rather than pretending there are none.** A resident who left
their phone in the car. A guest. A burglar carrying a phone that never
associates. Every real security product has these gaps, and every assertion this
agent makes carries them in its basis so they get said out loud.

**It is a client of `agents/people`, and it treats that hop the way `master`
treats its own.** If the personhood verdict did not arrive over a verified
transport, this agent still reports what it computed - the information is real
and a resident should see it - but it caps what that report may trigger at
CORROBORATING and says why in the basis. An unverified verdict is not a verdict
to send officers on, and applying the same rule one hop earlier is what keeps
the posture consistent rather than concentrated entirely in `master`.

Two limits are enforced in code rather than remembered:

- **Personhood gates everything.** A perturbation with no respiration signature
  is a curtain, and calling police on a curtain is the failure mode this agent
  is designed against. Nothing here reads the CSI feed directly; it reads the
  personhood verdict from `agents/people`.
- **We cannot say which body is the stranger when residents are also home.** A
  1x1 link resolves zones, not identities, and there is no re-identification.
  When the house is registered empty the answer is unambiguous; when it is not,
  this agent reports that there is an unaccounted body and lists every occupied
  zone, and refuses to guess which one it is. That refusal is the honest answer
  and it is still an extremely useful one to a responding officer.
"""

from __future__ import annotations

from dataclasses import dataclass

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion, Unknown
from agents.core.ports import ObservationSource, RosterSource

#: Consecutive clear ticks before a declared track is dropped. A track that
#: flickers off because one window missed a breath and back on a second later
#: is worse than no track: it tells an officer the intruder left.
CLEAR_TICKS_TO_DROP = 10


@dataclass
class _Track:
    """A continuous track, held once the agent has decided there is one."""

    opened_tick: int
    zones: tuple[str, ...]
    unaccounted: int
    clear_ticks: int = 0


class IntruderAgent(Agent):
    """Roster arithmetic over verified personhood, with a sticky track."""

    interval_s = 1.0

    def __init__(self, roster: RosterSource, mesh: ObservationSource) -> None:
        super().__init__(identity("intruder"))
        self._roster = roster
        self._mesh = mesh
        self._track: _Track | None = None
        self._tick_count = 0

    def tick(self) -> AgentObservation:
        self._tick_count += 1
        fetched = self._mesh.fetch("people")
        people = fetched.observation if fetched is not None else None
        upstream_verified = bool(fetched and fetched.envelope_verified)

        if people is None:
            # No personhood verdict means no intruder decision, full stop. This
            # agent has no fallback to amplitude and must never grow one.
            return self.blind(
                "intruder.unexpected_presence",
                "No verdict from agents/people. An unexpected presence is a body, and what "
                "makes a perturbation a body is the respiration signature. Without it this "
                "agent has nothing to reason over.",
            )

        bodies = sorted(
            {
                a.zone_scope
                for a in people.assertions
                if a.field == "people.personhood" and a.value == "living_body"
            }
        )
        residents = self._roster.residents()
        associated = self._roster.associated_devices()
        home = [r for r in residents if any(d in associated for d in r.device_ids)]
        unaccounted = max(0, len(bodies) - len(home))

        provenance = Provenance(
            # Device arithmetic over another agent's verdict. Derived, not
            # measured, and labelled as such so nothing downstream can present
            # it as a sensor reading.
            source=Source.AGENT_INFERENCE,
            producer=self.identity.name,
            ansname=self.identity.ansname,
            detail=f"{len(bodies)} bodies, {len(home)} residents home, {len(associated)} devices",
        )

        assertions: list[Assertion] = []
        unknowns: list[Unknown] = []

        # ------------------------------------------------------- track lifecycle

        if unaccounted > 0:
            if self._track is None:
                self._track = _Track(
                    opened_tick=self._tick_count, zones=tuple(bodies), unaccounted=unaccounted
                )
            else:
                self._track.zones = tuple(bodies)
                self._track.unaccounted = unaccounted
                self._track.clear_ticks = 0
        elif self._track is not None:
            self._track.clear_ticks += 1
            if self._track.clear_ticks >= CLEAR_TICKS_TO_DROP:
                self._track = None

        # ------------------------------------------------------- the assertions

        holes = (
            "The rule misses a resident who left their phone in the car, a guest, and "
            "anyone carrying a device that never associates to this router."
        )

        if self._track is None:
            assertions.append(
                Assertion(
                    field="intruder.unexpected_presence",
                    value="false",
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=0.7,
                    basis=(
                        f"{len(bodies)} resolved breathing presence(s) against {len(home)} "
                        f"resident(s) with an associated device. Nothing unaccounted. {holes}"
                    ),
                    provenance=provenance,
                )
            )
            return self.observe(
                assertions=tuple(assertions),
                unknowns=tuple(unknowns),
                note=f"{len(bodies)} bodies, {len(home)} accounted",
            )

        held_s = (self._tick_count - self._track.opened_tick) * self.interval_s
        assertions.append(
            Assertion(
                field="intruder.unexpected_presence",
                value="true",
                # ACTIONABLE, not DISPATCHABLE. This agent informs; it does not
                # dial, and nothing in Hawk Eye does. A human tap is what
                # releases agents/caller. Capped further when the personhood
                # verdict underneath it was not verified.
                severity_ceiling=(
                    Severity.ACTIONABLE if upstream_verified else Severity.CORROBORATING
                ),
                confidence=(0.75 if len(home) == 0 else 0.6) if upstream_verified else 0.3,
                basis=(
                    f"{len(bodies)} body/bodies resolved by respiration signature against "
                    f"{len(home)} resident(s) with a device associated to the router: "
                    f"{self._track.unaccounted} body/bodies with no corresponding device. "
                    f"Held continuously for {held_s:.0f}s. {holes}"
                    + (
                        ""
                        if upstream_verified
                        else (
                            " The personhood verdict underneath this did NOT arrive over a "
                            "verified transport, so this is capped at corroboration and must "
                            "not be the basis for sending anyone."
                        )
                    )
                ),
                provenance=provenance,
            )
        )
        assertions.append(
            Assertion(
                field="intruder.basis",
                value="roster_device_association",
                severity_ceiling=Severity.INFORMATIONAL,
                confidence=1.0,
                basis=(
                    "The household is configuration, not a discovery problem. An unexpected "
                    "presence is a body that no registered device accounts for. This is not "
                    "recognition: we do not identify people and cannot."
                ),
                provenance=provenance,
            )
        )

        # ------------------------------------------- which zone, and when not to say

        if not home and len(bodies) == 1:
            # The clean case, and the one in the classification table: house
            # registered empty, one body inside. There is nothing to confuse it
            # with, so the zone is attributable.
            assertions.append(
                Assertion(
                    field="intruder.intruder_zone",
                    value=bodies[0],
                    zone_scope=bodies[0],
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=0.8,
                    basis=(
                        "No resident device is associated to the router and exactly one "
                        "breathing presence is resolved, so this zone is the unaccounted body. "
                        "No occupants are known to be at risk."
                    ),
                    provenance=provenance,
                )
            )
        else:
            # The dangerous case: someone is home and did not expect company.
            # We know there is an extra body and we cannot say which one it is.
            # Saying so is better than guessing, and the list of occupied zones
            # is what an officer actually needs.
            unknowns.append(
                Unknown(
                    field="intruder.intruder_zone",
                    reason=(
                        "Residents are also in the building. Without re-identification there "
                        "is no way to say which resolved presence is the unaccounted one, and "
                        "guessing would send officers to the wrong room. Every occupied zone "
                        "is reported instead."
                    ),
                )
            )
            assertions.append(
                Assertion(
                    field="intruder.occupied_zones",
                    value=",".join(bodies),
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=0.7,
                    basis=(
                        f"Breathing presences resolved in: {', '.join(bodies) or 'none'}. One "
                        "of these is unaccounted for by device association. Which one cannot "
                        "be determined and is not guessed."
                    ),
                    provenance=provenance,
                )
            )

        # Resident zones, where agents/people resolved them. This is the separation
        # that matters: where the intruder is and where the resident is, tracked
        # apart, is the answer responding officers need and the thing no other
        # product gives them.
        resident_zones = sorted(
            {a.value for a in people.assertions if a.field == "people.zone"}
        )
        if resident_zones:
            assertions.append(
                Assertion(
                    field="intruder.resident_zones",
                    value=",".join(resident_zones),
                    severity_ceiling=Severity.CORROBORATING,
                    confidence=0.6,
                    basis=(
                        f"{len(home)} resident(s) are home by device association and "
                        f"presences are resolved in {', '.join(resident_zones)}. Zones are "
                        "room-level; which specific person is in which room is not known."
                    ),
                    provenance=provenance,
                )
            )
        else:
            unknowns.append(
                Unknown(
                    field="intruder.resident_zones",
                    reason=(
                        "agents/people has not resolved a zone for any resident, so there "
                        "is no room to send officers to. Knowing where the residents are "
                        "not is not the same as knowing where they are."
                    ),
                )
            )

        return self.observe(
            assertions=tuple(assertions),
            unknowns=tuple(unknowns),
            note=f"track held {held_s:.0f}s, {self._track.unaccounted} unaccounted",
        )
