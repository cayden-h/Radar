# Unexpected-Presence Notice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `agents/intruder` says a confirmed person is not accounted for, send the resident an SMS that reaches them with the app closed, and show a banner in the app.

**Architecture:** A ninth stream event, `notice`, produced at a single chokepoint. `HubRuntime.emit` is already documented as "the only way an event reaches the app", so a `NoticeDetector` is run there against every `StateEvent` and needs no change to either `SimulatedMasterClient` or `LiveMasterClient`. When it fires, the notice goes to a list of `NoticeSink`s: one publishes a `NoticeEvent` back through `emit`, one posts to Twilio. The detector is a pure synchronous class driven by `state.captured_at` rather than a wall clock, so the whole trigger rule is unit-testable without a server, a socket, or a sleep.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest + pytest-asyncio, `httpx` (already a dependency - no `twilio` package). Swift 6 / SwiftUI on the client, no third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-09-19-unexpected-presence-notice-design.md`

---

## File Structure

**Backend, created:**

| File | Responsibility |
|---|---|
| `app/backend/hawkeye_backend/models/notice.py` | `NoticeSeverity` and `Notice`. Data only; `NoticeEvent` lives in `events.py` with every other event class. |
| `app/backend/hawkeye_backend/notices/__init__.py` | Package re-exports. |
| `app/backend/hawkeye_backend/notices/detector.py` | The trigger rule. Pure, synchronous, no I/O. |
| `app/backend/hawkeye_backend/notices/sinks.py` | `NoticeSink` protocol, `StreamSink`, `TwilioSink`. |
| (Task 3 also adds `Notice.room`, set by the detector, so the SMS never parses rendered prose to recover a room name.) | |
| `app/backend/tests/test_notice_detector.py` | The trigger rule under test. |
| `app/backend/tests/test_notice_sinks.py` | Fan-out, failure isolation, Twilio request shape, rate limit. |

**Backend, modified:**

| File | Change |
|---|---|
| `app/backend/hawkeye_backend/models/events.py` | `EventKind.NOTICE`, the `NoticeEvent` class, and its place in the `EventPayload` union. |
| `app/backend/hawkeye_backend/config.py` | Four Twilio settings plus `site_timezone`. |
| `app/backend/hawkeye_backend/runtime.py` | Hold the detector and sinks; run them on every `StateEvent`. |
| `app/backend/hawkeye_backend/main.py` | Construct the sinks from settings at startup. |
| `app/backend/tools/gen_schema.py` | Emit `schema/event-notice.json`. |

**iOS, created:**

| File | Responsibility |
|---|---|
| `app/ios/HawkEye/Models/Notice.swift` | Mirrors the Pydantic model field for field. |
| `app/ios/HawkEye/Features/Home/NoticeBanner.swift` | The dismissible banner. |

**iOS, modified:**

| File | Change |
|---|---|
| `app/ios/HawkEye/Services/HawkEyeClient.swift` | `.notice` case on `HubEvent`; `notices` on `HawkEyeClienting`. |
| `app/ios/HawkEye/Services/LiveHawkEyeClient.swift` | Store notices off the stream. |
| `app/ios/HawkEye/Services/MockHawkEyeClient.swift` | Raise the scripted notice. |
| `app/ios/HawkEye/Features/Home/HomeView.swift` | Render the banner. |
| `app/ios/HawkEye/Config.swift` | `mockNoticeHoldSeconds`. |

**Why `notices/` is a package rather than one module:** the detector is a pure rule that a judge may want to read on its own, and the sinks do network I/O. Keeping them in one file would mean the rule could not be read without reading an HTTP client. They change for different reasons.

---

### Task 1: The notice models

**Files:**
- Create: `app/backend/hawkeye_backend/models/notice.py`
- Modify: `app/backend/hawkeye_backend/models/events.py`
- Test: `app/backend/tests/test_notice_models.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_notice_models.py`:

```python
"""The notice model, and its place in the envelope union."""

from __future__ import annotations

from datetime import UTC, datetime

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import EnvelopeAdapter, EventKind, NoticeEvent, envelope
from hawkeye_backend.models.notice import Notice, NoticeSeverity


def a_notice() -> Notice:
    return Notice(
        notice_id="ntc-p4",
        severity=NoticeSeverity.ATTENTION,
        title="Unexpected person",
        body="Not accounted for. Living room.",
        zone="living_room",
        presence_id="p4",
        raised_at=datetime(2026, 9, 19, 21, 4, tzinfo=UTC),
        provenance=Provenance(
            source=Source.AGENT_INFERENCE,
            producer="agents/intruder",
            ansname="ans://v1.0.0.intruder.hawkeye.example",
        ),
    )


def test_notice_carries_derived_provenance():
    """The honesty rule applies here exactly as it does to a reading."""
    n = a_notice()
    assert n.provenance.source_class == "derived"
    assert n.provenance.simulated is False


def test_notice_round_trips_through_the_envelope_union():
    """A notice decodes back as a NoticeEvent and not as something else."""
    env = envelope(seq=7, payload=NoticeEvent(notice=a_notice()))
    raw = env.model_dump_json()

    decoded = EnvelopeAdapter.validate_json(raw)

    assert decoded.kind is EventKind.NOTICE
    assert isinstance(decoded.payload, NoticeEvent)
    assert decoded.payload.notice.presence_id == "p4"
    assert decoded.payload.notice.title == "Unexpected person"


