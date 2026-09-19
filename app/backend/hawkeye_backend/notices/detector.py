"""The trigger rule for an unexpected-presence notice.

Pure and synchronous. No clock, no socket, no I/O: time comes from
`state.captured_at`, so the rule is deterministic, testable without sleeping,
and correct when a capture is replayed rather than live.

The rule is deliberately conservative in the same direction everything else in
this project is. A notice is unrecallable once it is an SMS on someone's phone.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.notice import Notice, NoticeSeverity
from hawkeye_backend.models.state import InteriorState, Presence, PresenceState

logger = logging.getLogger(__name__)

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
    """The name a resident reads, falling back to a derived name rather than to ''.

    Zones are a closed set fixed at enrollment, so hitting the fallback means
    something is genuinely wrong upstream (a zone renamed or dropped from the
    floorplan without the sensing side catching up). A resident reading a
    guessed room name during a real incident is the same category of problem
    as a fabricated measurement, so the fallback is logged rather than silent.
    """
    for room in state.floorplan.rooms:
        if room.zone == zone:
            return room.name
    logger.warning(
        "zone %r is not in the enrolled floorplan for site %r; "
        "falling back to a derived room name",
        zone,
        state.site_id,
    )
    return zone.replace("_", " ").capitalize()


class NoticeDetector:
    """Decides when an unexpected presence becomes a notice.

    Fires when, all at once:

    1. A presence is a confirmed person with `expected is False`.
    2. It has held that way continuously for `hold_s`.
    3. `calibration.healthy` is true.
    4. No notice has yet been raised for that `presence_id` since it was last
       seen qualifying within `forget_after_s`.

    Once per presence, while it is here - not once per `presence_id`, ever.
    `presence_id` is session-scoped (see `Presence.presence_id`) and can be
    recycled after a sensor restart, and a genuine re-entry hours after the
    same person left must notify again. A fired mark is therefore forgotten
    once the presence has been absent for `forget_after_s`; if it, or a
    different person reusing the same id, appears after that it is a new
    event.
    """

    def __init__(
        self,
        hold_s: float = 5.0,
        forget_after_s: float = 900.0,
        is_suppressed: Callable[[str], bool] | None = None,
    ) -> None:
        if hold_s < 0 or forget_after_s < 0:
            raise ValueError("hold_s and forget_after_s must not be negative")
        self.hold_s = hold_s
        self.forget_after_s = forget_after_s
        self._since: dict[str, datetime] = {}
        # Last seen "qualifying" timestamp for every presence_id that has
        # fired, so a mark can lapse. Refreshed on every tick the id still
        # qualifies, whether or not it has already fired.
        self._fired: dict[str, datetime] = {}
        # A resident saying "this person is fine" is a human override of a
        # machine inference, and it only ever lowers an alarm. Consulted here
        # rather than filtered downstream so an approved presence never starts a
        # hold at all, and approving mid-hold stops the notice.
        self._is_suppressed = is_suppressed

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

        # A presence gone long enough is gone. Forget its fired mark so a
        # genuine re-entry (or a recycled id) notifies again rather than being
        # suppressed forever.
        for presence_id in list(self._fired):
            last_seen = self._fired[presence_id]
            if (now - last_seen).total_seconds() > self.forget_after_s:
                del self._fired[presence_id]

        # `presence_id` is assumed unique within a single frame; if two shared
        # one, only the last would survive this comprehension.
        qualifying = {p.presence_id: p for p in state.presences if _is_unexpected(p)}

        if self._is_suppressed is not None:
            qualifying = {
                pid: p for pid, p in qualifying.items() if not self._is_suppressed(pid)
            }

        # A presence that stopped qualifying, or left the frame entirely,
        # restarts from zero if it comes back. It does not lose its fired mark
        # (that is handled above, on a longer timescale).
        for presence_id in list(self._since):
            if presence_id not in qualifying:
                del self._since[presence_id]

        raised: list[Notice] = []
        for presence_id, p in qualifying.items():
            if presence_id in self._fired:
                self._fired[presence_id] = now
                continue
            first = self._since.setdefault(presence_id, now)
            if (now - first).total_seconds() < self.hold_s:
                continue
            self._fired[presence_id] = now
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
            room=room,
            presence_id=p.presence_id,
            raised_at=state.captured_at,
            provenance=INTRUDER_PROVENANCE,
        )
