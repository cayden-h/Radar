"""The trigger rule for an unexpected-presence notice.

Pure and synchronous. No clock, no socket, no I/O: time comes from
`state.captured_at`, so the rule is deterministic, testable without sleeping,
and correct when a capture is replayed rather than live.

The rule is deliberately conservative in the same direction everything else in
this project is. A notice is unrecallable once it is an SMS on someone's phone.
"""

from __future__ import annotations

from datetime import datetime

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.notice import Notice, NoticeSeverity
from hawkeye_backend.models.state import InteriorState, Presence, PresenceState

# agents/intruder decides this from roster plus device association, which is an
# inference over other readings rather than a measurement. DERIVED is the honest
# class and the one `Source.AGENT_INFERENCE` maps to.
INTRUDER_PROVENANCE = Provenance(
    source=Source.AGENT_INFERENCE,
    producer="agents/intruder",
    detail="presence surplus against roster and device association",
)

_PERSON_STATES = frozenset({PresenceState.CONFIRMED_MOVING, PresenceState.CONFIRMED_STILL})

# Where the verification gate is, since it is not in this file.
#
# A notice is derived from `Presence.expected`, which arrives in interior state
# from `agents/master`. Master is the trust boundary: an intruder claim that
# fails verification never becomes `expected: False` in the first place, so a
# notice cannot outrun the verification of the claim under it.
#
# That is the same reason this module does no verification of its own. Adding a
# second, weaker check here would suggest the hub is a trust boundary too, and
# it is not - it is on the human side of the line.


def _is_unexpected(p: Presence) -> bool:
    """A confirmed person the system did not expect to be in the building.

    `expected` is orthogonal to `state`, not a fourth state. Personhood is
    consumed first: a perturbation with no respiration signature is a curtain,
    and calling the police on a curtain is the failure this guards against.

    `None` means not yet decided, and must never make an intruder.
    """
    return p.state in _PERSON_STATES and p.expected is False


def _room_name(state: InteriorState, zone: str) -> str:
    """The name a resident reads, falling back to the raw key rather than to ''."""
    for room in state.floorplan.rooms:
        if room.zone == zone:
            return room.name
    return zone.replace("_", " ").capitalize()


class NoticeDetector:
    """Decides when an unexpected presence becomes a notice.

    Fires when, all at once:

    1. A presence is a confirmed person with `expected is False`.
    2. It has held that way continuously for `hold_s`.
    3. `calibration.healthy` is true.
    4. No notice has yet been raised for that `presence_id`.

    And then never again for that `presence_id`.
    """

    def __init__(self, hold_s: float = 5.0) -> None:
        self.hold_s = hold_s
        self._since: dict[str, datetime] = {}
        self._fired: set[str] = set()

    def observe(self, state: InteriorState) -> list[Notice]:
        """Feed one interior state tick. Returns the notices it raised, if any."""
        # A stale baseline invents presences, and escalation is already
        # suppressed upstream when it goes unhealthy. Drop every in-flight hold
        # rather than merely declining to fire: the hold must be `hold_s` of
        # trustworthy observation, not `hold_s` of any observation at all.
        if not state.calibration.healthy:
            self._since.clear()
            return []

        now = state.captured_at
        qualifying = {p.presence_id: p for p in state.presences if _is_unexpected(p)}

        # A presence that stopped qualifying, or left the frame entirely,
        # restarts from zero if it comes back. It does not lose its fired mark.
        for presence_id in list(self._since):
            if presence_id not in qualifying:
                del self._since[presence_id]

        raised: list[Notice] = []
        for presence_id, p in qualifying.items():
            if presence_id in self._fired:
                continue
            first = self._since.setdefault(presence_id, now)
            if (now - first).total_seconds() < self.hold_s:
                continue
            self._fired.add(presence_id)
            self._since.pop(presence_id, None)
            raised.append(self._notice(state, p))
        return raised

    def _notice(self, state: InteriorState, p: Presence) -> Notice:
        room = _room_name(state, p.position.zone)
        return Notice(
            notice_id=f"ntc-{p.presence_id}",
            severity=NoticeSeverity.ATTENTION,
            title="Unexpected person",
            body=f"Not accounted for. {room}.",
            zone=p.position.zone,
            presence_id=p.presence_id,
            raised_at=state.captured_at,
            provenance=INTRUDER_PROVENANCE,
        )