def test_notice_payload_key_is_notice():
    """The wire key is `notice`, matching the per-kind naming the app mirrors."""
    env = envelope(seq=7, payload=NoticeEvent(notice=a_notice()))
    assert env.model_dump(mode="json")["payload"]["notice"]["notice_id"] == "ntc-p4"
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_models.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'hawkeye_backend.models.notice'`.

- [ ] **Step 3: Create the models**

Create `app/backend/hawkeye_backend/models/notice.py`:

```python
"""A notice: something the resident should know, that is not an incident.

`app/CLAUDE.md` already reserves the word - detections from the sensing agents
"surface here as alerts... An alert is information a person acts on. It is not a
call." An unexpected person is the clearest case of it.

This is on-thesis rather than a departure from it. Hawk Eye never calls 911 on
its own; the sensing agents detect, classify and *inform*, and a human decides
whether emergency services are needed. A notice is the inform step made to
actually arrive somewhere.

A notice carries `Provenance` like every other claim in this service, for the
same reason: a compromised sensing agent must not be able to buzz a resident's
phone at 3am any more than it can dial 911.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import Provenance, utc_now


class NoticeSeverity(StrEnum):
    """How loudly the app should render it. Never a dispatch decision."""

    INFO = "info"
    ATTENTION = "attention"


class Notice(BaseModel):
    """One thing the resident should know about."""

    notice_id: str
    severity: NoticeSeverity
    title: str = Field(description="Short, factual, e.g. 'Unexpected person'.")
    body: str = Field(description="One line. Never contains the street address.")
    zone: str | None = Field(default=None, description="Floorplan zone key, when there is one.")
    presence_id: str | None = Field(
        default=None,
        description="Session-scoped only. We do not do person re-identification.",
    )
    raised_at: datetime = Field(default_factory=utc_now)
    provenance: Provenance = Field(description="Required. See the honesty rule.")


```

`NoticeEvent` is deliberately **not** here. Every other event class lives in `events.py`, and
`Envelope.kind` is typed `EventKind`, so a `Literal["notice"]` default would make `envelope.kind`
a bare `str` and `decoded.kind is EventKind.NOTICE` would be False. Keeping the data model here and
the event class there follows the existing pattern and keeps the enum identity intact.

- [ ] **Step 4: Wire it into the event union**

In `app/backend/hawkeye_backend/models/events.py`:

Add to the imports, after the `hawkeye_backend.models.incident` import block:

```python
from hawkeye_backend.models.notice import Notice
```

Add to `EventKind`, after `CONTEXT`:

```python
    NOTICE = "notice"
```

Add the event class itself, after `ContextEvent` and before the `EventPayload` union:

```python
class NoticeEvent(BaseModel):
    """A notice was raised: something the resident should know about.

    Does not create an incident and does not dial. `app/CLAUDE.md`: "An alert is
    information a person acts on. It is not a call."
    """

    kind: Literal[EventKind.NOTICE] = EventKind.NOTICE
    notice: Notice
```

Add to the `EventPayload` annotated union, after `| ContextEvent`:

```python
    | NoticeEvent
```

Re-export so `from hawkeye_backend.models.events import NoticeEvent` works for every existing caller; add to the bottom of the file:

```python
__all__ = [
    "ContextEvent",
    "Envelope",
    "EnvelopeAdapter",
    "ErrorEvent",
    "EventKind",
    "EventPayload",
    "HelloEvent",
    "IncidentEvent",
    "IncidentPhase",
    "InstructionEvent",
    "Notice",
    "NoticeEvent",
    "StateEvent",
    "TranscriptEvent",
    "VerificationEvent",
    "envelope",
]
```

There is no circular import: `notice.py` imports only from `common.py`, and `events.py` imports `Notice` from it the same way it already imports `Incident` from `incident.py`.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_models.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Confirm nothing else broke**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `40 passed` - the 37 existing tests plus these 3.

- [ ] **Step 7: Commit**

```bash
git add app/backend/hawkeye_backend/models/notice.py app/backend/hawkeye_backend/models/events.py app/backend/tests/test_notice_models.py
git commit -m "Add the notice model and its place in the event union"
```

---

### Task 2: The trigger rule

This is the task that decides whether the feature is trustworthy. Write the tests first and do not shortcut them.

**Files:**
- Create: `app/backend/hawkeye_backend/notices/__init__.py`
- Create: `app/backend/hawkeye_backend/notices/detector.py`
- Test: `app/backend/tests/test_notice_detector.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_notice_detector.py`:

```python
"""The trigger rule.

The detector is driven by `state.captured_at` rather than a wall clock, so
every test here advances time by constructing a frame rather than by sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.state import (
    Calibration,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.notices.detector import NoticeDetector

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)

PROV = Provenance(source=Source.RUVIEW_SIM, producer="sensor/")


def presence(
    presence_id: str = "p4",
    *,
    state: PresenceState = PresenceState.CONFIRMED_MOVING,
    expected: bool | None = False,
    zone: str = "living_room",
) -> Presence:
    return Presence(
        presence_id=presence_id,
        state=state,
        position=Position(zone=zone, x=12.0, y=3.0, zone_confidence=0.8),
        moving=True,
        confidence=0.8,
        vitals=Vitals(respiration=RespirationStatus.BREATHING, breathing_bpm=21, person_confidence=0.88),
        presence_class=PresenceClass.ADULT,
        class_basis="respiration_rate",
        expected=expected,
        provenance=PROV,
    )


def frame(*presences: Presence, at_s: float = 0.0, healthy: bool = True) -> InteriorState:
    # `floorplan` is required on InteriorState - it has no default - so the
    # enrolled plan is built here. It is also what makes the room name in the
    # notice body real rather than a fallback.
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=healthy),
        presences=list(presences),
        floorplan=build_floorplan("site-demo-01"),
    )


def test_nothing_fires_before_the_hold_elapses():
    """Five seconds means five seconds. A notice is unrecallable once sent."""
    d = NoticeDetector(hold_s=5.0)

    assert d.observe(frame(presence(), at_s=0)) == []
    assert d.observe(frame(presence(), at_s=2)) == []
    assert d.observe(frame(presence(), at_s=4.9)) == []


def test_it_fires_once_the_hold_elapses():
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))

    raised = d.observe(frame(presence(), at_s=5.0))

    assert len(raised) == 1
    assert raised[0].presence_id == "p4"
    assert raised[0].zone == "living_room"
    assert raised[0].title == "Unexpected person"
    assert raised[0].provenance.producer == "agents/intruder"


def test_it_fires_exactly_once_however_many_frames_follow():
    """A presence walking room to room is one event, not five."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(presence(), at_s=5.0))

    later = [d.observe(frame(presence(zone="kitchen"), at_s=t)) for t in (6, 7, 8, 30)]

    assert later == [[], [], [], []]


def test_flicker_below_the_hold_resets_the_timer():
    """`expected` can flicker while agents/intruder is still resolving."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(expected=False), at_s=0))
    d.observe(frame(presence(expected=True), at_s=3))

    # The clock restarts from the frame it came back on, so t=6 is only 3s in.
    d.observe(frame(presence(expected=False), at_s=5))
    assert d.observe(frame(presence(expected=False), at_s=8)) == []
    assert len(d.observe(frame(presence(expected=False), at_s=10))) == 1


def test_an_unconfirmed_perturbation_never_fires():
    """The curtain over the dryer vent is not a person and never becomes one here."""
    d = NoticeDetector(hold_s=5.0)
    curtain = presence("p5", state=PresenceState.UNCONFIRMED, expected=False, zone="laundry")

    d.observe(frame(curtain, at_s=0))

    assert d.observe(frame(curtain, at_s=30)) == []


def test_an_unhealthy_baseline_suppresses_everything():
    """A stale baseline invents presences. Texting someone at 3am on one is its own harm."""
    d = NoticeDetector(hold_s=5.0)

    d.observe(frame(presence(), at_s=0, healthy=False))

    assert d.observe(frame(presence(), at_s=30, healthy=False)) == []


