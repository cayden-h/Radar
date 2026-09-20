# Motion-Gated Shutter Implementation Plan

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CSI motion alone open the camera shutter, and make the camera's own personhood verdict close it again, removing the deleted body-count dependency that currently hard-fails `agents/intruder`.

**Architecture:** `master` gains two independent decisions instead of one chained one. Decision A issues a signed `open` grant on a perturbation claim from `presence`. Decision B issues a signed `close` grant when `vision` reports `no_person`. A refractory lock in `master` prevents servo oscillation. `intruder` stops reading the radio and reads `vision` plus the roster instead.

**Tech Stack:** Python 3.13, pydantic v2, pytest, Ed25519 via `cryptography`. Run tests with `cd agents && python3 -m pytest -q`.

**Design spec:** `docs/superpowers/specs/2026-09-20-motion-gated-shutter-design.md`

---

## Context an engineer needs before starting

**What already exists and must not be rebuilt:**

- `agents/agents/shutter/` is complete and tested, 22 tests, no hardware needed. `GrantEnvelope.action` already accepts `"open"` and `"close"`; `shutter.py:234` already maps action to angle. **Do not modify anything under `agents/agents/shutter/`** except two docstrings in Task 9.
- `vision/hawkeye_vision/track.py` has the `Tracker` Protocol, `StubTracker`, `YoloBotSortTracker`, and `TrackBook`. The detection pipeline is done.
- `agents/agents/core/ports.py` holds every seam as a `Protocol`. New seams go there.
- `agents/agents/core/identity.py` holds `ROSTER`, the single source of truth for agent identities. `identity(slug)` looks one up.

**What does not exist and this plan creates:**

- `master` has never issued a grant. `grep -rn "sign_grant" agents/` returns only `test_shutter.py` and the shutter package itself. The whole grant-issuing path is new.
- There is no `agents/agents/vision/`. The capture pipeline exists; the ANS agent wrapper does not.
- There is no `agents/tests/test_master.py`.

**Two facts that shape the tests:**

- `LocalMesh.fetch` always returns `envelope_verified=False`. Any test asserting verified-path behaviour must construct `FetchedObservation(observation=..., envelope_verified=True)` by hand.
- `Agent.tick()` is synchronous and takes no arguments. Every agent is testable by constructing it with fixtures and calling `tick()`. No event loop.

---

## File Structure

| File | Responsibility |
|---|---|
| `vision/hawkeye_vision/occupancy.py` | **Create.** Pure function: a frame's `Detection`s plus tracker availability to `no_person` / `person_present` / `tracker_unavailable` |
| `vision/tests/test_occupancy.py` | **Create.** Tests for the above |
| `agents/agents/core/identity.py` | **Modify.** Add the `vision` `AgentIdentity` to `ROSTER`; edit `intruder`'s `consumes` and `must_not_claim` |
| `agents/agents/vision/__init__.py` | **Create.** Package marker |
| `agents/agents/vision/agent.py` | **Create.** `VisionAgent`, emits `vision.occupancy` |
| `agents/tests/test_vision_agent.py` | **Create.** Tests for the above |
| `agents/agents/master/episode.py` | **Create.** `ShutterEpisode`, the refractory lock. Pure state machine, no I/O |
| `agents/agents/master/shutter_client.py` | **Create.** `ShutterClient` Protocol + `LocalShutterClient`. Builds, signs and presents grants |
| `agents/agents/master/agent.py` | **Modify.** Wire the two decisions into `tick` |
| `agents/tests/test_master.py` | **Create.** Episode, grant issuance, failure modes |
| `agents/agents/intruder/agent.py` | **Modify.** Read `vision` + roster, not `people` |
| `agents/tests/test_intruder.py` | **Modify.** Rewrite fixtures |
| `agents/agents/presence/` | **Rename** from `agents/agents/people/`. Delete `respiration.py` |
| `agents/agents/shutter/grant.py` | **Modify.** Two stale docstrings only |
| `docs/swapping-in-real-parts.md`, `docs/PIVOT.md`, `CLAUDE.md` | **Modify.** Task 10 |

**Task order is load-bearing.** Task 8 deletes `respiration.py`, which `intruder` depends on until Task 7 lands. Do not reorder.

---

## Task 1: The occupancy verdict, as a pure function

The camera's whole contribution to the close decision is one three-valued answer. It lives in the `vision` package, not the agent, so it can be tested with no agent, no mesh and no identity.

**Files:**
- Create: `vision/hawkeye_vision/occupancy.py`
- Test: `vision/tests/test_occupancy.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_occupancy.py`:

```python
"""The three-valued occupancy verdict.

`tracker_unavailable` is the interesting one. A tracker with no weights file
returns zero detections, which is indistinguishable from an empty room unless
the verdict carries the distinction explicitly. A blind camera that reads as
`no_person` would close the shutter and look like a working benign close.
"""

from __future__ import annotations

from hawkeye_vision.occupancy import Occupancy, verdict
from hawkeye_vision.track import BBox, Detection


def _det(track_id: int) -> Detection:
    return Detection(track_id=track_id, bbox=BBox(0.1, 0.1, 0.2, 0.4))


def test_no_detections_is_no_person() -> None:
    assert verdict([], tracker_available=True) is Occupancy.NO_PERSON


def test_one_detection_is_person_present() -> None:
    assert verdict([_det(1)], tracker_available=True) is Occupancy.PERSON_PRESENT


def test_many_detections_are_still_person_present() -> None:
    """The verdict is personhood, not a count. A count would be an identity claim."""
    assert verdict([_det(1), _det(2)], tracker_available=True) is Occupancy.PERSON_PRESENT


def test_unavailable_tracker_is_not_no_person() -> None:
    """The blind-camera case. Zero detections from a tracker that cannot see
    must never read as an empty room."""
    assert verdict([], tracker_available=False) is Occupancy.TRACKER_UNAVAILABLE


def test_unavailable_tracker_wins_over_detections() -> None:
    """A tracker that reports itself unavailable is not believed even if it
    somehow produced boxes."""
    assert verdict([_det(1)], tracker_available=False) is Occupancy.TRACKER_UNAVAILABLE
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/vision && python3 -m pytest tests/test_occupancy.py -v
```

Expected: `ModuleNotFoundError: No module named 'hawkeye_vision.occupancy'`

- [ ] **Step 3: Write minimal implementation**

