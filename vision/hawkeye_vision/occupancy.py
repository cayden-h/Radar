"""Is there a person in frame, or is this a curtain.

The one question the camera is allowed to answer for the shutter decision.

It is deliberately not a count and deliberately not an identity. `track.py`
states that a track id says "the same person as a moment ago", never "this
particular person", and there is no enrolment and no database to check against.
A count would invite the reader to treat it as headcount, which is the claim the
2026-09-19 pivot deleted for being unsupportable.

Three values, not two. "I looked and saw nobody" and "I could not look" are
different facts, and collapsing them is how a blind camera closes a shutter and
looks like it is working.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from hawkeye_vision.track import Detection


class Occupancy(StrEnum):
    """What the camera can say about whether a human is present."""

    NO_PERSON = "no_person"
    PERSON_PRESENT = "person_present"
    TRACKER_UNAVAILABLE = "tracker_unavailable"


def verdict(detections: Sequence[Detection], *, tracker_available: bool) -> Occupancy:
    """The occupancy verdict for one frame's detections.

    `tracker_available` is checked first and unconditionally. A tracker that
    reports itself unavailable is not believed even if it produced boxes,
    because the boxes then have no provenance we can describe.
    """
    if not tracker_available:
        return Occupancy.TRACKER_UNAVAILABLE
    return Occupancy.PERSON_PRESENT if detections else Occupancy.NO_PERSON