def test_an_unhealthy_baseline_resets_an_in_flight_hold():
    """The hold must be five seconds of trustworthy observation, not five of any."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(presence(), at_s=3, healthy=False))

    assert d.observe(frame(presence(), at_s=6)) == []
    assert len(d.observe(frame(presence(), at_s=11))) == 1


def test_an_expected_resident_never_fires():
    d = NoticeDetector(hold_s=5.0)
    resident = presence("p1", expected=True, zone="second_bedroom")

    d.observe(frame(resident, at_s=0))

    assert d.observe(frame(resident, at_s=30)) == []


def test_a_null_expected_never_fires():
    """null means not yet decided. A frame that omits it must not make intruders."""
    d = NoticeDetector(hold_s=5.0)
    undecided = presence("p2", expected=None)

    d.observe(frame(undecided, at_s=0))

    assert d.observe(frame(undecided, at_s=30)) == []


def test_two_unexpected_presences_each_get_their_own_notice():
    d = NoticeDetector(hold_s=5.0)
    a, b = presence("p4"), presence("p6", zone="kitchen")
    d.observe(frame(a, b, at_s=0))

    raised = d.observe(frame(a, b, at_s=5))

    assert sorted(n.presence_id for n in raised) == ["p4", "p6"]


def test_a_presence_that_disappears_and_returns_restarts_the_hold():
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))
    d.observe(frame(at_s=2))

    assert d.observe(frame(presence(), at_s=4)) == []
    assert len(d.observe(frame(presence(), at_s=9))) == 1


def test_the_body_uses_the_room_name_from_the_floorplan():
    """The resident reads 'Living room', not 'living_room'."""
    d = NoticeDetector(hold_s=5.0)
    d.observe(frame(presence(), at_s=0))

    raised = d.observe(frame(presence(), at_s=5))

    assert raised[0].body == "Not accounted for. Living room."
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_detector.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'hawkeye_backend.notices'`.

- [ ] **Step 3: Create the package**

Create `app/backend/hawkeye_backend/notices/__init__.py`:

```python
"""Notices: the inform step of "detect, classify and inform".

A notice is information a person acts on. It is not an incident and it does not
dial. See `hawkeye_backend/models/notice.py`.
"""

from hawkeye_backend.notices.detector import NoticeDetector
from hawkeye_backend.notices.sinks import NoticeSink, StreamSink, TwilioSink, deliver

__all__ = ["NoticeDetector", "NoticeSink", "StreamSink", "TwilioSink", "deliver"]
```

This imports `sinks`, which does not exist until Task 3. Write the file now and expect the detector tests to keep failing on the import until Task 3 lands; that is fine and is the reason the two tasks are adjacent. If you would rather see green in between, create `sinks.py` as an empty file now and fill it in Task 3.

- [ ] **Step 4: Write the detector**

Create `app/backend/hawkeye_backend/notices/detector.py`:

```python
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
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_detector.py -q
```

Expected: `12 passed`. If the import of `sinks` in `__init__.py` is still failing, finish Task 3 first and come back; the detector tests are the gate on Task 3 being correct, not the other way round.

`build_floorplan("site-demo-01")` names the `living_room` zone "Living room", which is what `test_the_body_uses_the_room_name_from_the_floorplan` asserts. If that zone is named differently in `master/scenario.py`, fix the assertion to match the plan rather than changing the plan.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/notices/ app/backend/tests/test_notice_detector.py
git commit -m "Add the unexpected-presence trigger rule"
```

---

### Task 3: The sinks

**Files:**
- Create: `app/backend/hawkeye_backend/notices/sinks.py`
- Test: `app/backend/tests/test_notice_sinks.py`

- [ ] **Step 1: Write the failing tests**

Create `app/backend/tests/test_notice_sinks.py`:

```python
"""Sink fan-out, failure isolation, and the Twilio request shape.

No test here sends a real message.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.notice import Notice, NoticeSeverity
from hawkeye_backend.notices.sinks import TwilioSink, deliver

pytestmark = pytest.mark.asyncio


def a_notice(**overrides) -> Notice:
    base = dict(
        notice_id="ntc-p4",
        severity=NoticeSeverity.ATTENTION,
        title="Unexpected person",
        body="Not accounted for. Living room.",
        zone="living_room",
        presence_id="p4",
        raised_at=datetime(2026, 9, 20, 1, 4, tzinfo=UTC),
        provenance=Provenance(source=Source.AGENT_INFERENCE, producer="agents/intruder"),
    )
    base.update(overrides)
    return Notice(**base)


class Recorder:
    """A sink that remembers what it was handed."""

    def __init__(self) -> None:
        self.seen: list[Notice] = []

    async def deliver(self, notice: Notice) -> None:
        self.seen.append(notice)


class Exploding:
    """A sink that always fails, standing in for Twilio refusing a trial send."""

    async def deliver(self, notice: Notice) -> None:
        raise RuntimeError("A2P 10DLC registration required")


async def test_every_sink_receives_the_notice():
    a, b = Recorder(), Recorder()

    await deliver(a_notice(), [a, b])

    assert len(a.seen) == 1
    assert len(b.seen) == 1


async def test_a_failing_sink_does_not_stop_the_others():
    """A Twilio failure must not take down the in-app banner. This is the
    mitigation the spec relies on for demo day."""
    good = Recorder()

    await deliver(a_notice(), [Exploding(), good])

    assert len(good.seen) == 1


def stub_twilio(captured: list[httpx.Request], status: int = 201) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json={"sid": "SM0000"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_twilio_posts_the_expected_form():
    captured: list[httpx.Request] = []
    sink = TwilioSink(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured),
    )

    await sink.deliver(a_notice())

    assert len(captured) == 1
    req = captured[0]
    assert req.url.path == "/2010-04-01/Accounts/ACfake/Messages.json"
    assert req.method == "POST"
    assert "Authorization" in req.headers
    body = req.content.decode()
    assert "From=%2B15550001111" in body
    assert "To=%2B15550002222" in body


async def test_the_sms_names_the_room_and_the_local_time():
    """01:04 UTC is 21:04 the previous evening in Blacksburg."""
    captured: list[httpx.Request] = []
    sink = TwilioSink(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured),
    )

    await sink.deliver(a_notice())

    body = httpx.QueryParams(captured[0].content.decode())["Body"]
    assert body == (
        "Hawk Eye: unexpected person in the living room, 21:04.\nNot accounted for."
    )


async def test_the_sms_never_contains_the_street_address():
    """The dispatch address is bound at registration and does not travel."""
    captured: list[httpx.Request] = []
    sink = TwilioSink(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured),
    )

    await sink.deliver(a_notice())

    body = httpx.QueryParams(captured[0].content.decode())["Body"]
    assert "Ridgeview" not in body
    assert "Blacksburg" not in body


async def test_the_rate_limit_caps_a_rehearsal_loop():
    """A bug in the trigger must not be able to burn the trial credit."""
    captured: list[httpx.Request] = []
    sink = TwilioSink(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured),
        min_interval_s=0.0,
        max_per_process=3,
    )

    for i in range(10):
        await sink.deliver(a_notice(notice_id=f"ntc-{i}"))

    assert len(captured) == 3


async def test_a_twilio_error_response_is_logged_not_raised():
    """Delivery failures are logged, never raised. The stream sink runs on."""
    captured: list[httpx.Request] = []
    sink = TwilioSink(
        account_sid="ACfake",
        auth_token="tokenfake",
        from_number="+15550001111",
        to_number="+15550002222",
        timezone="America/New_York",
        client=stub_twilio(captured, status=400),
    )

    await sink.deliver(a_notice())  # must not raise
```

- [ ] **Step 2: Add the asyncio marker config**

`pytest-asyncio` needs a mode set or every `async def` test is skipped with a warning. In `app/backend/pyproject.toml`, change the pytest section to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
```