Create `vision/hawkeye_vision/occupancy.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/vision && python3 -m pytest tests/test_occupancy.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run the whole vision suite to confirm nothing regressed**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/vision && python3 -m pytest -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add vision/hawkeye_vision/occupancy.py vision/tests/test_occupancy.py
git commit -m "Separate 'saw nobody' from 'could not look' in the occupancy verdict"
```

---

## Task 2: Give `vision` an ANS identity

An agent with no entry in `ROSTER` has no ANSName, no cards and cannot be fetched. This must land before the agent class, because `Agent.__init__` calls `identity(slug)` and raises on an unknown one.

**Files:**
- Modify: `agents/agents/core/identity.py` (add to `ROSTER`)
- Test: `agents/tests/test_cards.py` (existing suite covers every roster entry)

- [ ] **Step 1: Read the existing test to see what it demands of a new entry**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_cards.py -q
```

Expected: passes now. It iterates `ROSTER`, so a malformed new entry fails it.

- [ ] **Step 2: Write the failing test**

Add to `agents/tests/test_cards.py`:

```python
def test_vision_is_registered_and_scoped_to_one_room() -> None:
    """The camera sees one room. That limit is carried on the identity, not in
    a comment, so the published card states it too."""
    from agents.core.identity import identity

    vision = identity("vision")
    assert vision.role is Role.SENSING
    fields = {f for skill in vision.skills for f in skill.fields}
    assert "vision.occupancy" in fields
    assert any("identif" in claim.lower() for claim in vision.must_not_claim)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_cards.py::test_vision_is_registered_and_scoped_to_one_room -v
```

Expected: FAIL, `KeyError` or `ValueError` from `identity("vision")`

- [ ] **Step 4: Add the roster entry**

In `agents/agents/core/identity.py`, inside the `ROSTER` tuple, after the `intruder` entry and before `master`:

```python
    AgentIdentity(
        slug="vision",
        tier=1,
        role=Role.SENSING,
        summary="The camera. Whether a human is in frame, and a description of what they are doing.",
        question="Is there a person in this room, and what are they doing?",
        # TRANSACTIONAL, not FIDUCIARY. Its verdict retires a shutter grant and
        # feeds the intruder rule; it is never on its own the basis for telling
        # a dispatcher that a specific person is present.
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="occupancy",
                name="Occupancy verdict",
                description=(
                    "Whether a human being is in frame. Object detection, not "
                    "recognition: `person_present`, `no_person`, or "
                    "`tracker_unavailable` when the detector cannot see at all. "
                    "Scoped to the one room the fixed camera covers."
                ),
                fields=("vision.occupancy",),
            ),
        ),
        must_not_claim=(
            "That we identify anyone. Track identities are stable within a session "
            "only; a track id says 'the same person as a moment ago', never 'this "
            "particular person'. There is no enrolment and no database.",
            "A headcount. The verdict is personhood, not a count, because a count "
            "invites being read as occupancy, which the 2026-09-19 pivot deleted.",
            "Anything about a room the camera does not cover. One fixed camera sees "
            "one room and every claim carries that scope.",
            "That an empty frame means an empty room when the tracker is unavailable. "
            "A detector with no weights returns zero detections and that is not "
            "evidence of absence.",
        ),
        consumes=(),
    ),
```

- [ ] **Step 5: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_cards.py -v
```

Expected: all pass, including the new one

- [ ] **Step 6: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/core/identity.py agents/tests/test_cards.py
git commit -m "Register vision, with the limits it must never exceed on its card"
```

---

## Task 3: The `VisionAgent`

**Files:**
- Create: `agents/agents/vision/__init__.py`, `agents/agents/vision/agent.py`
- Create: `agents/tests/test_vision_agent.py`

- [ ] **Step 1: Write the failing test**

Create `agents/tests/test_vision_agent.py`:

```python
"""The ANS wrapper over the camera pipeline.

Runs entirely on `StubTracker`. No weights, no camera, no MPS backend - the
same rule `StubShutter` follows, because the demo must never depend on hardware
being alive.
"""

from __future__ import annotations

import pytest
from hawkeye_backend.models.common import Source
from hawkeye_vision.occupancy import Occupancy

from agents.vision.agent import VisionAgent

ROOM = "living_room"


class _FakeSource:
    """Stands in for the capture loop: hands over one frame's verdict."""

    def __init__(self, verdict: Occupancy) -> None:
        self._verdict = verdict

    def occupancy(self) -> Occupancy:
        return self._verdict


def _agent(verdict: Occupancy) -> VisionAgent:
    return VisionAgent(_FakeSource(verdict), room=ROOM)


def test_no_person_is_asserted_and_scoped() -> None:
    obs = _agent(Occupancy.NO_PERSON).tick()
    (assertion,) = [a for a in obs.assertions if a.field == "vision.occupancy"]
    assert assertion.value == "no_person"
    assert assertion.zone_scope == ROOM


def test_person_present_is_asserted() -> None:
    obs = _agent(Occupancy.PERSON_PRESENT).tick()
    assert obs.value("vision.occupancy") == "person_present"


def test_unavailable_tracker_asserts_nothing_and_says_why() -> None:
    """A blind camera must not produce an occupancy assertion at all. An
    assertion of `tracker_unavailable` would still be a value that a careless
    consumer could compare against, so it goes in `unknowns` instead."""
    obs = _agent(Occupancy.TRACKER_UNAVAILABLE).tick()
    assert obs.value("vision.occupancy") is None
    (unknown,) = [u for u in obs.unknowns if u.field == "vision.occupancy"]
    assert "could not look" in unknown.reason.lower()


def test_provenance_is_a_sensor_reading_not_an_inference() -> None:
    """The camera measured this. It must not be labelled as derived, and it
    must not be labelled as simulated when a real tracker produced it."""
    obs = _agent(Occupancy.NO_PERSON).tick()
    (assertion,) = [a for a in obs.assertions if a.field == "vision.occupancy"]
    assert assertion.provenance.source is Source.SENSOR
    assert assertion.provenance.producer == "vision"


@pytest.mark.parametrize("verdict", list(Occupancy))
def test_every_verdict_keeps_the_agent_healthy(verdict: Occupancy) -> None:
    """An unavailable tracker is a fact to report, not a crash."""
    assert _agent(verdict).tick().healthy is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_vision_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.vision'`

- [ ] **Step 3: Check how `Source` is spelled before implementing**

```bash
grep -n "class Source" -A 12 app/backend/hawkeye_backend/models/common.py
```

