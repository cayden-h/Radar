"""A resident pointing at a person on the feed and saying "they are with me".

**This is not authentication and the name matters.** Nothing here verifies a
credential, and `vision` cannot tell you who anybody is. What is recorded is
that a human looked at a box on a screen and vouched for the person inside it.
Calling it authentication would put the one unbacked claim in a project whose
argument is that it never makes any, so the word does not appear.

## Why the ledger is here and not in master

`models/camera.py` states the rule this follows: a `track_id` is a rendering
detail that arrives at camera frame rate, not a claim. The hub is the only
process that ever sees one - `agents/vision` posts boxes here and nowhere else -
so the bookkeeping that is *keyed to* a track id belongs here too.

What crosses to `master` is the thing that is actually a claim: that the
resident has vouched for N people, by name, at a time. Master holds that,
subtracts it when it classifies, and seals it into the record. It never learns a
box id, which is what keeps geometry out of the trust boundary.

## The hole, stated where it is implemented

BoT-SORT can hand a **different** person a recycled track id inside the grace
window, and that person inherits the vouch. That is real and it is why
`GRACE_S` is a minute rather than an hour. A vouch is a human pointing at a box,
keyed to a tracker id, and it is never an identity claim - the basis text that
reaches master says exactly that so it cannot be repeated as something stronger.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from hawkeye_backend.models.camera import PersonVouch
from hawkeye_backend.models.common import utc_now

#: How long a vouch outlives the track it was made against.
#:
#: A person who steps behind a sofa must not become an intruder, and BoT-SORT's
#: ReID buffer usually hands back the same id across a gap that short. Past this
#: the vouch lapses and the person is unaccounted again, which is the honest
#: answer: nothing here recognises anybody, so a vouch cannot outlive the
#: tracker's own continuity by much without becoming a claim about identity.
GRACE_S = 60.0


class VouchLedger:
    """Who the resident has vouched for, keyed to the box they pointed at.

    Pure and clock-injected. Nothing in here does I/O, so the grace window is
    testable without sleeping and the whole lifecycle is exercised in
    milliseconds.
    """

    def __init__(self, grace_s: float = GRACE_S) -> None:
        self._grace = timedelta(seconds=grace_s)
        self._vouches: dict[int, PersonVouch] = {}

    # --------------------------------------------------------------- mutation

    def vouch(self, track_id: int, name: str, *, now: datetime | None = None) -> PersonVouch:
        """Record that the resident vouched for whoever is in this box.

        Re-vouching an id replaces the name rather than raising. Correcting a
        typo must not require a revoke first: the resident is looking at a live
        feed, and a two-step correction is a two-step mistake.
        """
        at = now or utc_now()
        vouch = PersonVouch(
            track_id=track_id,
            name=name.strip(),
            vouched_at=at,
            last_seen_at=at,
            held=True,
        )
        self._vouches[track_id] = vouch
        return vouch

    def revoke(self, track_id: int) -> PersonVouch | None:
        """Take a vouch back. Returns what was removed, or None if nothing was.

        Undoing must be one gesture. Tapping the wrong box is the most likely
        mistake a resident will make on this screen, and a mistake that needs a
        confirmation dialog to undo is one people live with instead.
        """
        return self._vouches.pop(track_id, None)

    def observe(self, track_ids: frozenset[int], *, now: datetime | None = None) -> None:
        """Take the ids the tracker is currently holding, and age off the rest.

        Called from the boxes path, so it runs at detector rate. An id present
        here has its clock reset; an id absent for longer than the grace window
        is dropped entirely.

        An empty set is meaningful and is handled as such: it means the detector
        looked and found nobody, which starts every held vouch's grace window
        rather than clearing them - see `GRACE_S`.
        """
        at = now or utc_now()
        for track_id, vouch in list(self._vouches.items()):
            if track_id in track_ids:
                self._vouches[track_id] = vouch.model_copy(
                    update={"last_seen_at": at, "held": True}
                )
            elif at - vouch.last_seen_at > self._grace:
                del self._vouches[track_id]
            elif vouch.held:
                self._vouches[track_id] = vouch.model_copy(update={"held": False})

    # ---------------------------------------------------------------- reading

    def active(self, *, now: datetime | None = None) -> tuple[PersonVouch, ...]:
        """Every vouch that has not lapsed, newest last.

        Expiry is evaluated on read as well as on `observe`, so a hub whose
        camera link dropped does not serve vouches that should have lapsed
        while no boxes were arriving to age them off.
        """
        at = now or utc_now()
        live = [v for v in self._vouches.values() if at - v.last_seen_at <= self._grace]
        return tuple(sorted(live, key=lambda v: v.vouched_at))

    def get(self, track_id: int) -> PersonVouch | None:
        return self._vouches.get(track_id)