- [ ] **Step 3: Run the tests and confirm they fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_sinks.py -q
```

Expected: `ImportError: cannot import name 'TwilioSink' from 'hawkeye_backend.notices.sinks'`.

- [ ] **Step 4: Write the sinks**

Create `app/backend/hawkeye_backend/notices/sinks.py`:

```python
"""Where a notice goes.

Two sinks today. The stream sink puts a `NoticeEvent` on the websocket, which is
what draws the in-app banner. The Twilio sink sends an SMS, which is the only
one of the two that reaches a resident whose phone is locked and whose app is
closed.

APNs is the third sink and is **not implemented**. It is the reason this is a
protocol rather than a function call: adding it changes nothing above this file.
There is deliberately no local-notification sink - a `UNUserNotificationCenter`
notification only fires while the app holds the socket, which is exactly the
case the resident does not need help with, and on stage it is indistinguishable
from a real push.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import httpx

from hawkeye_backend.models.events import NoticeEvent
from hawkeye_backend.models.notice import Notice

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com"


@runtime_checkable
class NoticeSink(Protocol):
    """One way a notice reaches a person."""

    async def deliver(self, notice: Notice) -> None: ...


async def deliver(notice: Notice, sinks: Sequence[NoticeSink]) -> None:
    """Fan out to every sink. One sink failing never stops another.

    This is load-bearing for demo day: a Twilio trial that starts refusing
    A2P sends on Sunday morning must leave the in-app banner intact.
    """
    for sink in sinks:
        try:
            await sink.deliver(notice)
        except Exception:
            logger.exception("notice sink %s failed for %s", type(sink).__name__, notice.notice_id)


class StreamSink:
    """Publishes the notice onto the websocket, via the runtime's one emit path."""

    def __init__(self, emit: Callable[[NoticeEvent], Awaitable[None]]) -> None:
        self._emit = emit

    async def deliver(self, notice: Notice) -> None:
        await self._emit(NoticeEvent(notice=notice))


class TwilioSink:
    """Sends an SMS through the Twilio REST API.

    Uses `httpx` directly rather than the `twilio` package: the API is one form
    POST with basic auth, `httpx` is already a dependency, and the service holds
    the line on adding dependencies it does not need.

    Trial-account limits, stated where someone debugging will find them:
    the trial only sends to numbers verified in the Twilio console, every
    message is prefixed "Sent from your Twilio trial account", and US A2P 10DLC
    enforcement can begin refusing trial sends without warning.
    """

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        timezone: str,
        client: httpx.AsyncClient | None = None,
        min_interval_s: float = 60.0,
        max_per_process: int = 5,
    ) -> None:
        self._sid = account_sid
        self._from = from_number
        self._to = to_number
        self._tz = ZoneInfo(timezone)
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._auth = (account_sid, auth_token)
        self._min_interval_s = min_interval_s
        self._max_per_process = max_per_process
        self._sent = 0
        self._last_at: float | None = None
        self._lock = asyncio.Lock()

    def _body(self, notice: Notice) -> str:
        """The message. The street address is never in it.

        The dispatch address is bound at registration and sealed; it does not
        travel in claims and it does not travel here. An SMS is plaintext to a
        device that can be stolen, which is the threat model that put the
        address out of claims in the first place.

        The room comes off `notice.room`, which the detector resolved from the
        floorplan. The sink never re-derives it: one place decides what a zone
        is called, and a sink that parsed the rendered prose back apart would
        break the first time anyone reworded it.
        """
        local = notice.raised_at.astimezone(self._tz).strftime("%H:%M")
        where = f" in the {notice.room.lower()}" if notice.room else ""
        return f"Hawk Eye: unexpected person{where}, {local}.\nNot accounted for."

    async def deliver(self, notice: Notice) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._sent >= self._max_per_process:
                logger.warning("twilio: process cap of %d reached, dropping %s",
                               self._max_per_process, notice.notice_id)
                return
            if self._last_at is not None and (now - self._last_at) < self._min_interval_s:
                logger.warning("twilio: within %.0fs of the last send, dropping %s",
                               self._min_interval_s, notice.notice_id)
                return
            self._sent += 1
            self._last_at = now

        resp = await self._client.post(
            f"{TWILIO_API}/2010-04-01/Accounts/{self._sid}/Messages.json",
            auth=self._auth,
            data={"From": self._from, "To": self._to, "Body": self._body(notice)},
        )
        if resp.status_code >= 400:
            logger.error("twilio refused %s: %s %s", notice.notice_id, resp.status_code, resp.text)
            return
        logger.info("twilio sent %s", notice.notice_id)

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_sinks.py -q
```

Expected: `7 passed`.

- [ ] **Step 6: Run the whole suite**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `63 passed` (56 existing + 7 new).

- [ ] **Step 7: Commit**

```bash
git add app/backend/hawkeye_backend/notices/sinks.py app/backend/tests/test_notice_sinks.py app/backend/pyproject.toml
git commit -m "Add the notice sinks: stream and Twilio SMS"
```

---

### Task 4: Configuration

**Files:**
- Modify: `app/backend/hawkeye_backend/config.py`
- Test: `app/backend/tests/test_notice_config.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_notice_config.py`:

```python
"""Twilio configuration, and the requirement that its absence is harmless."""

from __future__ import annotations

from hawkeye_backend.config import Settings


def test_twilio_is_unconfigured_by_default():
    """The app must run with no Twilio account at all."""
    s = Settings(_env_file=None)
    assert s.twilio_configured is False


def test_twilio_needs_all_four_values():
    """Three out of four is a misconfiguration, not a partial feature."""
    s = Settings(
        _env_file=None,
        twilio_account_sid="ACfake",
        twilio_auth_token="tokenfake",
        twilio_from_number="+15550001111",
    )
    assert s.twilio_configured is False


def test_twilio_configured_when_all_four_are_present():
    s = Settings(
        _env_file=None,
        twilio_account_sid="ACfake",
        twilio_auth_token="tokenfake",
        twilio_from_number="+15550001111",
        twilio_to_number="+15550002222",
    )
    assert s.twilio_configured is True


def test_the_site_timezone_defaults_to_the_demo_home():
    s = Settings(_env_file=None)
    assert s.site_timezone == "America/New_York"
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_config.py -q
```

Expected: `AttributeError: 'Settings' object has no attribute 'twilio_configured'`.

- [ ] **Step 3: Add the settings**

In `app/backend/hawkeye_backend/config.py`, add these fields after the `store_backend` / `mongodb_database` block and before `host`:

```python
    # Notices. A notice is information the resident acts on, never a dispatch.
    # The hold before an unexpected presence becomes one; see
    # hawkeye_backend/notices/detector.py for why it is not zero.
    notice_hold_s: float = 5.0

    # Twilio, for the SMS sink. All four or none: three out of four is a
    # misconfiguration and is treated as unconfigured rather than as a partial
    # feature that fails at the moment it matters.
    #
    # Trial accounts only send to numbers verified in the Twilio console, and
    # prefix every message with "Sent from your Twilio trial account".
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_number: str = ""

    # Rate limits on the SMS sink. A rehearsal loop must not be able to send
    # fifty texts, and a bug in the trigger must not burn the trial credit.
    twilio_min_interval_s: float = 60.0
    twilio_max_per_process: int = 5

    # Used to render the local time in an SMS. The demo home is in Blacksburg.
    site_timezone: str = "America/New_York"