Use whichever member names the enum actually defines. If there is no `SENSOR` member, use the one the CSI path uses for a direct measurement and adjust the test in Step 1 to match. Do not invent a member.

- [ ] **Step 4: Write the implementation**

Create `agents/agents/vision/__init__.py`:

```python
"""agents/vision - the camera, behind an ANS identity."""

from agents.vision.agent import VisionAgent

__all__ = ["VisionAgent"]
```

Create `agents/agents/vision/agent.py`:

```python
"""agents/vision - is there a person in this room.

The camera answers personhood. That is the question the radio used to answer
with a respiration signature, and which the 2026-09-19 pivot deleted for being
unsupportable on a 1x1 link. It does not answer identity, because identity needs
enrolment and a database we deliberately do not have.

This agent is thin on purpose. Detection, tracking, lighting and recording all
live in `vision/hawkeye_vision/`, which has its own test suite. What is here is
the ANS surface: an identity, a scope, a provenance label, and the distinction
between not seeing anybody and not being able to see.

**The scope is carried in the data.** One fixed camera sees one room, and every
assertion carries that room in `zone_scope`. Root CLAUDE.md requires that a
scoped claim must not be presentable as an unscoped one by accident, and a field
on the assertion is the only version of that which survives being passed around.
"""

from __future__ import annotations

from typing import Protocol

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity
from hawkeye_vision.occupancy import Occupancy

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion, Unknown


class OccupancySource(Protocol):
    """The capture loop, reduced to the one question this agent asks it."""

    def occupancy(self) -> Occupancy:
        """The verdict for the most recent frame."""
        ...


class VisionAgent(Agent):
    """Personhood from the camera, scoped to the one room it covers."""

    interval_s = 1.0

    def __init__(self, source: OccupancySource, *, room: str) -> None:
        super().__init__(identity("vision"))
        self._source = source
        self._room = room

    def tick(self) -> AgentObservation:
        verdict = self._source.occupancy()

        if verdict is Occupancy.TRACKER_UNAVAILABLE:
            # Deliberately not an assertion. `tracker_unavailable` as a *value*
            # is something a careless consumer can compare against and get a
            # truthy answer from; an unknown cannot be mistaken for a reading.
            return AgentObservation(
                agent=self.identity.name,
                ansname=self.identity.ansname,
                unknowns=(
                    Unknown(
                        field="vision.occupancy",
                        zone_scope=self._room,
                        reason=(
                            "The detector could not look: no weights loaded or no frames "
                            "arriving. Zero detections from a blind camera is not evidence "
                            "that the room is empty."
                        ),
                    ),
                ),
            )

        return AgentObservation(
            agent=self.identity.name,
            ansname=self.identity.ansname,
            assertions=(
                Assertion(
                    field="vision.occupancy",
                    value=verdict.value,
                    zone_scope=self._room,
                    severity_ceiling=Severity.ACTIONABLE,
                    confidence=0.9,
                    basis=(
                        f"Object detection over the {self._room} camera. Personhood only: "
                        "this says a human is in frame, never which human, and never how "
                        "many."
                    ),
                    provenance=Provenance(
                        source=Source.SENSOR,
                        producer=self.identity.name,
                        ansname=self.identity.ansname,
                        detail=f"camera:{self._room}",
                    ),
                ),
            ),
        )
```

- [ ] **Step 5: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_vision_agent.py -v
```

Expected: 7 passed. If `Severity.ACTIONABLE` or `Source.SENSOR` do not exist, fix to the real member names found in Step 3 rather than adding members.

**Scope boundary, stated so nobody thinks it was forgotten.**

`VisionAgent` depends on an `OccupancySource` Protocol, and this plan supplies only the fake one in the tests. The adapter that runs the real capture loop - pull a `Frame`, call `Tracker.update`, feed `TrackBook`, call `verdict()` with the live detections and `Tracker.available` - is **not** built here. It belongs with the capture loop in `vision/hawkeye_vision/`, it needs a camera to exercise honestly, and building it blind would produce untested glue at exactly the seam that matters.

Task 10 Step 5 adds it to `TASKS.md`. Everything in this plan is testable and demoable without it, via `StubTracker` and the mock path.

- [ ] **Step 6: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/vision agents/tests/test_vision_agent.py
git commit -m "Wrap the camera in an ANS identity that reports personhood and nothing more"
```

---

## Task 4: The refractory lock, as a pure state machine

A benign close at tick T followed by a re-open at T+1 oscillates the servo at 1 Hz. The SG92R stalls over 700mA and `docs/hardware/servo-sg92r.md` records that this browns out the Pi. This is the test that protects the physical demo, so the state machine is separated from all I/O in order to be exhaustively testable.

**Files:**
- Create: `agents/agents/master/episode.py`
- Create: `agents/tests/test_master.py`

- [ ] **Step 1: Write the failing test**

Create `agents/tests/test_master.py`:

```python
"""master's shutter decisions.

The refractory lock is the test that protects the physical demo: an oscillating
SG92R stalls over 700mA and browns out the Pi.
"""

from __future__ import annotations

from agents.master.episode import CLEAR_TICKS_TO_RELEASE, ShutterEpisode

ROOM = "living_room"


def test_motion_on_a_closed_shutter_opens_it() -> None:
    episode = ShutterEpisode()
    assert episode.on_motion(ROOM) is True


def test_motion_while_already_open_does_not_re_open() -> None:
    """Re-issuing an open grant for an already-open lens is a wasted servo
    command and a wasted nonce."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    assert episode.on_motion(ROOM) is False


def test_benign_close_locks_out_immediate_re_open() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion(ROOM) is False


def test_lock_releases_after_enough_clear_ticks() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is True


def test_motion_during_the_lock_restarts_the_clear_count() -> None:
    """A fan that keeps tripping motion must never accumulate clear ticks
    between gusts and slip past the lock."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False  # still locked, and this resets it
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False


def test_the_lock_is_per_room() -> None:
    """A locked living room must not suppress an open for the kitchen."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion("kitchen") is True


def test_motion_flood_is_bounded() -> None:
    """The brownout guard. 500 ticks of unbroken motion must produce a small,
    bounded number of open commands, not one per tick."""
    episode = ShutterEpisode()
    opens = 0
    for _ in range(500):
        if episode.on_motion(ROOM):
            opens += 1
            episode.opened(ROOM)
            episode.closed(ROOM)
    assert opens == 1, f"servo commanded {opens} times under continuous motion"


def test_suppression_reason_is_reportable() -> None:
    """A suppressed open is evidence, not a gap. master puts this string in the
    discard feed so the replay console shows the suppression."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    episode.on_clear(ROOM)
    episode.on_motion(ROOM)
    reason = episode.suppression_reason(ROOM)
    assert reason is not None
    assert str(CLEAR_TICKS_TO_RELEASE) in reason
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.master.episode'`