```

Add this property to `Settings`, after the fields:

```python
    @property
    def twilio_configured(self) -> bool:
        """True only when every value needed to send is present."""
        return all(
            (
                self.twilio_account_sid,
                self.twilio_auth_token,
                self.twilio_from_number,
                self.twilio_to_number,
            )
        )
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_config.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Document the variables**

Add to `app/backend/README.md`, under whatever section lists environment variables (create a `## Notices` section at the end of the file if there is none):

```markdown
## Notices

An unexpected presence that holds for `HAWKEYE_NOTICE_HOLD_S` seconds raises a
notice: a banner in the app, and an SMS if Twilio is configured. A notice is
information the resident acts on. It never creates an incident and never dials.

Twilio is optional and the service runs normally without it. All four values are
required together:

```sh
export HAWKEYE_TWILIO_ACCOUNT_SID=ACxxxxxxxx
export HAWKEYE_TWILIO_AUTH_TOKEN=xxxxxxxx
export HAWKEYE_TWILIO_FROM_NUMBER=+15550001111
export HAWKEYE_TWILIO_TO_NUMBER=+15550002222    # must be verified in the Twilio console
```

On a trial account the destination number must be verified in the console, and
every message arrives prefixed "Sent from your Twilio trial account".
```

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/config.py app/backend/tests/test_notice_config.py app/backend/README.md
git commit -m "Configure the notice hold and the Twilio sink"
```

---

### Task 5: Run the detector at the one chokepoint

**Files:**
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Modify: `app/backend/hawkeye_backend/main.py`
- Test: `app/backend/tests/test_notice_runtime.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_notice_runtime.py`:

```python
"""The runtime hook: a state event that qualifies produces a notice event."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hawkeye_backend.bus import EventBus
from hawkeye_backend.config import Settings
from hawkeye_backend.master.scenario import build_floorplan
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import NoticeEvent, StateEvent
from hawkeye_backend.models.state import (
    Calibration,
    InteriorState,
    Position,
    Presence,
    PresenceClass,
    PresenceState,
    RespirationStatus,
    Vitals,
)
from hawkeye_backend.notices import NoticeDetector
from hawkeye_backend.runtime import HubRuntime
from hawkeye_backend.store import InMemoryStore

T0 = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)
PROV = Provenance(source=Source.RUVIEW_SIM, producer="sensor/")


class NoMaster:
    async def start(self, sink) -> None: ...
    async def stop(self) -> None: ...


def frame(at_s: float, *, expected: bool | None = False) -> InteriorState:
    return InteriorState(
        site_id="site-demo-01",
        captured_at=T0 + timedelta(seconds=at_s),
        sensor_identity="ans://v1.0.0.sensor.hawkeye.example",
        calibration=Calibration(baseline_age_s=30.0, healthy=True),
        presences=[
            Presence(
                presence_id="p4",
                state=PresenceState.CONFIRMED_MOVING,
                position=Position(zone="living_room", x=12.0, y=3.0, zone_confidence=0.8),
                moving=True,
                confidence=0.8,
                vitals=Vitals(
                    respiration=RespirationStatus.BREATHING,
                    breathing_bpm=21,
                    person_confidence=0.88,
                ),
                presence_class=PresenceClass.ADULT,
                class_basis="respiration_rate",
                expected=expected,
                provenance=PROV,
            )
        ],
        floorplan=build_floorplan("site-demo-01"),
    )


def a_runtime(sinks) -> HubRuntime:
    return HubRuntime(
        settings=Settings(_env_file=None),
        store=InMemoryStore(),
        bus=EventBus(),
        client=NoMaster(),
        detector=NoticeDetector(hold_s=5.0),
        notice_sinks=sinks,
    )


class Recorder:
    def __init__(self) -> None:
        self.seen = []

    async def deliver(self, notice) -> None:
        self.seen.append(notice)


async def test_a_qualifying_state_stream_raises_one_notice():
    rec = Recorder()
    rt = a_runtime([rec])

    await rt.emit(StateEvent(state=frame(0)))
    assert rec.seen == []

    await rt.emit(StateEvent(state=frame(5)))
    assert len(rec.seen) == 1
    assert rec.seen[0].presence_id == "p4"


async def test_the_notice_reaches_a_subscribed_app():
    """The stream sink is wired by the runtime, so a websocket client sees it."""
    rt = a_runtime([])
    sub = await rt.bus.subscribe()

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    kinds = []
    while not sub.queue.empty():
        kinds.append(sub.queue.get_nowait().payload)
    assert any(isinstance(p, NoticeEvent) for p in kinds)


async def test_a_notice_event_does_not_itself_run_the_detector():
    """Guards against unbounded recursion through emit."""
    rt = a_runtime([])

    await rt.emit(StateEvent(state=frame(0)))
    await rt.emit(StateEvent(state=frame(5)))

    events = await rt.store.recent_events(200)
    notices = [e for e in events if isinstance(e.payload, NoticeEvent)]
    assert len(notices) == 1


async def test_an_expected_resident_raises_nothing():
    rec = Recorder()
    rt = a_runtime([rec])

    await rt.emit(StateEvent(state=frame(0, expected=True)))
    await rt.emit(StateEvent(state=frame(30, expected=True)))

    assert rec.seen == []
```

`recent_events(limit)` is the `InMemoryStore` reader; there is no `list_events`.

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_runtime.py -q
```

Expected: `TypeError: HubRuntime.__init__() got an unexpected keyword argument 'detector'`.

- [ ] **Step 3: Wire the runtime**

In `app/backend/hawkeye_backend/runtime.py`:

Add to the imports:

```python
from hawkeye_backend.models.notice import Notice, NoticeEvent
from hawkeye_backend.notices import NoticeDetector, NoticeSink, StreamSink, deliver
```

Add `NoticeEvent` to the existing `from hawkeye_backend.models.events import (...)` block.

Replace `__init__` with:

```python
    def __init__(
        self,
        settings: Settings,
        store: Store,
        bus: EventBus,
        client: MasterClient,
        detector: NoticeDetector | None = None,
        notice_sinks: list[NoticeSink] | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.bus = bus
        self.client = client
        self.started_at = time.monotonic()
        self.detector = detector or NoticeDetector(hold_s=settings.notice_hold_s)
        # The stream sink is always present, so the in-app banner never depends
        # on Twilio being configured or on Twilio being up.
        self.notice_sinks: list[NoticeSink] = [StreamSink(self.emit_notice)]
        self.notice_sinks.extend(notice_sinks or [])
```

Replace `emit` with:

```python
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

        # After publishing, so the frame the notice describes is already on the
        # wire when the notice arrives. Only StateEvent feeds the detector, which
        # is what bounds the recursion through emit_notice to one level.
        if isinstance(payload, StateEvent):
            for notice in self.detector.observe(payload.state):
                await deliver(notice, self.notice_sinks)

    async def emit_notice(self, event: NoticeEvent) -> None:
        """The stream sink's callback. Separate so the recursion is visible."""
        await self.emit(event)
```

Add a `NoticeEvent` case to `_persist`, before the `case _:` fallthrough, only if `Store` has an append for it. It does not, and notices are already in the event log via `append_event`, so leave `_persist` untouched and add this comment above `case _:`:

```python
            # NoticeEvent has no typed record of its own: it is already in the
            # event log via append_event, and the app reads it off the stream.
```

- [ ] **Step 4: Construct the Twilio sink at startup**

In `app/backend/hawkeye_backend/main.py`, find where `HubRuntime` is constructed. Add above it:

```python
    notice_sinks: list[NoticeSink] = []
    if settings.twilio_configured:
        notice_sinks.append(
            TwilioSink(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_from_number,
                to_number=settings.twilio_to_number,
                timezone=settings.site_timezone,
                min_interval_s=settings.twilio_min_interval_s,
                max_per_process=settings.twilio_max_per_process,
            )
        )
        logger.info("notices: twilio sms sink enabled")
    else:
        logger.info("notices: twilio not configured, in-app banner only")
```

and pass `notice_sinks=notice_sinks` to the `HubRuntime(...)` call. Add to the imports:

```python
from hawkeye_backend.notices import NoticeSink, TwilioSink
```

If `main.py` has no module-level `logger`, add `logger = logging.getLogger(__name__)` and `import logging` alongside the existing imports.

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_notice_runtime.py -q
```

Expected: `4 passed`.

- [ ] **Step 6: Run the whole suite**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `71 passed` (63 + 4 config + 4 runtime).

- [ ] **Step 7: Verify it end to end against the simulated master**

```bash
cd app/backend && HAWKEYE_MODE=simulated HAWKEYE_SIM_AUTOSTART=true .venv/bin/python -m uvicorn hawkeye_backend.main:app --port 8787 &
sleep 30 && .venv/bin/python tools/ws_probe.py 2>&1 | grep -i notice
```

Expected: at least one line containing `"kind": "notice"` with `"title": "Unexpected person"`, roughly 5 seconds after the burglary scenario's intruder acquires respiration. If `tools/ws_probe.py` takes different arguments, run it as its own `--help` describes. Kill the server afterwards.

- [ ] **Step 8: Commit**

```bash
git add app/backend/hawkeye_backend/runtime.py app/backend/hawkeye_backend/main.py app/backend/tests/test_notice_runtime.py
git commit -m "Run the notice detector at the runtime's one emit path"
```

---

### Task 6: The schema example

**Files:**
- Modify: `app/backend/tools/gen_schema.py`
- Create (generated): `app/backend/schema/event-notice.json`

- [ ] **Step 1: Add the notice example to the generator**

In `app/backend/tools/gen_schema.py`, add to the imports:

```python
from hawkeye_backend.models.notice import Notice, NoticeEvent, NoticeSeverity
```

Find where the other `event-*.json` examples are written (they follow a consistent pattern of building an `Envelope` and dumping it). Add an entry alongside them, matching the surrounding style exactly:

```python
    write(
        "event-notice.json",
        Envelope(
            seq=48,
            payload=NoticeEvent(
                notice=Notice(
                    notice_id="ntc-p4",
                    severity=NoticeSeverity.ATTENTION,
                    title="Unexpected person",
                    body="Not accounted for. Living room.",
                    zone="living_room",
                    presence_id="p4",
                    raised_at=datetime(2026, 9, 19, 21, 4, 11, 142000, tzinfo=UTC),
                    provenance=Provenance(
                        source=Source.AGENT_INFERENCE,
                        producer="agents/intruder",
                        ansname=ANSNAME["intruder"],
                        detail="presence surplus against roster and device association",
                    ),
                )
            ),
        ),
    )
```

If the helper is not named `write`, or the file builds a dict of name to model instead, follow whatever shape the neighbouring `event-context.json` entry uses. If `ANSNAME` has no `"intruder"` key, use the literal `"ans://v1.0.0.intruder.hawkeye.example"`.

- [ ] **Step 2: Regenerate and inspect**

```bash
cd app/backend && .venv/bin/python tools/gen_schema.py && cat schema/event-notice.json
```

Expected: a file whose `payload.kind` is `"notice"`, whose `payload.notice.provenance.source_class` is `"derived"`, and whose `raised_at` carries microseconds - the client decoder has to handle them, which is why the example has them.

- [ ] **Step 3: Confirm nothing else in schema/ changed**

```bash
cd app/backend && git status --short schema/
```

Expected: only `schema/event-notice.json` and possibly `schema/envelope.schema.json` (which gains the new union member). Any other file changing means the generator was edited wrongly; revert and retry.

- [ ] **Step 4: Commit**

```bash
git add app/backend/tools/gen_schema.py app/backend/schema/
git commit -m "Generate the notice schema example"
```

---

### Task 7: The iOS model and decoder

**Files:**
- Create: `app/ios/HawkEye/Models/Notice.swift`
- Modify: `app/ios/HawkEye/Services/HawkEyeClient.swift:125-176`

- [ ] **Step 1: Write the model**

Create `app/ios/HawkEye/Models/Notice.swift`:

```swift
import Foundation

/// Something the resident should know about, that is not an incident.
///
/// This is the backend's `Notice`, field for field, checked against
/// `app/backend/schema/event-notice.json`.
///
/// A notice does not raise an incident and does not dial. `app/CLAUDE.md`:
/// "An alert is information a person acts on. It is not a call."
struct Notice: Codable, Sendable, Hashable, Identifiable {

    /// How loudly to render it. Never a dispatch decision.
    enum Severity: String, Codable, Sendable, Hashable, CaseIterable {
        case info
        case attention
    }

    var noticeID: String
    var severity: Severity
    /// Short and factual. "Unexpected person".
    var title: String
    /// One line. Never contains the street address.
    var body: String
    var zone: String?
    /// Session-scoped only. We do not do person re-identification.
    var presenceID: String?
    var raisedAt: Date
    /// Required, same as every other reading. A notice from an agent that does
    /// not verify is not shown.
    var provenance: Provenance

    var id: String { noticeID }

    enum CodingKeys: String, CodingKey {
        case severity, title, body, zone, provenance
        case noticeID = "notice_id"
        case presenceID = "presence_id"
        case raisedAt = "raised_at"
    }
}
```

- [ ] **Step 2: Add the case to the event union**

In `app/ios/HawkEye/Services/HawkEyeClient.swift`, add to `enum HubEvent`, after `case context(ContextNote)`:

```swift
    case notice(Notice)
```

Add `notice` to the `CodingKeys` in the `HubEvent: Decodable` extension, changing:

```swift
        case state, phase, incident, line, instruction, result, note, code, message
```

to:

```swift
        case state, phase, incident, line, instruction, result, note, notice, code, message
```

Add the decode arm, after the `case "context":` arm:

```swift
        case "notice":
            self = .notice(try c.decode(Notice.self, forKey: .notice))
```

- [ ] **Step 3: Parse-check**

```bash
cd app/ios && swiftc -parse -swift-version 6 HawkEye/Models/Notice.swift HawkEye/Models/Provenance.swift
```

Expected: no output, exit 0.