- [ ] **Step 3: Write the implementation**

Create `agents/agents/master/episode.py`:

```python
"""The refractory lock: what stops the shield oscillating.

Motion opens the lens and the camera's own verdict closes it again. Those two
rules alone oscillate: a resident walks through, the camera sees a person, they
leave frame, the lens closes, and the next motion tick re-opens it while they
are still in the room.

That is not a cosmetic bug. The SG92R stalls over 700mA and
`docs/hardware/servo-sg92r.md` records that this browns out the Pi, which means
an oscillating shutter is the demo dying on stage.

**This lives in `master` and not in `shutter`.** `shutter` must stay a thing
that verifies a grant and moves. Giving it an opinion about whether it should
have been asked makes it a second policy engine, which is what the pivot
rejected when it rejected folding `shutter` into `vision`. Keeping the bound
here also keeps it testable with no hardware.

It is a pure state machine: no clock, no I/O, no grants. Every transition is a
method call, which is what lets the flood case be tested over 500 ticks in
microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto

#: Consecutive motion-free ticks before a benign close stops suppressing an
#: open. The same constant and the same reasoning as `CLEAR_TICKS_TO_DROP` in
#: `agents/intruder`: a state that flickers off and back a second later is worse
#: than no state at all.
CLEAR_TICKS_TO_RELEASE = 10


class _State(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    LOCKED = auto()


@dataclass
class _Room:
    state: _State = _State.CLOSED
    clear_ticks: int = 0
    suppressed: bool = False


@dataclass
class ShutterEpisode:
    """Per-room shutter state, and the lock that bounds servo commands."""

    _rooms: dict[str, _Room] = field(default_factory=dict)

    def _room(self, room: str) -> _Room:
        return self._rooms.setdefault(room, _Room())

    def on_motion(self, room: str) -> bool:
        """Motion was reported in `room`. True if master should open the lens.

        Any motion resets the clear count, including motion that is itself
        suppressed. A fan that trips motion every few seconds must never
        accumulate clear ticks between gusts and slip past the lock.
        """
        entry = self._room(room)
        entry.clear_ticks = 0

        if entry.state is _State.CLOSED:
            entry.suppressed = False
            return True

        entry.suppressed = entry.state is _State.LOCKED
        return False

    def on_clear(self, room: str) -> None:
        """A tick with no motion in `room`."""
        entry = self._room(room)
        if entry.state is not _State.LOCKED:
            return
        entry.clear_ticks += 1
        if entry.clear_ticks >= CLEAR_TICKS_TO_RELEASE:
            entry.state = _State.CLOSED
            entry.clear_ticks = 0
            entry.suppressed = False

    def opened(self, room: str) -> None:
        """`shutter` attested open."""
        entry = self._room(room)
        entry.state = _State.OPEN
        entry.suppressed = False

    def closed(self, room: str) -> None:
        """`shutter` attested closed after a benign verdict. Starts the lock."""
        entry = self._room(room)
        entry.state = _State.LOCKED
        entry.clear_ticks = 0

    def is_open(self, room: str) -> bool:
        return self._room(room).state is _State.OPEN

    def suppression_reason(self, room: str) -> str | None:
        """Why the last open was suppressed, for the discard feed.

        A suppressed open is evidence rather than a gap, so it is reportable in
        the same place `TrustGate` reports everything else it refused.
        """
        entry = self._room(room)
        if not entry.suppressed:
            return None
        return (
            f"open suppressed in {room}: benign close is still holding, "
            f"{entry.clear_ticks} clear ticks of {CLEAR_TICKS_TO_RELEASE}"
        )
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/master/episode.py agents/tests/test_master.py
git commit -m "Bound servo commands under continuous motion so the Pi cannot brown out"
```

---

## Task 5: The grant-issuing client

`master` has never issued a grant. This builds the path: ask `shutter` for a nonce, build the envelope, sign it, present it.

**Files:**
- Create: `agents/agents/master/shutter_client.py`
- Test: append to `agents/tests/test_master.py`

- [ ] **Step 1: Read the existing grant construction in the shutter tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && sed -n '120,170p' tests/test_shutter.py
```

This shows exactly how a valid grant is built and signed. Mirror it - do not invent a second way.

- [ ] **Step 2: Write the failing test**

Append to `agents/tests/test_master.py`:

```python
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.master.shutter_client import GRANT_TTL, LocalShutterClient
from agents.shutter.agent import ShutterAgent


def _shutter() -> ShutterAgent:
    """A real ShutterAgent on the stub backend. No GPIO, no servo."""
    from agents.shutter.backend import StubShutter
    from agents.shutter.shutter import Shutter

    return ShutterAgent(Shutter(backend=StubShutter()))


def test_open_grant_moves_the_real_shutter() -> None:
    """End to end against the real gate: master signs, shutter verifies."""
    key = Ed25519PrivateKey.generate()
    shutter = _shutter()
    client = LocalShutterClient(shutter, key=key, issuer="master")

    attestation = client.request(action="open", reason="motion:c-1")

    assert attestation is not None
    assert attestation.position == "open"


def test_close_grant_moves_it_back() -> None:
    key = Ed25519PrivateKey.generate()
    shutter = _shutter()
    client = LocalShutterClient(shutter, key=key, issuer="master")
    client.request(action="open", reason="motion:c-1")

    attestation = client.request(action="close", reason="vision:v-9")

    assert attestation is not None
    assert attestation.position == "closed"


def test_a_grant_signed_by_the_wrong_key_is_refused() -> None:
    """The refusal path. This is the submission, so it is tested from master's
    side too and not only from the shutter's."""
    shutter = _shutter()
    client = LocalShutterClient(shutter, key=Ed25519PrivateKey.generate(), issuer="master")

    assert client.request(action="open", reason="motion:c-1") is None
    assert shutter.shutter.position == "closed"