- [ ] **Step 4: Regenerate the Xcode project**

```bash
cd app/ios && xcodegen generate
```

Expected: `Created project at .../HawkEye.xcodeproj`. This is required after adding any Swift file; the target globs `HawkEye/`.

- [ ] **Step 5: Commit**

```bash
git add app/ios/HawkEye/Models/Notice.swift app/ios/HawkEye/Services/HawkEyeClient.swift
git commit -m "Decode the notice event in the app"
```

---

### Task 8: Carry notices on both clients

**Files:**
- Modify: `app/ios/HawkEye/Services/HawkEyeClient.swift:15-45` (the `HawkEyeClienting` protocol)
- Modify: `app/ios/HawkEye/Services/LiveHawkEyeClient.swift:142-178`
- Modify: `app/ios/HawkEye/Services/MockHawkEyeClient.swift:41-48, 145-150`
- Modify: `app/ios/HawkEye/Config.swift`

- [ ] **Step 1: Add it to the protocol**

In `app/ios/HawkEye/Services/HawkEyeClient.swift`, add to `protocol HawkEyeClienting`, after the `verifications` property:

```swift
    /// Notices raised by the sensing agents, newest first.
    ///
    /// A notice is information the resident acts on. It does not raise an
    /// incident and it does not dial; a human tap still does that.
    var notices: [Notice] { get }

    /// Dismiss one. Local to this device: the notice stays in the sealed log.
    func dismissNotice(_ id: String)
```

- [ ] **Step 2: Implement on the live client**

In `app/ios/HawkEye/Services/LiveHawkEyeClient.swift`, add alongside the other `private(set) var` declarations:

```swift
    private(set) var notices: [Notice] = []
```

In the `apply(_ data: Data)` switch, add after the `case .verification(let result):` arm:

```swift
        case .notice(let notice):
            notices.removeAll { $0.id == notice.id }
            notices.insert(notice, at: 0)
```

Add the dismiss method alongside `disconnect()`:

```swift
    func dismissNotice(_ id: String) {
        notices.removeAll { $0.id == id }
    }
```

- [ ] **Step 3: Add the mock timing constant**

In `app/ios/HawkEye/Config.swift`, add after `mockIntruderIdentifiedAfter`:

```swift
    /// Seconds an unexpected presence must hold before it becomes a notice.
    ///
    /// Mirrors `HAWKEYE_NOTICE_HOLD_S` on the hub, whose default is the same 5.
    /// The mock scripts the notice rather than re-deriving the rule in Swift:
    /// the rule lives in `hawkeye_backend/notices/detector.py` and having two
    /// copies of it is how they drift.
    static let mockNoticeHoldSeconds: Double = 5
```

- [ ] **Step 4: Implement on the mock client**

In `app/ios/HawkEye/Services/MockHawkEyeClient.swift`, add alongside the other `private(set) var` declarations at line 41-48:

```swift
    private(set) var notices: [Notice] = []
```

Add the dismiss method next to the other helpers in the `// MARK: Emission helpers` section:

```swift
    func dismissNotice(_ id: String) {
        notices.removeAll { $0.id == id }
    }
```

In the sensor loop at line 145-150, immediately after `self.interior = self.state(at: self.tick)`, add:

```swift
                self.raiseNoticeIfDue()
```

Add this method to the `// MARK: Emission helpers` section:

```swift
    /// The burglary scenario's one notice.
    ///
    /// Scripted against the same elapsed-time constants the presence generator
    /// uses, so it lands `Config.mockNoticeHoldSeconds` after the intruder
    /// acquires respiration - which is what the hub's detector does with the
    /// same frames. The mock does not re-implement the rule; see
    /// `Config.mockNoticeHoldSeconds`.
    private func raiseNoticeIfDue() {
        guard Config.mockScenario == .burglary else { return }
        guard notices.isEmpty else { return }
        let due = Config.mockIntruderIdentifiedAfter + Config.mockNoticeHoldSeconds
        guard elapsed >= due else { return }
        guard let intruder = interior.presences.first(where: \.isUnexpected) else { return }

        let room = roomName(of: intruder.presenceID)
        notices.insert(
            Notice(
                noticeID: "ntc-\(intruder.presenceID)",
                severity: .attention,
                title: "Unexpected person",
                body: "Not accounted for. \(room).",
                zone: intruder.zone,
                presenceID: intruder.presenceID,
                raisedAt: Date(),
                provenance: Provenance(
                    source: .agentInference,
                    producer: "agents/intruder",
                    ansname: "ans://v1.0.0.intruder.hawkeye.example",
                    detail: "presence surplus against roster and device association"
                )
            ),
            at: 0
        )
    }
```

`elapsed` is whatever the file already uses to express seconds since the sensor loop started; if the property has another name, use that one - `intruder(since:plan:t:provenance:)` at line 306 takes it as its first argument, so read the call site in `state(at:)` and use the same expression.

Check `Provenance`'s memberwise initializer in `app/ios/HawkEye/Models/Provenance.swift` before writing this: `sourceClass` and `simulated` are computed server-side, so if the Swift struct declares them as stored properties they must be supplied here too, as `.derived` and `false`.

In `resolve()`, add `notices = []` alongside the other resets so a second run of the demo starts clean.

- [ ] **Step 5: Parse-check the whole app**

```bash
cd app/ios && find HawkEye -name '*.swift' -print0 | xargs -0 swiftc -parse -swift-version 6
```

Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add app/ios/HawkEye/Services/ app/ios/HawkEye/Config.swift
git commit -m "Carry notices on both hub clients"
```

---

### Task 9: The banner

**Files:**
- Create: `app/ios/HawkEye/Features/Home/NoticeBanner.swift`
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift:16-30`

- [ ] **Step 1: Write the banner**

Create `app/ios/HawkEye/Features/Home/NoticeBanner.swift`:

```swift
import SwiftUI

/// A notice, on the home screen.
///
/// Violet, matching `Palette.personUnexpected` and the Burglary button, because
/// the presence it describes is already drawn in that colour on the floorplan
/// and in the roster. One colour, one meaning.
///
/// It is dismissible and it does not dial. The incident buttons are three
/// controls further down the screen and still take a 1.5s hold, which is the
/// separation the whole product rests on: the system informs, a person decides.
struct NoticeBanner: View {
    let notice: Notice
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Space.sm) {
            Image(systemName: "person.fill.viewfinder")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Palette.personUnexpected)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text(notice.title)
                    .font(Typography.rowTitle)
                    .foregroundStyle(Palette.personUnexpected)
                Text(notice.body)
                    .font(Typography.rowDetail)
                    .foregroundStyle(Palette.textSecondary)
            }

            Spacer(minLength: Space.sm)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
        }
        .padding(Space.sm)
        .background(
            RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
                .fill(Palette.personUnexpected.opacity(0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
                .stroke(Palette.personUnexpected.opacity(0.42), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title). \(notice.body)")
    }
}
```

Every name used here - `Space.sm`, `Radius.card`, `Typography.rowTitle`, `Typography.rowDetail`, `Palette.textSecondary` - must exist in `app/ios/HawkEye/DesignSystem/`. Open `Layout.swift`, `Typography.swift` and `Palette.swift` first and substitute the actual token names; do not add new tokens for this.

**Do not add a haptic or a sound to this banner, now or later.** `app/CLAUDE.md`'s silent mode is
explicit that "a silent mode that still buzzes is not silent", and a burglary incident defaults to
silent precisely because a phone that buzzes gives away someone hiding. The banner as written above
is visual only, which satisfies the rule by construction; a `UIImpactFeedbackGenerator` added later
for polish would break it in the one scenario that matters most. If a future change wants feedback
here, it must be gated on there being no active burglary incident, and that gate must be tested.

- [ ] **Step 2: Render it**

In `app/ios/HawkEye/Features/Home/HomeView.swift`, inside the outer `VStack(spacing: Space.lg)` at line 17, as the first child, add:

```swift
            ForEach(model.client.notices) { notice in
                NoticeBanner(notice: notice) {
                    withAnimation(Motion.standard) {
                        model.client.dismissNotice(notice.id)
                    }
                }
                .transition(.move(edge: .top).combined(with: .opacity))
            }
```

`model` is whatever the view already calls its `AppModel`; read the property declarations at lines 8-15 and use that name. If `Motion` has no `standard`, use whichever curve the file already uses for state changes.

- [ ] **Step 3: Parse-check**

```bash
cd app/ios && find HawkEye -name '*.swift' -print0 | xargs -0 swiftc -parse -swift-version 6
```

Expected: no output, exit 0.

- [ ] **Step 4: Regenerate and build**

```bash
cd app/ios && xcodegen generate
xcodebuild -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```

Expected: `** BUILD SUCCEEDED **`.

If `xcodebuild` reports "tool 'xcodebuild' requires Xcode, but active developer directory is a command line tools instance", run `sudo xcode-select -s /Applications/Xcode.app` once and retry. If no `iPhone 17 Pro` simulator exists, pick one from `xcrun simctl list devicetypes`.

- [ ] **Step 5: Run it and look at it**

```bash
cd app/ios && xcodebuild -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
xcrun simctl boot 'iPhone 17 Pro' 2>/dev/null; open -a Simulator
```

Install and launch the built app, connect to the mock hub, and wait. Roughly ten seconds in, the violet banner must appear above the interior view, saying "Unexpected person / Not accounted for. Living room.", at the same time the fourth presence turns violet with tracking brackets on the floorplan.

Be picky about it. Check that the banner does not shove the floorplan off the bottom of the screen, that the dismiss animation is not abrupt, that the violet matches the roster row exactly, and that dismissing it does not shift the layout with a jump. Fix anything that looks off.

- [ ] **Step 6: Commit**

```bash
git add app/ios/HawkEye/Features/Home/
git commit -m "Show the notice banner on the home screen"
```

---

### Task 10: Documentation

**Files:**
- Modify: `app/CLAUDE.md`
- Modify: `app/ios/README.md`
- Modify: `docs/swapping-in-real-parts.md`

- [ ] **Step 1: Describe it in `app/CLAUDE.md`**

In the "Raising an incident" section, replace the paragraph beginning "`collapse` and `environment` still detect" with:

```markdown
`collapse`, `environment` and `intruder` still detect, and their detections surface here as
**notices**: "a fall was detected in the main bedroom four minutes ago", "an unexpected person is in
the living room". A notice is information a person acts on. It is not a call.

A notice reaches the resident two ways: a dismissible banner in the app, and an SMS through Twilio,
which is the only one of the two that arrives when the phone is locked and the app is closed.
There is deliberately no local notification. One would only fire while the app holds the socket,
which is exactly the case the resident does not need help with, and on stage it is indistinguishable
from a real push. APNs is the third sink and is not implemented; it is a driver behind
`NoticeSink`, which already exists.

The trigger rule lives in `app/backend/hawkeye_backend/notices/detector.py` and is deliberately
conservative: a confirmed person only, five seconds of continuous hold, suppressed entirely when the
baseline is unhealthy, once per presence and never again. A notice is unrecallable once it is an SMS
on someone's phone.
```

- [ ] **Step 2: Add it to `app/ios/README.md`**

Add to the list of things the app renders, in the same voice as the neighbouring entries:

```markdown
- **The notice banner.** An unexpected presence that holds for five seconds raises a `notice` event,
  and the app puts a violet banner above the interior view carrying the same words and the same
  colour as the roster row. It is dismissible, dismissal is local to the device, and the notice stays
  in the sealed log. It does not raise an incident; the three buttons below it still need a human
  hold. The mock scripts the notice off `Config.mockNoticeHoldSeconds` rather than re-deriving the
  rule in Swift, because two copies of a rule is how they drift.
```

- [ ] **Step 3: Add the seam to `docs/swapping-in-real-parts.md`**

Add a row or section, matching the file's existing format, covering:

- **What is simulated:** nothing about the notice itself. The detector runs on whatever interior state it is given, so on the mock path it fires off `ruview-sim` frames and on the live path off `nexmon-csi` frames, with no branch.
- **What is not implemented:** APNs. "The phone buzzes with the app closed" is true because of Twilio, not because of push. Say which.
- **How to flip Twilio on:** set the four `HAWKEYE_TWILIO_*` variables. How to tell it worked: the log line `notices: twilio sms sink enabled` at startup, and `twilio sent ntc-p4` when it fires.
- **The half-flipped state that looks like something else:** three of the four Twilio variables set reads as `twilio_configured == False` and logs `notices: twilio not configured, in-app banner only`. The banner still appears, so the failure looks like Twilio being slow rather than like Twilio being off. Check the startup line, not the banner.

- [ ] **Step 4: Commit**

```bash
git add app/CLAUDE.md app/ios/README.md docs/swapping-in-real-parts.md
git commit -m "Document the notice path and its seams"
```

---

## Final verification

- [ ] **Backend suite green**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: `71 passed`.

- [ ] **Schema and client agree**

```bash
cd app/backend && .venv/bin/python tools/gen_schema.py && git diff --stat schema/
```

Expected: no diff. A diff means the models changed after the example was generated.

- [ ] **App builds**

```bash
cd app/ios && xcodegen generate && xcodebuild -project HawkEye.xcodeproj -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```

Expected: `** BUILD SUCCEEDED **`.

- [ ] **One real SMS arrives**

Set the four `HAWKEYE_TWILIO_*` variables to a real trial account with your own number verified, run the hub in simulated mode, and confirm a text arrives on the phone with the app not running. This is the requirement the whole plan exists to satisfy and nothing above it proves it.

```bash
cd app/backend && HAWKEYE_MODE=simulated HAWKEYE_SIM_AUTOSTART=true .venv/bin/python -m uvicorn hawkeye_backend.main:app --port 8787
```

Expected on the phone, roughly ten seconds in:

```
Sent from your Twilio trial account - Hawk Eye: unexpected person in the living room, 21:04.
Not accounted for.
```

If nothing arrives, check in this order: the startup log says `twilio sms sink enabled`; the destination number is verified in the Twilio console; the Twilio console's Messaging logs show the attempt and its error code. A 21608 is an unverified destination number, a 30034 is unregistered A2P 10DLC.