def test_each_grant_gets_a_fresh_nonce() -> None:
    """A reused nonce is a replay. The client must ask for a new challenge per
    grant rather than caching one."""
    key = Ed25519PrivateKey.generate()
    shutter = _shutter()
    client = LocalShutterClient(shutter, key=key, issuer="master")

    client.request(action="open", reason="motion:c-1")
    client.request(action="close", reason="vision:v-1")

    assert len(client.nonces_used) == 2
    assert len(set(client.nonces_used)) == 2


def test_grant_ttl_is_seconds_not_minutes() -> None:
    """A grant that outlives the situation that produced it is a replay
    waiting to happen."""
    assert GRANT_TTL <= timedelta(seconds=30)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py -k shutter_client -v
```

Expected: `ModuleNotFoundError: No module named 'agents.master.shutter_client'`

If `ShutterAgent`'s constructor signature or `Shutter`'s differ from what Step 1 showed, fix the `_shutter()` helper to match the real one. Do not change `agents/agents/shutter/`.

- [ ] **Step 4: Write the implementation**

Create `agents/agents/master/shutter_client.py`:

```python
"""How master asks the shield to move.

A grant is not a claim. A claim says what is true; a grant says *do this*. A
claim that fails verification is discarded and the world is unchanged, and a
grant that fails verification is an attempt to move a physical object that did
not succeed. `agents/shutter/grant.py` states that distinction and this is the
other end of it.

**The nonce is not cached.** `shutter` issues a challenge, and the grant is
bound to it. Asking for a fresh one per grant is what makes a replayed grant
detectable, and holding one open across two grants would give an attacker a
window in which a captured grant is still live.

`LocalShutterClient` talks to a `ShutterAgent` in this process. It is the same
category of stand-in as `LocalMesh` and carries the same warning: an in-process
call verifies the signature but not the transport, and the architecture is two
independently registered agents over ANS. It exists so master's decision logic
can be written and tested before that transport is wired.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.shutter.agent import ShutterAgent
from agents.shutter.grant import GrantEnvelope, sign_grant
from agents.shutter.shutter import Attestation

#: How long a grant stays valid. Seconds, not minutes, per `grant.py`: a grant
#: that outlives the situation that produced it is a replay waiting to happen.
GRANT_TTL = timedelta(seconds=10)


class ShutterClient(Protocol):
    """Whatever moves the shield on master's behalf."""

    def request(self, *, action: str, reason: str) -> Attestation | None:
        """Ask for a move. `None` when the shutter refused."""
        ...


class LocalShutterClient:
    """In-process `ShutterClient`. Signs real grants against a real gate."""

    def __init__(
        self, shutter: ShutterAgent, *, key: Ed25519PrivateKey, issuer: str
    ) -> None:
        self._shutter = shutter
        self._key = key
        self._issuer = issuer
        self.nonces_used: list[str] = []

    def request(self, *, action: str, reason: str) -> Attestation | None:
        nonce = self._shutter.challenge()
        self.nonces_used.append(nonce)

        now = datetime.now(timezone.utc)
        envelope = GrantEnvelope(
            nonce=nonce,
            issuer=self._issuer,
            action=action,
            # Recorded, not trusted. It goes into the sealed record so an
            # investigator can follow the chain backwards; nothing downstream
            # reads it as authorization.
            reason=reason,
            issued_at=now,
            expires_at=now + GRANT_TTL,
        )
        signed = sign_grant(self._key, envelope)

        try:
            return self._shutter.shutter.open(signed)
        except Exception:
            # A refusal is an outcome, not an error. `shutter` has already
            # produced a signed refusal bound to the nonce, which is the record
            # that matters; master's job here is only to not move on.
            return None
```

- [ ] **Step 5: Reconcile with the real shutter API**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && grep -n "def challenge\|def _challenge\|def open\|class Attestation" agents/shutter/agent.py agents/shutter/shutter.py
```

`ShutterAgent._challenge` takes a params dict and returns a dict. If there is no public `challenge()`, either call the A2A method the way `test_shutter.py` does, or add a thin public `challenge()` on `ShutterAgent` that returns the nonce string. Adding that one accessor is the only permitted change to the shutter package in this task. Update the implementation above to match whatever the real signatures are, and narrow the bare `except Exception` to the actual refusal type (`GrantRefused`) once confirmed.

- [ ] **Step 6: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py tests/test_shutter.py -v
```

Expected: all pass, including the pre-existing 22 shutter tests

- [ ] **Step 7: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/master/shutter_client.py agents/tests/test_master.py agents/agents/shutter/agent.py
git commit -m "Give master a way to actually issue the grant it has always been credited with"
```

---

## Task 6: Wire the two decisions into `master.tick`

**Files:**
- Modify: `agents/agents/master/agent.py` (`SENSING` at line 55, `__init__` at 95, `tick` at 117)
- Test: append to `agents/tests/test_master.py`

- [ ] **Step 1: Write the failing test**

Append to `agents/tests/test_master.py`:

```python
from agents.core.observations import AgentObservation, Assertion
from agents.core.ports import FetchedObservation
from agents.master.agent import MasterAgent


class _Mesh:
    """An ObservationSource whose verification status the test controls."""

    def __init__(self) -> None:
        self._obs: dict[str, FetchedObservation] = {}

    def put(self, slug: str, obs: AgentObservation, *, verified: bool = True) -> None:
        self._obs[slug] = FetchedObservation(observation=obs, envelope_verified=verified)

    def drop(self, slug: str) -> None:
        self._obs.pop(slug, None)

    def fetch(self, slug: str) -> FetchedObservation | None:
        return self._obs.get(slug)


def _obs(slug: str, field: str, value: str) -> AgentObservation:
    from hawkeye_backend.models.common import Provenance, Source

    return AgentObservation(
        agent=f"agents/{slug}",
        ansname=f"ans://v0.1.0.{slug}.batradar.club",
        assertions=(
            Assertion(
                field=field,
                value=value,
                zone_scope=ROOM,
                confidence=0.9,
                basis="test fixture",
                provenance=Provenance(
                    source=Source.SENSOR,
                    producer=slug,
                    ansname=f"ans://v0.1.0.{slug}.batradar.club",
                    detail="test",
                ),
            ),
        ),
    )


def _master(mesh: _Mesh) -> tuple[MasterAgent, ShutterAgent]:
    shutter = _shutter()
    key = Ed25519PrivateKey.generate()
    client = LocalShutterClient(shutter, key=key, issuer="master")
    return MasterAgent(mesh, shutter_client=client), shutter


def test_motion_alone_opens_the_lens() -> None:
    """Decision A. No roster in this path at all."""
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, shutter = _master(mesh)

    master.tick()

    assert shutter.shutter.position == "open"


def test_no_person_closes_the_lens() -> None:
    """Decision B. The camera says the motion was not a person."""
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, shutter = _master(mesh)
    master.tick()

    mesh.put("vision", _obs("vision", "vision.occupancy", "no_person"))
    master.tick()

    assert shutter.shutter.position == "closed"


def test_person_present_keeps_the_lens_open() -> None:
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, shutter = _master(mesh)
    master.tick()

    mesh.put("vision", _obs("vision", "vision.occupancy", "person_present"))
    master.tick()

    assert shutter.shutter.position == "open"


def test_silent_vision_keeps_the_lens_open() -> None:
    """Closing on silence lets an attacker blind the camera by killing one
    agent. Open-on-failure is the safe direction, because opening has already
    been paid for by a verified grant."""
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, shutter = _master(mesh)
    master.tick()

    mesh.drop("vision")
    for _ in range(5):
        master.tick()

    assert shutter.shutter.position == "open"


def test_unverified_no_person_does_not_close_the_lens() -> None:
    """An unverified claim cannot retire a verified grant's effect."""
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, shutter = _master(mesh)
    master.tick()

    mesh.put("vision", _obs("vision", "vision.occupancy", "no_person"), verified=False)
    master.tick()

    assert shutter.shutter.position == "open"


def test_a_long_vision_silence_raises_a_notice_for_the_resident() -> None:
    """There is no silence timeout, because a timeout is what an attacker who
    can kill vision wants. The condition is made loud instead."""
    mesh = _Mesh()
    mesh.put("presence", _obs("presence", "presence.perturbation", "true"))
    master, _ = _master(mesh)
    master.tick()
    mesh.drop("vision")

    for _ in range(30):
        obs = master.tick()

    assert obs.value("master.vision_silent") == "true"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py -k "lens or silent" -v
```

Expected: FAIL, `MasterAgent.__init__() got an unexpected keyword argument 'shutter_client'`

- [ ] **Step 3: Change `SENSING`**

In `agents/agents/master/agent.py` line 55:

```python
# `people` became `presence` and `vision` joined when the shutter stopped being
# gated on a body count the radio can no longer produce. See
# docs/superpowers/specs/2026-09-20-motion-gated-shutter-design.md.
SENSING = ("presence", "intruder", "vision")
```

- [ ] **Step 4: Extend `__init__`**

In `MasterAgent.__init__`, add the parameter and the state:

```python
    def __init__(
        self,
        mesh: ObservationSource,
        *,
        gas: GasSensor | None = None,
        profiles: dict[str, TrustProfile] | None = None,
        shutter_client: ShutterClient | None = None,
    ) -> None:
```

and at the end of the body:

```python
        # None in tests that only exercise classification. A master with no
        # shutter client simply never issues a grant, which is the correct
        # degenerate behaviour rather than a crash.
        self._shutter = shutter_client
        self._episode = ShutterEpisode()
        self._vision_silent_ticks = 0
```

Add the imports at the top of the file:

```python
from agents.master.episode import ShutterEpisode
from agents.master.shutter_client import ShutterClient
```

- [ ] **Step 5: Add the decision method and call it from `tick`**

Add this method to `MasterAgent`:

```python
    #: Ticks of vision silence, with the lens open, before the resident is told.
    #: Not a timeout: nothing closes on silence, because a silence timeout is
    #: precisely what an attacker who can kill `vision` wants. The condition is
    #: made loud and a human decides.
    VISION_SILENT_NOTICE_TICKS = 20

    def _drive_shutter(self, admitted: list[AdmittedClaim]) -> bool:
        """The two shutter decisions. Returns True if vision has gone silent
        with the lens open for long enough that the resident should be told.

        Only admitted claims reach here, so an unverified `no_person` has
        already been capped by the gate and cannot retire a verified grant.
        """
        if self._shutter is None:
            return False

        rooms = {a.assertion.zone_scope for a in admitted}
        notice = False

        for room in sorted(rooms):
            moving = any(
                a.assertion.field == "presence.perturbation"
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
```

In `tick`, after `gate, admitted, unreachable = self._gather()` and before `classify(...)`:

```python
        vision_silent = self._drive_shutter(admitted)
```

and in the `assertions` list that `tick` builds, append:

```python
        if vision_silent:
            assertions.append(
                Assertion(
                    field="master.vision_silent",
                    value="true",
                    zone_scope="site",
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
```

- [ ] **Step 6: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_master.py -v
```

Expected: all pass. `AdmittedClaim.spoken` is a property at `gate.py:91` - confirm it means what this code assumes (the claim survived the gate at a severity worth acting on) and adjust if not.

- [ ] **Step 7: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/master/agent.py agents/tests/test_master.py
git commit -m "Open the lens on motion, close it on the camera's own verdict"
```

---

## Task 7: `intruder` reads the camera, not the radio

**Files:**
- Modify: `agents/agents/intruder/agent.py`, `agents/agents/core/identity.py`
- Modify: `agents/tests/test_intruder.py`

- [ ] **Step 1: Read the current test file end to end**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && cat tests/test_intruder.py
```

Its fixtures build `people.personhood` observations. Every one of them changes to `vision.occupancy`. The track-lifecycle tests keep their shape.

- [ ] **Step 2: Write the failing tests**

Replace the fixture helper in `agents/tests/test_intruder.py` so it produces a vision observation, and add:

```python
def test_person_with_no_associated_device_is_unexpected() -> None:
    mesh = _mesh_with_vision("person_present")
    agent = IntruderAgent(_roster(residents=1, associated=()), mesh)
    assert agent.tick().value("intruder.unexpected_presence") == "true"


def test_person_with_an_associated_device_is_accounted_for() -> None:
    mesh = _mesh_with_vision("person_present")
    agent = IntruderAgent(_roster(residents=1, associated=("phone-1",)), mesh)
    assert agent.tick().value("intruder.unexpected_presence") == "false"


def test_no_person_is_never_an_intruder() -> None:
    mesh = _mesh_with_vision("no_person")
    agent = IntruderAgent(_roster(residents=1, associated=()), mesh)
    assert agent.tick().value("intruder.unexpected_presence") == "false"


def test_no_vision_verdict_is_blind_not_false() -> None:
    """Absence of a verdict is not evidence of absence. The agent reports that
    it could not decide rather than deciding there is nobody."""
    agent = IntruderAgent(_roster(residents=1, associated=()), _empty_mesh())
    obs = agent.tick()
    assert obs.value("intruder.unexpected_presence") is None
    assert any(u.field == "intruder.unexpected_presence" for u in obs.unknowns)


def test_basis_names_the_holes() -> None:
    """The rule's gaps get said out loud in the claim itself, because they are
    what a judge will ask about."""
    mesh = _mesh_with_vision("person_present")
    agent = IntruderAgent(_roster(residents=1, associated=()), mesh)
    basis = agent.tick().value("intruder.basis") or ""
    assert "phone" in basis.lower()
    assert "guest" in basis.lower()


def test_unverified_vision_caps_severity() -> None:
    """An unverified upstream verdict is still reported - the information is
    real and a resident should see it - but it must not be allowed to trigger a
    dispatch."""
    mesh = _mesh_with_vision("person_present", verified=False)
    agent = IntruderAgent(_roster(residents=1, associated=()), mesh)
    (assertion,) = [
        a for a in agent.tick().assertions if a.field == "intruder.unexpected_presence"
    ]
    assert assertion.severity_ceiling is Severity.CORROBORATING
```

- [ ] **Step 3: Run to verify they fail**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_intruder.py -v
```

Expected: failures - the agent still fetches `people`

- [ ] **Step 4: Rewrite the agent's input**

In `agents/agents/intruder/agent.py`, in `tick`, replace the `people` fetch and the body-count arithmetic:

```python
        fetched = self._mesh.fetch("vision")
        vision = fetched.observation if fetched is not None else None
        upstream_verified = bool(fetched and fetched.envelope_verified)

        if vision is None:
            return self.blind(
                "intruder.unexpected_presence",
                "No verdict from agents/vision. What makes a perturbation a person is the "
                "camera seeing one, and without that this agent has nothing to reason over. "
                "Absence of a verdict is not evidence that the room is empty.",
            )

        occupied = sorted(
            {
                a.zone_scope
                for a in vision.assertions
                if a.field == "vision.occupancy" and a.value == "person_present"
            }
        )
        residents = self._roster.residents()
        associated = self._roster.associated_devices()
        home = [r for r in residents if any(d in associated for d in r.device_ids)]
        unaccounted = len(occupied) if occupied and not home else 0
```

Update the `Provenance.detail` string on the next lines:

```python
            detail=f"{len(occupied)} rooms with a person, {len(home)} residents home, {len(associated)} devices",
```

and the `holes` string:

```python
        holes = (
            "The rule misses a resident who left their phone in the car, a guest, and "
            "anyone carrying a device that never associates to this router. The camera "
            "says a person is present; it never says which person."
        )
```

- [ ] **Step 5: Rewrite the module docstring**

The docstring at the top of `agents/agents/intruder/agent.py` describes CSI body counts and the four-line stage arithmetic. Replace the arithmetic block with:

```
    Camera:     a person in the living room
    Roster:     2 registered residents      (configuration, not discovery)
    Associated: 0 resident phones on the network
                -------------------------------------
                a person no device accounts for
```

and replace the paragraph beginning "**Personhood gates everything.**" with:

```
- **Personhood comes from the camera now.** A perturbation with no person in
  frame is a curtain, and calling police on a curtain is the failure mode this
  agent is designed against. Nothing here reads CSI; it reads the camera's
  verdict. The radio lost this job on 2026-09-19 when respiration sensing was
  cut, and the camera is a better answer to it: an officer can check the footage
  afterwards, which was never true of a breathing signature.
```

- [ ] **Step 6: Update the identity**

In `agents/agents/core/identity.py`, in the `intruder` entry: change `consumes=("people",)` to `consumes=("vision",)`, and replace the `must_not_claim` line beginning "An intruder without a personhood verdict from agents/people" with:

```python
            "An intruder without a verdict from agents/vision. A perturbation with no "
            "person in frame is a curtain, and calling police on a curtain is the "
            "failure mode.",
```

- [ ] **Step 7: Run the tests**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_intruder.py tests/test_cards.py -v
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/intruder/agent.py agents/agents/core/identity.py agents/tests/test_intruder.py
git commit -m "Let intruder corroborate a camera against a router, not a radio against itself"
```

---

## Task 8: `people` becomes `presence`, and `respiration.py` goes

This is the task that removes the dead dependency. It must come after Task 7 or `intruder` breaks.

**Files:**
- Rename: `agents/agents/people/` to `agents/agents/presence/`
- Delete: `agents/agents/presence/respiration.py`
- Modify: `agents/agents/presence/agent.py`, `presence.py`, `agents/agents/core/identity.py`
- Rename: `agents/tests/test_people.py` to `agents/tests/test_presence.py`

- [ ] **Step 1: Find every reference before moving anything**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks && grep -rn "agents.people\|agents/people\|people\.\(personhood\|respiration\|breathing_bpm\|heart_bpm\|headcount\|zone\|perturbation\|moving\|presence_class\|sensed_presences\)" --include="*.py" --include="*.md" --include="*.swift" --include="*.json" . | grep -v ".pyc"
```

Record the list. `app/backend/` and `app/ios/` may reference these field names and this task must not leave them dangling.

- [ ] **Step 2: Do the rename**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents
git mv agents/people agents/presence
git rm agents/presence/respiration.py
git mv tests/test_people.py tests/test_presence.py
```

- [ ] **Step 3: Run the suite to see the full blast radius**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest -q
```

Expected: many failures. This is the one task with a red phase, which is why it is isolated and last among the code tasks.

- [ ] **Step 4: Fix imports and field names**

In `agents/agents/presence/agent.py`: remove the `respiration` import and every call into it; `identity("people")` becomes `identity("presence")`.

In `agents/agents/presence/presence.py`: rename the emitted fields `people.zone` to `presence.zone`, `people.perturbation` to `presence.perturbation`, `people.presence_class` to `presence.presence_class`, `people.sensed_presences` to `presence.sensed_presences`. Delete the `people.headcount` assertion block at `presence.py:183` - the pivot notes it never came from the radio.

In `agents/agents/core/identity.py`: change the `people` entry's `slug` to `"presence"`, drop the `personhood`, `vitals` and `headcount` `Skill` entries entirely, keep `zones` with its fields renamed, and change `profile=TrustProfile.FIDUCIARY` to `TrustProfile.TRANSACTIONAL` with this comment:

```python
        # Was FIDUCIARY when its verdicts turned an occupancy report into a
        # medical emergency. Respiration was cut on 2026-09-19 and the camera
        # took personhood on 2026-09-20, so what is left is "something moved in
        # this room", which opens a shutter and is never on its own the basis
        # for anything said to a dispatcher.
        profile=TrustProfile.TRANSACTIONAL,
```

Update its `summary` and `question` to match: it now answers only motion and room.

- [ ] **Step 5: Fix the tests**

In `agents/tests/test_presence.py`, delete every test of respiration, personhood, breathing rate, heart rate and headcount. Keep and rename the zone and perturbation tests.

- [ ] **Step 6: Run the full suite**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest -q
```

Expected: all pass

- [ ] **Step 7: Verify the dead dependency is actually gone**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks && grep -rn "people.personhood\|respiration" --include="*.py" agents/ | grep -v test
```

Expected: no output. If anything remains, it is a live reference to a deleted signal and must be removed before committing.

- [ ] **Step 8: Run the backend suite too**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/app/backend && python3 -m pytest -q
```

Expected: all pass. If field-name references broke it, fix them here.

- [ ] **Step 9: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add -A agents app/backend
git commit -m "Retire respiration sensing in code, a day after retiring it on paper"
```

---

## Task 9: The two stale grant docstrings

**Files:**
- Modify: `agents/agents/shutter/grant.py` (the `reason` field at ~line 72, `incident_id` at ~line 83)

- [ ] **Step 1: Make the edits**

`reason`:

```python
    reason: str = Field(
        description=(
            "What justified this grant: a motion claim id for `open`, a vision verdict "
            "id for `close`. **Recorded, not trusted** - it goes into the sealed record "
            "so an investigator can follow the chain backwards, and nothing here reads "
            "it as authorization."
        )
    )
```

`incident_id`:

```python
    incident_id: str | None = Field(
        default=None,
        description=(
            "Null when the shutter moves on motion or on a vision verdict, which is the "
            "normal case. Set when a human raised the incident first, or closed the lens "
            "from the app."
        ),
    )
```

- [ ] **Step 2: Run the shutter suite**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest tests/test_shutter.py -q
```

Expected: 22 passed, unchanged

- [ ] **Step 3: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add agents/agents/shutter/grant.py
git commit -m "Correct what the grant says justified it"
```

---

## Task 10: The documentation that is now wrong

Per root `CLAUDE.md`, `docs/swapping-in-real-parts.md` is the switchboard and must list every simulated seam.

**Files:**
- Modify: `docs/swapping-in-real-parts.md`, `docs/PIVOT.md`, `CLAUDE.md`, `TASKS.md`

- [ ] **Step 1: Add the vision row to the switchboard**

In `docs/swapping-in-real-parts.md`, following the existing row format, add a `vision.occupancy` entry recording: the seam is `StubTracker` to `YoloBotSortTracker`; the flip is a constructor argument; you can tell it worked because the verdict varies with what is in front of the camera; and the half-flipped state to watch for is a real tracker with no weights file, which returns zero detections, reads as `no_person`, closes the shutter, and looks exactly like a working benign close while actually being a blind camera. Note that `Occupancy.TRACKER_UNAVAILABLE` and `VisionAgent`'s unknown-instead-of-assertion behaviour are what make that state visible rather than silent.

- [ ] **Step 2: Add a startup assertion for the blind-camera state**

The documentation line is not sufficient on its own. In whatever constructs the real tracker in `vision/hawkeye_vision/`, confirm `Tracker.available` is already set false with a `reason` when weights are missing - `YoloBotSortTracker` has `available` and `reason` attributes for exactly this. Verify:

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/vision && python3 -m pytest tests/test_yolo.py -q
```

If no test covers the missing-weights path, add one asserting `available is False` and `reason` is non-empty.

- [ ] **Step 3: Update the architecture diagram**

In root `CLAUDE.md`, the ASCII diagram shows `presence -> intruder -> master -> shutter -> vision`. Redraw it as the two decisions: `presence` motion into `master`, `master` grant into `shutter`, `shutter` open into `vision`, and `vision` back into `master` for the close plus into `intruder` for the verdict. Update the timing budget table: the 0.6s `intruder` row no longer sits between motion and the grant, so the grant issues at roughly 0.4s and the intruder verdict lands after the camera does.

Update the seven-agent table: `presence` now reads "Motion, and which room" and `vision` gains "the personhood verdict that closes the shutter again".

- [ ] **Step 4: Record the change in `docs/PIVOT.md`**

Add a dated section recording that the trigger chain changed on 2026-09-20, that motion alone now opens the lens, that the camera closes it, and both rejections so neither is re-proposed: camera-as-authenticator (circular - it would have to watch to decide whether it may watch) and camera-side identity matching (needs enrolment and a database we do not have).

- [ ] **Step 5: Update `TASKS.md`**

Mark the vision-agent task done, and add two rows for the seams this plan deliberately leaves unbuilt:

1. Wiring `LocalShutterClient` to a real networked `shutter` over A2A. It is in-process today, and `ports.py` already warns that an in-process call verifies nothing.
2. The real `OccupancySource` adapter: pull a `Frame`, call `Tracker.update`, feed `TrackBook`, call `verdict()` with the live detections and `Tracker.available`. Needs a camera to exercise honestly.

- [ ] **Step 6: Full verification**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks/agents && python3 -m pytest -q
cd /Users/cayden/Documents/GitHub/VTHacks/vision && python3 -m pytest -q
cd /Users/cayden/Documents/GitHub/VTHacks/app/backend && python3 -m pytest -q
```

Expected: all three suites pass

- [ ] **Step 7: Commit**

```bash
cd /Users/cayden/Documents/GitHub/VTHacks
git add docs CLAUDE.md TASKS.md vision
git commit -m "Redraw the trigger chain in the docs that describe it"
```

---

## Definition of done

- All three test suites pass.
- `grep -rn "people.personhood" agents/` returns nothing.
- `agents/agents/shutter/` is unchanged except `grant.py` docstrings and at most one public `challenge()` accessor.
- The motion-flood test bounds servo commands to 1 over 500 ticks of continuous motion.
- `docs/swapping-in-real-parts.md` has a `vision.occupancy` row naming the blind-camera failure.
