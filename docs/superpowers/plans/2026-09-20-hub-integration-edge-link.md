# Hub Integration: Edge Link, Live Feed, Vision Relay, Shutter Grant

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry a live camera from the Raspberry Pi to the phone, the watch and a browser through `app/backend`, and carry a signed shutter grant back the other way so a servo moves.

**Architecture:** The Pi dials one bidirectional websocket to the Mac (`WS /v1/edge/link`). JPEG frames travel up it, shutter grants travel down it. The backend holds the newest frame in `LiveCamera` and fans it out three ways: full-rate MJPEG for the phone and the browser, a 1 Hz thumbnail on the existing event stream for the watch, and a single still on demand. `vision/` stays on the Mac and reads from that same relay through a new `FrameSource`, so YOLO, Gemini and the mp4 recorder run unchanged.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest, OpenCV, websockets. Swift/SwiftUI and vanilla JS on the client side. No new dependencies beyond `websockets`, which `app/backend` already imports lazily in `master/live.py`.

**Spec:** `docs/superpowers/specs/2026-09-20-hub-integration-live-feed-design.md`

---

## Orientation for someone with no context

Read these three before Task 1. They are short.

- `app/backend/hawkeye_backend/runtime.py` - `HubRuntime.emit()` is the single funnel every event passes through: it sequences, persists and fans out. Anything that needs to reach all three apps goes through it.
- `app/backend/hawkeye_backend/models/events.py` - the websocket envelope. A tagged union discriminated on `kind`. You will add two members.
- `vision/hawkeye_vision/frames.py` - the `FrameSource` protocol. Two implementations exist. You will add a third and change nothing downstream of it.

Three project rules that will get your work rejected if you break them:

1. **Never show a stale frame as if it were live.** A frozen picture of an empty room is the most dangerous lie this system can tell. Unreachable must render as unreachable.
2. **A limit is carried in the data, not only in a comment.** If a claim is scoped to one room, the claim has a `room` field.
3. **No em dashes in any prose you write**, and one sentence per line in Markdown. Match the house style in the files around you.

### Commands you will need

```bash
# Backend tests, from the repo root
cd app/backend && .venv/bin/python -m pytest -q

# Vision tests
cd vision && python3 -m pytest -q

# Agents tests
cd agents && python -m pytest -q

# Run the backend
cd app/backend && .venv/bin/python -m hawkeye_backend.main
```

---

## File structure

**Create:**

| Path | Responsibility |
|---|---|
| `app/backend/hawkeye_backend/edge/__init__.py` | Package exports |
| `app/backend/hawkeye_backend/edge/wire.py` | The Pi-to-Mac message types. No behaviour |
| `app/backend/hawkeye_backend/edge/camera.py` | `LiveCamera`: newest frame, status, MJPEG fan-out |
| `app/backend/hawkeye_backend/edge/link.py` | The websocket endpoint and its session state machine |
| `vision/hawkeye_vision/edge.py` | The Pi-side client. Capture, encode, push |
| `vision/hawkeye_vision/relay.py` | `RelayFrameSource`: a `FrameSource` reading from the backend |
| `app/web/live/index.html` | The browser surface |
| `app/web/live/live.css` | Its styles |
| `app/web/live/live.js` | Its websocket and controls |
| `app/backend/tests/test_edge_wire.py` | Wire type tests |
| `app/backend/tests/test_edge_camera.py` | `LiveCamera` tests |
| `app/backend/tests/test_edge_link.py` | Endpoint tests |
| `app/backend/tests/test_camera_api.py` | Still and MJPEG endpoint tests |
| `app/backend/tests/test_vision_api.py` | Narration and occupancy endpoint tests |
| `app/backend/tests/test_shutter_api.py` | Shutter control tests |
| `vision/tests/test_relay.py` | `RelayFrameSource` tests |
| `scripts/check-hop.sh` | The reachability check from spec section 8 step 1 |

**Modify:**

| Path | Change |
|---|---|
| `app/backend/hawkeye_backend/models/events.py` | Add `FrameEvent`, `NarrationEvent`, `ShieldEvent` to the union |
| `app/backend/hawkeye_backend/models/hub.py` | Add `CameraStatus`, put it on `HubStatus` |
| `app/backend/hawkeye_backend/config.py` | Add edge and camera settings |
| `app/backend/hawkeye_backend/runtime.py` | Hold `LiveCamera`, run the 1 Hz thumbnail task |
| `app/backend/hawkeye_backend/api.py` | Add camera, vision, shutter and edge routes |
| `app/backend/hawkeye_backend/main.py` | Mount `app/web/live` at `/live` |
| `docs/swapping-in-real-parts.md` | Four new rows |

---

## Task 1: The edge wire types

The messages that cross `WS /v1/edge/link`. Types only, no behaviour, so every later task has something concrete to import.

Frames do **not** travel as base64. A frame is a text header message immediately followed by a binary websocket message carrying the raw JPEG. Websockets preserve order, so the pairing is reliable, and it avoids paying 33% overhead on the one thing that has to stay smooth.

**Files:**
- Create: `app/backend/hawkeye_backend/edge/__init__.py`
- Create: `app/backend/hawkeye_backend/edge/wire.py`
- Test: `app/backend/tests/test_edge_wire.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_edge_wire.py`:

```python
"""The Pi-to-Mac wire types.

These are the only shapes that cross an untrusted LAN into this process, so
they are strict: extra members are a parse failure rather than a field somebody
later reads. Same rule the claim envelope lives by.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeError,
    EdgeFrameHeader,
    EdgeGrant,
    EdgeHello,
    decode_edge_message,
)
from hawkeye_backend.models.common import Source, utc_now


def test_hello_carries_the_source_the_pi_claims():
    hello = EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC)
    assert hello.kind == "hello"
    assert hello.source is Source.CAMERA_UVC


def test_frame_header_round_trips():
    at = utc_now()
    header = EdgeFrameHeader(index=7, captured_at=at, bytes=1234)
    decoded = decode_edge_message(header.model_dump_json())
    assert isinstance(decoded, EdgeFrameHeader)
    assert decoded.index == 7
    assert decoded.bytes == 1234


def test_decode_dispatches_on_kind():
    hello = EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC)
    assert isinstance(decode_edge_message(hello.model_dump_json()), EdgeHello)

    err = EdgeError(code="camera_lost", message="device went away")
    assert isinstance(decode_edge_message(err.model_dump_json()), EdgeError)


def test_an_unknown_kind_is_refused_not_guessed():
    with pytest.raises(ValidationError):
        decode_edge_message('{"kind": "something_else"}')


def test_smuggled_members_are_a_parse_failure():
    """Same rule as the claim envelope: extra="forbid", not charitable reading."""
    with pytest.raises(ValidationError):
        decode_edge_message(
            '{"kind": "hello", "edge_id": "pi-01", "source": "camera-uvc", "admin": true}'
        )


def test_a_frame_header_claiming_zero_bytes_is_refused():
    """A header promising no payload has no honest meaning and would desync the
    pairing between header and binary message."""
    with pytest.raises(ValidationError):
        EdgeFrameHeader(index=1, captured_at=utc_now(), bytes=0)


def test_grant_carries_the_signed_string_opaquely():
    """The bytes that were signed must be the bytes that are verified, so the
    grant crosses as an opaque string and is never re-serialized on the way."""
    grant = EdgeGrant(grant_json='{"nonce":"chal-1"}', request_id="req-1")
    assert grant.grant_json == '{"nonce":"chal-1"}'


def test_attestation_carries_the_request_it_answers():
    att = EdgeAttestation(
        request_id="req-1", attestation_json='{"position":"open"}', refused=False
    )
    assert att.request_id == "req-1"
    assert att.refused is False
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_wire.py -q
```

Expected: collection error, `ModuleNotFoundError: No module named 'hawkeye_backend.edge'`.

- [ ] **Step 3: Write the implementation**

Create `app/backend/hawkeye_backend/edge/__init__.py`:

```python
"""The Pi-to-Mac edge link.

The Pi holds the camera and the servo and nothing else. It dials this process
over one websocket, pushes JPEG frames up it, and receives shutter grants back
down it.

The Pi dials out rather than serving, so nothing here ever has to discover the
Pi's address. It is a headless box whose DHCP lease moves every time the network
changes, and the only two things it needs to know about the world are a WiFi
password and this hub's mDNS name.
"""

from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeError,
    EdgeFrameHeader,
    EdgeGrant,
    EdgeHello,
    EdgeMessage,
    decode_edge_message,
)

__all__ = [
    "EdgeAttestation",
    "EdgeError",
    "EdgeFrameHeader",
    "EdgeGrant",
    "EdgeHello",
    "EdgeMessage",
    "LiveCamera",
    "decode_edge_message",
]
```

Create `app/backend/hawkeye_backend/edge/wire.py`:

```python
"""What crosses the edge link, in both directions.

These are the only shapes that reach this process from an untrusted LAN, so
they follow the same rules the claim envelope already lives by:

- **`extra="forbid"`.** A message carrying smuggled members is a parse failure,
  not a field somebody reads later by accident.
- **An unknown `kind` is refused**, never read charitably into the nearest
  matching shape.
- **A signed string crosses opaquely.** `EdgeGrant.grant_json` is a string and
  never a nested object, because any layer that parses and re-serializes it
  breaks the signature, and that failure is indistinguishable from tampering.

A frame does not travel in any of these. A frame is an `EdgeFrameHeader` text
message immediately followed by a binary websocket message carrying the raw
JPEG bytes. Websockets preserve ordering, so the pairing holds, and the frame
never pays base64's 33% overhead on the one path that has to stay smooth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from hawkeye_backend.models.common import Source, utc_now


class _Strict(BaseModel):
    """Every wire type forbids extras. Stated once."""

    model_config = ConfigDict(extra="forbid")


class EdgeHello(_Strict):
    """First message on every link. Says which Pi, and what it is looking through."""

    kind: Literal["hello"] = "hello"
    edge_id: str = Field(min_length=1, description="Which physical edge box this is.")
    source: Source = Field(
        description=(
            "What is actually producing frames. `camera-uvc` is the Brio, "
            "`replay-video` is a file being replayed through the same path. This is "
            "what stops a video file presenting as a camera, and it is carried "
            "rather than assumed for exactly that reason."
        )
    )
    note: str = ""


class EdgeFrameHeader(_Strict):
    """Describes the binary message that follows it. Never carries the frame itself."""

    kind: Literal["frame"] = "frame"
    index: int = Field(ge=0, description="Monotonic per link. A gap means frames were dropped.")
    captured_at: datetime = Field(
        description=(
            "When the camera took it, stamped on the Pi. Not when it arrived here. "
            "The two differ by the link's latency and the difference is the whole "
            "point of reporting frame age honestly."
        )
    )
    bytes: int = Field(gt=0, description="Length of the binary message that follows.")


class EdgeError(_Strict):
    """The Pi reporting that it cannot do its job. Surfaced, never swallowed."""

    kind: Literal["error"] = "error"
    code: str
    message: str
    at: datetime = Field(default_factory=utc_now)


class EdgeGrant(_Strict):
    """Mac to Pi. A signed shutter grant, to be forwarded to the local shutter agent.

    `grant_json` is opaque here and stays opaque all the way to `shutter`, which
    verifies the signature over exactly these bytes. Nothing on this path may
    parse and re-serialize it.
    """

    kind: Literal["grant"] = "grant"
    request_id: str = Field(min_length=1, description="Echoed back on the attestation.")
    grant_json: str = Field(min_length=1)


class EdgeAttestation(_Strict):
    """Pi to Mac. What the shutter said after being asked to move.

    `refused` is a first-class outcome rather than an error. A shutter refusing a
    grant it cannot verify is the system working, and it is the thing this
    project most wants to be able to show.
    """

    kind: Literal["attestation"] = "attestation"
    request_id: str = Field(min_length=1)
    attestation_json: str = ""
    refused: bool = False
    refusal_reason: str = ""


EdgeMessage = Annotated[
    EdgeHello | EdgeFrameHeader | EdgeError | EdgeGrant | EdgeAttestation,
    Field(discriminator="kind"),
]

_EdgeMessageAdapter: TypeAdapter[EdgeMessage] = TypeAdapter(EdgeMessage)


def decode_edge_message(raw: str | bytes) -> EdgeMessage:
    """Parse one text message off the link, or raise `ValidationError`.

    Raises rather than returning None. A message this process cannot understand
    arriving on the link that moves a physical shield is not a condition to
    shrug at, and the caller closes the link on it.
    """
    return _EdgeMessageAdapter.validate_json(raw)
```

- [ ] **Step 4: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_wire.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backend/hawkeye_backend/edge/ app/backend/tests/test_edge_wire.py
git commit -m "Define what crosses the edge link, in both directions"
```

---

## Task 2: `LiveCamera`

Holds the newest frame, reports honestly on how old it is, and fans out to MJPEG consumers.

**Files:**
- Create: `app/backend/hawkeye_backend/edge/camera.py`
- Modify: `app/backend/hawkeye_backend/models/hub.py`
- Test: `app/backend/tests/test_edge_camera.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_edge_camera.py`:

```python
"""LiveCamera: the newest frame, and the truth about its age.

The rule under test throughout: a stale frame is never served as a live one. A
frozen picture of an empty room is the most dangerous output this system has.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.models.common import Source, utc_now

JPEG = b"\xff\xd8\xff\xe0not-really-a-jpeg\xff\xd9"


def test_a_new_camera_is_unlinked_and_says_so():
    camera = LiveCamera()
    status = camera.status()
    assert status.linked is False
    assert status.last_frame_age_s is None
    assert "no edge" in status.detail.lower()


def test_accepting_a_frame_makes_it_the_latest():
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    camera.accept(JPEG, index=0, captured_at=utc_now())

    latest = camera.latest
    assert latest is not None
    assert latest.jpeg == JPEG
    assert latest.index == 0


def test_status_reports_the_source_the_edge_claimed():
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.REPLAY_VIDEO)
    camera.accept(JPEG, index=0, captured_at=utc_now())
    assert camera.status().source is Source.REPLAY_VIDEO


def test_a_frame_older_than_the_stale_window_reads_as_stale():
    camera = LiveCamera(stale_after_s=2.0)
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    camera.accept(JPEG, index=0, captured_at=utc_now() - timedelta(seconds=30))

    status = camera.status()
    assert status.live is False
    assert status.last_frame_age_s is not None
    assert status.last_frame_age_s > 2.0
    assert "stale" in status.detail.lower()


def test_a_fresh_frame_reads_as_live():
    camera = LiveCamera(stale_after_s=2.0)
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    camera.accept(JPEG, index=0, captured_at=utc_now())
    assert camera.status().live is True


def test_closing_the_link_does_not_erase_the_last_frame_but_does_end_live():
    """The frame is still useful as the last thing seen. It is just no longer
    presentable as current, and the status is what says so."""
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    camera.accept(JPEG, index=0, captured_at=utc_now())
    camera.link_closed("edge disconnected")

    assert camera.latest is not None
    status = camera.status()
    assert status.linked is False
    assert status.live is False


def test_a_gap_in_frame_indices_is_counted_as_dropped():
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    camera.accept(JPEG, index=0, captured_at=utc_now())
    camera.accept(JPEG, index=5, captured_at=utc_now())
    assert camera.status().frames_dropped == 4


@pytest.mark.asyncio
async def test_a_subscriber_receives_frames_accepted_after_it_subscribed():
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    sub = await camera.subscribe()
    camera.accept(JPEG, index=0, captured_at=utc_now())

    got = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert got.jpeg == JPEG
    await camera.unsubscribe(sub)


@pytest.mark.asyncio
async def test_a_slow_subscriber_is_dropped_rather_than_blocking_the_camera():
    """Same rule EventBus already applies. During an incident a stale frame is
    worthless and blocking the camera on one slow consumer is unacceptable."""
    camera = LiveCamera()
    camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    sub = await camera.subscribe(buffer=2)

    for i in range(10):
        camera.accept(JPEG, index=i, captured_at=utc_now())

    assert sub.dropped > 0
    assert sub.queue.qsize() <= 2
    await camera.unsubscribe(sub)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_camera.py -q
```

Expected: `ModuleNotFoundError: No module named 'hawkeye_backend.edge.camera'`.

- [ ] **Step 3: Add `CameraStatus` to the hub model**

Append to `app/backend/hawkeye_backend/models/hub.py`:

```python
class CameraStatus(BaseModel):
    """Whether there is a camera, and whether what it last sent is current.

    `linked` and `live` are deliberately two fields rather than one. A link that
    is up while frames have stopped arriving is a real and distinct failure, and
    collapsing it into one boolean would let a stalled camera read as a
    disconnected one, which is a different repair.

    `live` false means the app must not present the last frame as current. That
    is the whole reason this model exists: a frozen picture of an empty room is
    the most dangerous thing this system can put on a screen.
    """

    linked: bool = Field(description="Is an edge box connected right now.")
    live: bool = Field(description="Is the newest frame recent enough to present as current.")
    edge_id: str | None = None
    source: Source | None = Field(
        default=None,
        description="What the edge claims is producing frames. A video file must not read as a camera.",
    )
    last_frame_age_s: float | None = Field(
        default=None, description="Seconds since the newest frame was captured. None if never."
    )
    fps: float = Field(default=0.0, description="Frames per second over the last ten seconds.")
    frames_received: int = 0
    frames_dropped: int = Field(
        default=0, description="Inferred from gaps in the edge's frame index."
    )
    detail: str = Field(description="One sentence, written to be printed on a console.")
```

Add `Source` to that file's imports if it is not already there:

```python
from hawkeye_backend.models.common import Source
```

Then add the field to `HubStatus` (find the class in the same file and add this alongside `sensor`):

```python
    camera: CameraStatus = Field(
        description=(
            "The camera's own health, separate from the radio's. The Connect screen "
            "and the live view both read it, and an unreachable camera must render "
            "as unreachable rather than as a still room."
        )
    )
```

- [ ] **Step 4: Write `LiveCamera`**

Create `app/backend/hawkeye_backend/edge/camera.py`:

```python
"""The newest frame off the edge link, and everything that wants a copy of it.

One producer (whichever edge link is connected), three kinds of consumer:
full-rate MJPEG for the phone and the browser, a 1 Hz thumbnail on the event
stream for the watch, and a single still on demand.

A slow consumer is dropped rather than allowed to back up the camera, which is
the same rule `EventBus` already applies to slow websocket subscribers and for
the same reason: during an incident a stale frame is worthless, and blocking the
camera on a phone that went to sleep is unacceptable.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from hawkeye_backend.models.common import Source, utc_now
from hawkeye_backend.models.hub import CameraStatus

logger = logging.getLogger(__name__)

#: Frames older than this are not presentable as current. Generous relative to
#: any real capture rate, so this fires on a genuinely stalled camera rather
#: than on one slow frame.
DEFAULT_STALE_AFTER_S = 3.0

#: Window the reported frame rate is measured over.
FPS_WINDOW_S = 10.0

#: Default per-subscriber buffer for MJPEG. Small on purpose: a consumer that
#: has fallen three frames behind wants the newest frame, not the backlog.
DEFAULT_SUBSCRIBER_BUFFER = 4


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """One JPEG, and when the camera took it."""

    jpeg: bytes
    index: int
    captured_at: datetime


class FrameSubscription:
    """One MJPEG consumer's queue."""

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[CapturedFrame] = asyncio.Queue(maxsize=maxsize)
        self.dropped: int = 0


class LiveCamera:
    """Holds the newest frame and tells the truth about how old it is."""

    def __init__(self, stale_after_s: float = DEFAULT_STALE_AFTER_S) -> None:
        self._stale_after_s = stale_after_s
        self._latest: CapturedFrame | None = None
        self._subscribers: set[FrameSubscription] = set()
        self._linked = False
        self._edge_id: str | None = None
        self._source: Source | None = None
        self._frames_received = 0
        self._frames_dropped = 0
        self._next_index = 0
        self._detail = "No edge camera has connected yet."
        #: Arrival times inside the fps window.
        self._arrivals: deque[datetime] = deque()

    # ------------------------------------------------------------- link state

    def link_opened(self, *, edge_id: str, source: Source) -> None:
        self._linked = True
        self._edge_id = edge_id
        self._source = source
        self._next_index = 0
        self._detail = f"Edge camera {edge_id} connected, reporting source {source.value}."
        logger.info("%s", self._detail)

    def link_closed(self, reason: str) -> None:
        """The edge went away. The last frame is kept; `live` is what goes false.

        Keeping the frame is deliberate. It is still a true statement about the
        last thing the camera saw, and the status is what stops it being
        presented as the current one.
        """
        self._linked = False
        self._detail = f"Edge camera disconnected: {reason}"
        logger.warning("%s", self._detail)

    # ----------------------------------------------------------------- frames

    def accept(self, jpeg: bytes, *, index: int, captured_at: datetime) -> None:
        """Take one frame from the link and hand it to every consumer."""
        if index > self._next_index:
            self._frames_dropped += index - self._next_index
        self._next_index = index + 1
        self._frames_received += 1

        frame = CapturedFrame(jpeg=jpeg, index=index, captured_at=captured_at)
        self._latest = frame

        now = utc_now()
        self._arrivals.append(now)
        while self._arrivals and (now - self._arrivals[0]).total_seconds() > FPS_WINDOW_S:
            self._arrivals.popleft()

        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(frame)
            except asyncio.QueueFull:
                sub.dropped += 1

    @property
    def latest(self) -> CapturedFrame | None:
        """The newest frame, or None if none has ever arrived.

        Callers must consult `status().live` before presenting this as current.
        """
        return self._latest

    # ------------------------------------------------------------ subscribers

    async def subscribe(self, buffer: int = DEFAULT_SUBSCRIBER_BUFFER) -> FrameSubscription:
        sub = FrameSubscription(buffer)
        self._subscribers.add(sub)
        logger.info("camera subscriber joined (%d total)", len(self._subscribers))
        return sub

    async def unsubscribe(self, sub: FrameSubscription) -> None:
        self._subscribers.discard(sub)
        logger.info("camera subscriber left (%d total)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ----------------------------------------------------------------- status

    def status(self) -> CameraStatus:
        age: float | None = None
        if self._latest is not None:
            age = (utc_now() - self._latest.captured_at).total_seconds()

        live = self._linked and age is not None and age <= self._stale_after_s

        detail = self._detail
        if self._linked and age is not None and age > self._stale_after_s:
            detail = (
                f"Edge camera {self._edge_id} is connected but its newest frame is "
                f"{age:.1f}s old, which is stale. Not presentable as current."
            )
        elif live:
            detail = (
                f"Edge camera {self._edge_id} live at {self._fps():.1f} fps, "
                f"newest frame {age:.1f}s old."
            )

        return CameraStatus(
            linked=self._linked,
            live=live,
            edge_id=self._edge_id,
            source=self._source,
            last_frame_age_s=round(age, 3) if age is not None else None,
            fps=round(self._fps(), 2),
            frames_received=self._frames_received,
            frames_dropped=self._frames_dropped,
            detail=detail,
        )

    def _fps(self) -> float:
        if len(self._arrivals) < 2:
            return 0.0
        span = (self._arrivals[-1] - self._arrivals[0]).total_seconds()
        if span <= 0:
            return 0.0
        return (len(self._arrivals) - 1) / span
```

- [ ] **Step 5: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_camera.py -q
```

Expected: 9 passed. If `test_a_new_camera_is_unlinked_and_says_so` fails on the detail string, the message is `"No edge camera has connected yet."` and the assertion lowercases it, so check for a typo rather than changing the assertion.

- [ ] **Step 6: Run the whole backend suite**

`HubStatus` gained a required field, so anything constructing one directly will now fail. That is the point of running this now rather than in Task 6.

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Fix every failure by passing a `CameraStatus` in. Where a test just needs a placeholder:

```python
from hawkeye_backend.models.hub import CameraStatus

CameraStatus(linked=False, live=False, detail="No edge camera has connected yet.")
```

- [ ] **Step 7: Commit**

```bash
git add app/backend/hawkeye_backend/edge/camera.py \
        app/backend/hawkeye_backend/models/hub.py \
        app/backend/tests/
git commit -m "Hold the newest camera frame, and say honestly how old it is"
```

---

## Task 3: The edge link endpoint

`WS /v1/edge/link`. The Pi dials it, authenticates with a shared secret, sends `hello`, then header-plus-binary frame pairs.

**Files:**
- Create: `app/backend/hawkeye_backend/edge/link.py`
- Modify: `app/backend/hawkeye_backend/config.py`
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Modify: `app/backend/hawkeye_backend/api.py`
- Test: `app/backend/tests/test_edge_link.py`

- [ ] **Step 1: Add the settings**

In `app/backend/hawkeye_backend/config.py`, add inside `Settings`, after the `replay_archive` field:

```python
    # The edge link. The Pi holds the camera and the servo and dials this
    # process; nothing here ever dials the Pi. It is headless and its lease
    # moves, so the only address in this system is this hub's own.
    #
    # The token is not optional theatre. Without it any host on the same WiFi
    # could inject frames into the camera feed, and the camera feed is the one
    # surface a human is asked to believe.
    edge_token: SecretStr = SecretStr("")

    # Frames older than this are not presentable as current. See
    # hawkeye_backend/edge/camera.py.
    camera_stale_after_s: float = 3.0

    # How often a thumbnail is pushed onto the event stream for the watch.
    # Deliberately slow: it is a wrist, not a monitor.
    camera_thumbnail_interval_s: float = 1.0

    # Long edge of that thumbnail, in pixels.
    camera_thumbnail_long_edge: int = 320
```

Add this property next to `twilio_configured`:

```python
    @property
    def edge_configured(self) -> bool:
        """True when the edge link can actually authenticate anyone.

        An empty token means the link refuses every connection rather than
        accepting every connection. A camera feed that anyone on the WiFi can
        write to is worse than no camera feed.
        """
        return bool(self.edge_token.get_secret_value())
```

- [ ] **Step 2: Write the failing test**

Create `app/backend/tests/test_edge_link.py`:

```python
"""The edge link endpoint.

Everything here is about what the link refuses. The link is the one door this
process opens onto an untrusted LAN, and it is also the door a shutter grant
leaves by, so the refusals are the feature.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.edge.wire import EdgeFrameHeader, EdgeHello
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source, utc_now

JPEG = b"\xff\xd8\xff\xe0not-really-a-jpeg\xff\xd9"
TOKEN = "test-edge-token"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        mode="simulated",
        edge_token=TOKEN,
        sim_autostart=False,
        replay_site_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_the_link_refuses_a_connection_with_no_token(client: TestClient):
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/edge/link"):
            pass


def test_the_link_refuses_a_wrong_token(client: TestClient):
    with pytest.raises(Exception):
        with client.websocket_connect("/v1/edge/link?token=not-the-token"):
            pass


def test_a_frame_sent_up_the_link_becomes_the_latest_frame(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as ws:
        ws.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        header = EdgeFrameHeader(index=0, captured_at=utc_now(), bytes=len(JPEG))
        ws.send_text(header.model_dump_json())
        ws.send_bytes(JPEG)

        # The still endpoint is the cheapest way to observe that it landed.
        response = client.get("/v1/camera/still")

    assert response.status_code == 200
    assert response.content == JPEG


def test_a_binary_message_with_no_header_before_it_is_refused(client: TestClient):
    """The pairing between header and payload is what keeps frames honest about
    when they were taken. An unpaired payload has no timestamp and is dropped
    rather than stamped with arrival time."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as ws:
        ws.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        ws.send_bytes(JPEG)
        error = ws.receive_json()

    assert error["kind"] == "error"
    assert error["code"] == "unpaired_payload"


def test_a_payload_whose_length_contradicts_its_header_is_refused(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as ws:
        ws.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        ws.send_text(
            EdgeFrameHeader(index=0, captured_at=utc_now(), bytes=999999).model_dump_json()
        )
        ws.send_bytes(JPEG)
        error = ws.receive_json()

    assert error["kind"] == "error"
    assert error["code"] == "length_mismatch"


def test_a_frame_before_hello_is_refused(client: TestClient):
    """Until the edge says what it is looking through, a frame cannot be
    labelled, and an unlabelled frame could be a video file presenting as a
    camera."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as ws:
        ws.send_text(
            EdgeFrameHeader(index=0, captured_at=utc_now(), bytes=len(JPEG)).model_dump_json()
        )
        error = ws.receive_json()

    assert error["kind"] == "error"
    assert error["code"] == "no_hello"


def test_the_hub_reports_the_camera_as_unlinked_after_the_edge_goes_away(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as ws:
        ws.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

    status = client.get("/v1/hub").json()
    assert status["camera"]["linked"] is False
    assert status["camera"]["live"] is False


def test_an_unconfigured_token_refuses_every_connection(monkeypatch):
    """Empty token means closed, never open. A camera feed anyone on the WiFi
    can write to is worse than no camera feed."""
    settings = Settings(mode="simulated", edge_token="", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/v1/edge/link?token=anything"):
                pass
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_link.py -q
```

Expected: every test fails, most with a 403 or 404 on the websocket route.

- [ ] **Step 4: Put `LiveCamera` on the runtime**

In `app/backend/hawkeye_backend/runtime.py`, add the import:

```python
from hawkeye_backend.edge.camera import LiveCamera
```

In `HubRuntime.__init__`, after `self.archive` is assigned:

```python
        # The newest camera frame and everyone who wants a copy. Owned by the
        # runtime rather than by the endpoint, because it outlives any one
        # websocket: the edge reconnecting must not reset what the phone sees.
        self.camera = LiveCamera(stale_after_s=settings.camera_stale_after_s)
```

- [ ] **Step 5: Write the endpoint**

Create `app/backend/hawkeye_backend/edge/link.py`:

```python
"""The websocket the Pi dials, and the state machine behind it.

Reading order for the refusals, because they are the substance of this file:

- **No token, wrong token, or no token configured** closes the connection before
  a single byte is read. Closed by default, never open by default.
- **A frame before `hello`** is refused, because until the edge says what it is
  looking through, the frame cannot be labelled, and an unlabelled frame could
  be a video file presenting as a camera.
- **A binary message with no header before it** is refused rather than stamped
  with arrival time. Arrival time is not capture time, and quietly substituting
  one for the other is how a frame starts lying about when it was taken.
- **A payload whose length contradicts its header** is refused, because the two
  disagreeing means the stream has desynchronized and every subsequent pairing
  is guesswork.

Every refusal is reported back down the link as an `EdgeError` before the
connection closes, so the Pi's log says what happened rather than just
"disconnected".
"""

from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeError,
    EdgeFrameHeader,
    EdgeHello,
    decode_edge_message,
)
from hawkeye_backend.runtime import HubRuntime

logger = logging.getLogger(__name__)

#: Sent instead of an HTTP status, because a websocket handshake has no body to
#: put a reason in. 4401 is in the private-use range and means "bad token".
CLOSE_UNAUTHORIZED = 4401
CLOSE_PROTOCOL = 4400


async def run_edge_link(websocket: WebSocket, runtime: HubRuntime, token: str | None) -> None:
    """Serve one edge connection for its lifetime."""
    configured = runtime.settings.edge_token.get_secret_value()
    if not configured:
        logger.warning(
            "edge link: refused a connection because HAWKEYE_EDGE_TOKEN is not set. "
            "An unauthenticated camera feed is worse than no camera feed."
        )
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="edge token not configured")
        return
    if token != configured:
        logger.warning("edge link: refused a connection presenting a bad token")
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="bad token")
        return

    await websocket.accept()
    runtime.edge = websocket
    hello: EdgeHello | None = None
    pending: EdgeFrameHeader | None = None
    reason = "closed"

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                reason = "edge disconnected"
                break

            if (payload := message.get("bytes")) is not None:
                if hello is None:
                    await _refuse(websocket, "no_hello", "a frame arrived before hello")
                    reason = "frame before hello"
                    break
                if pending is None:
                    await _refuse(
                        websocket,
                        "unpaired_payload",
                        "a binary message arrived with no frame header before it",
                    )
                    reason = "unpaired payload"
                    break
                if len(payload) != pending.bytes:
                    await _refuse(
                        websocket,
                        "length_mismatch",
                        f"header promised {pending.bytes} bytes, payload carried {len(payload)}",
                    )
                    reason = "length mismatch"
                    break

                runtime.camera.accept(
                    payload, index=pending.index, captured_at=pending.captured_at
                )
                pending = None
                continue

            raw = message.get("text")
            if raw is None:
                continue

            try:
                decoded = decode_edge_message(raw)
            except ValidationError as exc:
                await _refuse(websocket, "malformed", f"unparseable message: {exc.error_count()} errors")
                reason = "malformed message"
                break

            match decoded:
                case EdgeHello():
                    hello = decoded
                    runtime.camera.link_opened(edge_id=decoded.edge_id, source=decoded.source)
                case EdgeFrameHeader():
                    if hello is None:
                        await _refuse(websocket, "no_hello", "a frame arrived before hello")
                        reason = "frame before hello"
                        break
                    pending = decoded
                case EdgeAttestation():
                    runtime.resolve_attestation(decoded)
                case EdgeError():
                    logger.warning(
                        "edge link: the edge reported %s: %s", decoded.code, decoded.message
                    )
                case _:
                    # EdgeGrant travels the other way. Receiving one means the
                    # far end is confused about which side it is, and that is
                    # worth saying rather than ignoring.
                    await _refuse(websocket, "wrong_direction", "that message only travels downward")
                    reason = "wrong direction"
                    break

    except WebSocketDisconnect:
        reason = "edge disconnected"
    except Exception:
        logger.exception("edge link: unexpected failure")
        reason = "internal error"
    finally:
        runtime.edge = None
        runtime.camera.link_closed(reason)


async def _refuse(websocket: WebSocket, code: str, message: str) -> None:
    """Say why before hanging up, so the Pi's log is not just 'disconnected'."""
    logger.warning("edge link: refusing (%s) %s", code, message)
    try:
        await websocket.send_text(EdgeError(code=code, message=message).model_dump_json())
        await websocket.close(code=CLOSE_PROTOCOL, reason=code)
    except Exception:
        logger.debug("edge link: could not deliver the refusal, the socket was already gone")
```

- [ ] **Step 6: Give the runtime the edge handle and the attestation hook**

In `app/backend/hawkeye_backend/runtime.py`, add to `HubRuntime.__init__` right after `self.camera`:

```python
        # The connected edge websocket, when there is one. Held so a shutter
        # grant has somewhere to go. `None` is the honest answer when the Pi is
        # not there, and the shutter endpoint says so rather than timing out.
        self.edge: object | None = None
        #: request_id -> the future waiting on that attestation.
        self._pending_attestations: dict[str, asyncio.Future[object]] = {}
```

Add these two methods to `HubRuntime`, after `emit_notice`:

```python
    def resolve_attestation(self, attestation: object) -> None:
        """Hand an attestation back to whoever asked for the move.

        Called from the edge link's receive loop. Unknown request ids are logged
        and dropped rather than raising: an attestation arriving after its
        caller gave up is stale, not dangerous.
        """
        request_id = getattr(attestation, "request_id", "")
        future = self._pending_attestations.pop(request_id, None)
        if future is None:
            logger.warning(
                "attestation for unknown request %r, dropped. Its caller has "
                "already given up.",
                request_id,
            )
            return
        if not future.done():
            future.set_result(attestation)

    def await_attestation(self, request_id: str) -> "asyncio.Future[object]":
        """Register interest in an attestation before the grant is sent."""
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending_attestations[request_id] = future
        return future
```

- [ ] **Step 7: Route it**

In `app/backend/hawkeye_backend/api.py`, add the import near the top:

```python
from hawkeye_backend.edge.link import run_edge_link
```

Add this route at the end of the file:

```python
@router.websocket("/edge/link")
async def edge_link(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    """The websocket the Pi dials. Frames up, shutter grants down.

    The Pi dials out rather than serving so that nothing in this system ever has
    to discover the Pi's address. It is headless and its DHCP lease moves every
    time the network changes; the only address anything needs is this hub's own.
    """
    runtime: HubRuntime = websocket.app.state.runtime
    await run_edge_link(websocket, runtime, token)
```

Add the still endpoint just above it:

```python
@router.get("/camera/still", summary="The newest camera frame", response_class=Response)
async def get_camera_still(request: Request) -> Response:
    """One JPEG, or a 503 naming why there isn't one.

    503 rather than a placeholder image, deliberately. A caller that gets bytes
    back must be able to treat them as a real frame; handing back a grey
    rectangle on failure would make every consumer responsible for telling the
    two apart, and one of them would get it wrong.

    A stale frame is still served, because it is a true statement about the last
    thing the camera saw. `X-HawkEye-Frame-Age` and `X-HawkEye-Live` say what it
    is, and the live view reads them.
    """
    runtime = _runtime(request)
    frame = runtime.camera.latest
    status = runtime.camera.status()
    if frame is None:
        raise HTTPException(status_code=503, detail=status.detail)
    return Response(
        content=frame.jpeg,
        media_type="image/jpeg",
        headers={
            "X-HawkEye-Frame-Age": f"{status.last_frame_age_s:.3f}",
            "X-HawkEye-Live": "true" if status.live else "false",
            "Cache-Control": "no-store",
        },
    )
```

Finally, put the camera on `GET /v1/hub`. In `get_hub`, add to the `HubStatus(...)` construction:

```python
        camera=runtime.camera.status(),
```

- [ ] **Step 8: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_edge_link.py -q
```

Expected: 8 passed.

- [ ] **Step 9: Run the whole suite**

```bash
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add app/backend/hawkeye_backend/ app/backend/tests/test_edge_link.py
git commit -m "Open the door the Pi dials, and name every reason it closes"
```

---

## Task 4: The Pi-side edge client

**Files:**
- Create: `vision/hawkeye_vision/edge.py`
- Create: `scripts/check-hop.sh`

- [ ] **Step 1: Write the client**

Create `vision/hawkeye_vision/edge.py`:

```python
"""What runs on the Pi. Capture, encode, push. Nothing else.

This module exists so the Pi never has to run a model. A Pi 4B takes roughly a
second per frame on YOLO11m and the timing budget in the root CLAUDE.md is three
seconds end to end, so the tracker lives on the Mac and this ships it pixels.

Run it:

    python -m hawkeye_vision.edge --hub ws://hawkeye-hub.local:8787 --token "$HAWKEYE_EDGE_TOKEN"

It dials out and keeps dialling. The hub never dials the Pi, because the Pi is
headless and its address moves every time the network changes, and the only
thing this box needs to know about the world is where the hub is.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from hawkeye_backend.edge.wire import EdgeError, EdgeFrameHeader, EdgeHello
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import FrameSource
from hawkeye_vision.narrate import encode_jpeg

logger = logging.getLogger(__name__)

#: Long edge of a pushed frame. Larger than the narration thumbnail because
#: this is what a human watches, not what a model samples.
EDGE_LONG_EDGE = 960
EDGE_JPEG_QUALITY = 70

#: Reconnect backoff bounds. The ceiling is low on purpose: this link coming
#: back within a few seconds of the network returning is worth more than being
#: polite to a hub that is down.
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 10.0


def open_source(kind: str, index: int, path: str | None) -> FrameSource:
    """Build the frame source named on the command line.

    `kind` is explicit rather than inferred, because the whole point of
    `FrameSource.source` is that a video file must not be able to present itself
    as a camera by accident.
    """
    if kind == "camera":
        from hawkeye_vision.webcam import MacCamera

        return MacCamera(index=index)
    if kind == "fixture":
        from hawkeye_vision.fixture import FileFixture

        if not path:
            raise SystemExit("--source fixture needs --path")
        return FileFixture(path)
    raise SystemExit(f"unknown source: {kind!r}. Use 'camera' or 'fixture'.")


async def pump(url: str, token: str, edge_id: str, source: FrameSource, fps: float) -> None:
    """Dial the hub and push frames until cancelled. Reconnects forever."""
    import websockets

    backoff = BACKOFF_START_S
    interval = 1.0 / fps if fps > 0 else 0.0

    while True:
        try:
            async with websockets.connect(f"{url}/v1/edge/link?token={token}") as socket:
                logger.info("edge: connected to %s", url)
                backoff = BACKOFF_START_S

                await socket.send(
                    EdgeHello(edge_id=edge_id, source=source.source).model_dump_json()
                )

                # The receive side runs alongside the push so a grant arriving
                # downward is not stuck behind the next frame going up.
                receiver = asyncio.create_task(_receive(socket))
                try:
                    for frame in source.frames():
                        jpeg = encode_jpeg(
                            frame.image,
                            long_edge=EDGE_LONG_EDGE,
                            quality=EDGE_JPEG_QUALITY,
                        )
                        header = EdgeFrameHeader(
                            index=frame.index,
                            captured_at=frame.captured_at,
                            bytes=len(jpeg),
                        )
                        await socket.send(header.model_dump_json())
                        await socket.send(jpeg)
                        if interval:
                            await asyncio.sleep(interval)
                finally:
                    receiver.cancel()

        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reconnect on anything
            logger.warning("edge: link dropped (%s); retrying in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)


async def _receive(socket) -> None:  # noqa: ANN001 - websockets client protocol
    """Handle everything the hub sends down. Today that is grants and errors."""
    from hawkeye_backend.edge.wire import decode_edge_message

    async for raw in socket:
        if isinstance(raw, bytes):
            logger.warning("edge: the hub sent binary, which it never should. Ignored.")
            continue
        try:
            message = decode_edge_message(raw)
        except Exception:
            logger.exception("edge: the hub sent something unparseable")
            continue
        if isinstance(message, EdgeError):
            logger.error("edge: the hub refused us (%s): %s", message.code, message.message)
            continue
        # Grants are handled in Task 11. Logged until then so the wiring is
        # visible rather than silently dropped.
        logger.info("edge: received %s from the hub", message.kind)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push camera frames to the Hawk Eye hub.")
    parser.add_argument("--hub", default=os.environ.get("HAWKEYE_HUB_URL", "ws://hawkeye-hub.local:8787"))
    parser.add_argument("--token", default=os.environ.get("HAWKEYE_EDGE_TOKEN", ""))
    parser.add_argument("--edge-id", default=os.environ.get("HAWKEYE_EDGE_ID", "pi-01"))
    parser.add_argument("--source", default="camera", choices=("camera", "fixture"))
    parser.add_argument("--index", type=int, default=0, help="Camera index. 0 is the Brio.")
    parser.add_argument("--path", default=None, help="Video file, for --source fixture.")
    parser.add_argument("--fps", type=float, default=10.0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    if not args.token:
        # Refusing here rather than connecting and being refused is a better
        # error: it names the missing variable instead of reporting a 4401.
        logger.error("no token. Set HAWKEYE_EDGE_TOKEN or pass --token.")
        return 2

    source = open_source(args.source, args.index, args.path)
    try:
        asyncio.run(pump(args.hub, args.token, args.edge_id, source, args.fps))
    except KeyboardInterrupt:
        logger.info("edge: stopped")
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the reachability check**

This is spec section 8 step 1 and it is the whole point of doing this task before any app work.

Create `scripts/check-hop.sh`:

```bash
#!/usr/bin/env bash
# Prove the Pi can reach the hub before anything depends on it.
#
# Run this on the Pi. It answers one question: does this network carry
# device-to-device traffic, or is client isolation on? Everything downstream is
# built on the answer being yes, and finding out at 3am is not a plan.
set -uo pipefail

HUB="${HAWKEYE_HUB_HOST:-hawkeye-hub.local}"
PORT="${HAWKEYE_HUB_PORT:-8787}"

echo "Checking the hop to ${HUB}:${PORT}"
echo

printf '1. DNS or mDNS resolves the hub ... '
if ADDR=$(getent hosts "${HUB}" 2>/dev/null | awk '{print $1; exit}') && [ -n "${ADDR}" ]; then
  echo "yes, ${ADDR}"
else
  echo "NO"
  echo
  echo "   The name ${HUB} does not resolve from this box."
  echo "   On the Mac, check that it is advertising: dns-sd -B _http._tcp"
  echo "   Or set HAWKEYE_HUB_HOST to the Mac's IP and run this again."
  exit 1
fi

printf '2. TCP connect to the hub port ... '
if timeout 5 bash -c "</dev/tcp/${HUB}/${PORT}" 2>/dev/null; then
  echo "yes"
else
  echo "NO"
  echo
  echo "   The name resolves but the port does not answer. In order of likelihood:"
  echo "   a. The hub is not running. On the Mac:"
  echo "        cd app/backend && .venv/bin/python -m hawkeye_backend.main"
  echo "   b. The macOS firewall is blocking incoming connections."
  echo "        System Settings > Network > Firewall"
  echo "   c. CLIENT ISOLATION is on for this WiFi network. This is the one you"
  echo "        cannot fix from your side. Move both boxes to a phone hotspot."
  exit 1
fi

printf '3. The hub answers /healthz ... '
if BODY=$(curl -fsS --max-time 5 "http://${HUB}:${PORT}/healthz" 2>/dev/null); then
  echo "yes"
  echo "   ${BODY}"
else
  echo "NO"
  echo "   The port is open but the hub did not answer. Check its log."
  exit 1
fi

echo
echo "The hop works. Start the edge:"
echo "  python -m hawkeye_vision.edge --hub ws://${HUB}:${PORT} --token \"\$HAWKEYE_EDGE_TOKEN\""
```

```bash
chmod +x scripts/check-hop.sh
```

- [ ] **Step 3: Prove it locally, both processes on the Mac**

This is the milestone. Nothing after this task is worth building until this works.

Terminal one:

```bash
cd app/backend
HAWKEYE_EDGE_TOKEN=dev-token .venv/bin/python -m hawkeye_backend.main
```

Terminal two, pushing the Brio:

```bash
cd vision
HAWKEYE_EDGE_TOKEN=dev-token python3 -m hawkeye_vision.edge \
  --hub ws://127.0.0.1:8787 --token dev-token --fps 10
```

Terminal three:

```bash
curl -sS -D- -o /tmp/still.jpg http://127.0.0.1:8787/v1/camera/still | grep -i hawkeye
file /tmp/still.jpg
curl -sS http://127.0.0.1:8787/v1/hub | python3 -m json.tool | grep -A8 '"camera"'
```

Expected: `X-HawkEye-Live: true`, `/tmp/still.jpg: JPEG image data`, and a camera block reporting `"linked": true` with a non-zero `fps`.

If the camera will not open, run with `--source fixture --path <a video file>` and everything else in this plan still works.

- [ ] **Step 4: Commit**

```bash
git add vision/hawkeye_vision/edge.py scripts/check-hop.sh
git commit -m "Push frames from the Pi, and prove the hop before anything depends on it"
```

---

## Task 5: MJPEG egress

**Files:**
- Modify: `app/backend/hawkeye_backend/api.py`
- Test: `app/backend/tests/test_camera_api.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_camera_api.py`:

```python
"""The camera's HTTP surface: one still, and a stream."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source, utc_now

JPEG = b"\xff\xd8\xff\xe0not-really-a-jpeg\xff\xd9"
BOUNDARY = b"--hawkeyeframe"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_the_still_endpoint_503s_with_a_reason_when_no_frame_has_arrived(client: TestClient):
    """A 503 naming the problem, never a placeholder image. A caller that gets
    bytes must be able to treat them as a real frame."""
    response = client.get("/v1/camera/still")
    assert response.status_code == 503
    assert "edge camera" in response.json()["detail"].lower()


def test_the_still_endpoint_labels_a_stale_frame_as_not_live(client: TestClient):
    from datetime import timedelta

    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now() - timedelta(seconds=60))

    response = client.get("/v1/camera/still")
    assert response.status_code == 200
    assert response.headers["x-hawkeye-live"] == "false"
    assert float(response.headers["x-hawkeye-frame-age"]) > 2.0


def test_the_live_endpoint_503s_when_there_is_no_camera(client: TestClient):
    response = client.get("/v1/camera/live")
    assert response.status_code == 503


def test_the_live_endpoint_streams_multipart_frames(client: TestClient):
    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now())

    with client.stream("GET", "/v1/camera/live") as response:
        assert response.status_code == 200
        assert "multipart/x-mixed-replace" in response.headers["content-type"]
        chunk = next(response.iter_bytes())

    assert BOUNDARY in chunk
    assert b"Content-Type: image/jpeg" in chunk
    assert JPEG in chunk
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_camera_api.py -q
```

Expected: the two live-endpoint tests fail with 404.

- [ ] **Step 3: Implement**

In `app/backend/hawkeye_backend/api.py`, add the import:

```python
from fastapi.responses import Response, StreamingResponse
```

(Replace the existing `from fastapi.responses import Response` line.)

Add this constant near the top, under `router = APIRouter(...)`:

```python
#: MJPEG part separator. Any token works as long as it does not occur in the
#: payload; this one is spelled out rather than generated so the web console and
#: the tests can both name it.
MJPEG_BOUNDARY = "hawkeyeframe"
```

Add the route, next to `get_camera_still`:

```python
@router.get("/camera/live", summary="The live camera, as MJPEG")
async def get_camera_live(request: Request) -> StreamingResponse:
    """`multipart/x-mixed-replace`, which every browser and `AVFoundation` reads.

    MJPEG rather than WebRTC because it needs no signalling, no TURN fallback
    and no peer plumbing, and it is one `<img src>` in the browser. The cost is
    bandwidth, and this runs on a LAN.

    A consumer that falls behind is dropped frames, not a stalled camera. See
    `LiveCamera.accept`: the queue is small on purpose, because a viewer three
    frames behind wants the newest frame and not the backlog.
    """
    runtime = _runtime(request)
    status = runtime.camera.status()
    if runtime.camera.latest is None:
        # 503 before the stream opens, so a caller gets a status code rather
        # than an empty 200 that never produces a part.
        raise HTTPException(status_code=503, detail=status.detail)

    async def parts():
        sub = await runtime.camera.subscribe()
        try:
            # The newest frame first, so a viewer joining mid-stream sees
            # something immediately instead of waiting for the next capture.
            if (first := runtime.camera.latest) is not None:
                yield _mjpeg_part(first.jpeg)
            while True:
                frame = await sub.queue.get()
                yield _mjpeg_part(frame.jpeg)
        except asyncio.CancelledError:
            raise
        finally:
            await runtime.camera.unsubscribe(sub)

    return StreamingResponse(
        parts(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _mjpeg_part(jpeg: bytes) -> bytes:
    """One part of the multipart stream.

    `Content-Length` is included because without it some clients buffer until
    the connection closes, which for a stream that never closes means they draw
    nothing at all.
    """
    return (
        f"--{MJPEG_BOUNDARY}\r\n"
        f"Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode() + jpeg + b"\r\n"
```

- [ ] **Step 4: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_camera_api.py -q
```

Expected: 5 passed.

- [ ] **Step 5: See it in a browser**

With the hub and the edge both running from Task 4:

```bash
open http://127.0.0.1:8787/v1/camera/live
```

Expected: moving video. This is the first moving picture the system has produced.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/api.py app/backend/tests/test_camera_api.py
git commit -m "Serve the camera as MJPEG, which every browser already reads"
```

---

## Task 6: The 1 Hz thumbnail on the event stream

The watch has no MJPEG decoder and no direct network path to the hub. It gets frames the way it gets everything else: as an envelope, relayed by the phone.

**Files:**
- Modify: `app/backend/hawkeye_backend/models/events.py`
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Test: `app/backend/tests/test_frame_event.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_frame_event.py`:

```python
"""The thumbnail that reaches a wrist."""

from __future__ import annotations

import asyncio
import base64

import pytest

from hawkeye_backend.config import Settings
from hawkeye_backend.main import build_runtime
from hawkeye_backend.models.common import Source, utc_now
from hawkeye_backend.models.events import EventKind, FrameEvent

JPEG = b"\xff\xd8\xff\xe0not-really-a-jpeg\xff\xd9"


def test_a_frame_event_carries_base64_and_its_scope():
    event = FrameEvent(
        jpeg_base64=base64.b64encode(JPEG).decode(),
        captured_at=utc_now(),
        source=Source.CAMERA_UVC,
        live=True,
        room="Living room",
    )
    assert event.kind is EventKind.FRAME
    assert base64.b64decode(event.jpeg_base64) == JPEG
    assert event.room == "Living room"


@pytest.mark.asyncio
async def test_the_thumbnail_task_publishes_the_latest_frame():
    settings = Settings(
        mode="simulated",
        edge_token="t",
        camera_thumbnail_interval_s=0.05,
        replay_site_enabled=False,
    )
    runtime = build_runtime(settings)
    sub = await runtime.bus.subscribe()
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now())

    task = asyncio.create_task(runtime._publish_thumbnails())
    try:
        envelope = await asyncio.wait_for(sub.queue.get(), timeout=2.0)
    finally:
        task.cancel()

    assert envelope.payload.kind is EventKind.FRAME
    assert envelope.payload.live is True


@pytest.mark.asyncio
async def test_the_thumbnail_task_publishes_nothing_when_there_is_no_frame():
    """Silence, not a placeholder. A watch showing a grey rectangle labelled as
    a camera frame is the failure this whole design is trying to avoid."""
    settings = Settings(
        mode="simulated",
        edge_token="t",
        camera_thumbnail_interval_s=0.05,
        replay_site_enabled=False,
    )
    runtime = build_runtime(settings)
    sub = await runtime.bus.subscribe()

    task = asyncio.create_task(runtime._publish_thumbnails())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.queue.get(), timeout=0.4)
    finally:
        task.cancel()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_frame_event.py -q
```

Expected: `ImportError: cannot import name 'FrameEvent'`.

- [ ] **Step 3: Add `FrameEvent` to the union**

In `app/backend/hawkeye_backend/models/events.py`, add to `EventKind`:

```python
    FRAME = "frame"
```

Add the class after `NoticeEvent`:

```python
class FrameEvent(BaseModel):
    """A camera thumbnail, for clients that cannot hold an MJPEG stream open.

    The watch is the reason this exists. It has no MJPEG decoder and no direct
    path to the hub, so it gets frames the way it gets everything else: as an
    envelope, relayed through the phone. `Notice.stillFrame` already proves a
    base64 JPEG survives that trip.

    One per second, and small. This is a wrist, not a monitor.
    """

    kind: Literal[EventKind.FRAME] = EventKind.FRAME
    jpeg_base64: str = Field(description="Base64 JPEG. Small: a thumbnail, not a recording.")
    captured_at: datetime = Field(
        description="When the camera took it, not when it was published here."
    )
    source: Source = Field(
        description="What produced it. A video file must not read as a camera."
    )
    live: bool = Field(
        description=(
            "Whether this was current when published. False means the client must "
            "label it as the last thing seen rather than draw it as the room now."
        )
    )
    room: str | None = Field(
        default=None,
        description=(
            "The room this camera covers. One fixed camera sees one room, and every "
            "vision claim carries its scope rather than implying it has none."
        ),
    )
```

Add `FrameEvent` to the `EventPayload` union and add the imports at the top of the file:

```python
from hawkeye_backend.models.common import Source, utc_now
```

- [ ] **Step 4: Publish the thumbnails**

In `app/backend/hawkeye_backend/runtime.py`, add to the events import:

```python
    FrameEvent,
```

Add these near the other imports:

```python
import base64
```

Add the task method after `_poll_sensor`:

```python
    async def _publish_thumbnails(self) -> None:
        """Push a small frame onto the event stream, for the watch.

        Publishes nothing at all when there is no frame. Silence is the honest
        output: a watch drawing a grey rectangle labelled as a camera frame is
        precisely the lie this design exists to prevent.

        Re-encoding happens here rather than on the Pi because the Pi already
        ships one size and a second encode on a Pi 4B costs frames off the
        stream a human is watching.
        """
        interval = self.settings.camera_thumbnail_interval_s
        last_index: int | None = None
        while True:
            try:
                frame = self.camera.latest
                if frame is not None and frame.index != last_index:
                    last_index = frame.index
                    status = self.camera.status()
                    thumb = self._thumbnail(frame.jpeg)
                    await self.emit(
                        FrameEvent(
                            jpeg_base64=base64.b64encode(thumb).decode(),
                            captured_at=frame.captured_at,
                            source=status.source or Source.CAMERA_SIM,
                            live=status.live,
                            room=self.settings.camera_room,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Broad on purpose, same as _poll_sensor. This task runs for the
                # life of the process and must not die of one bad frame during
                # an emergency.
                logger.exception("thumbnail publish failed")
            await asyncio.sleep(interval)

    def _thumbnail(self, jpeg: bytes) -> bytes:
        """Shrink a frame for the wrist, or hand back what we were given.

        OpenCV is not a hard dependency of this service, and a hub that refuses
        to start because a thumbnail could not be resized would be trading the
        whole demo for a few kilobytes. Falls back to the full frame and says so
        once.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            if not getattr(self, "_thumb_warned", False):
                logger.warning(
                    "thumbnails: OpenCV is not installed, so full frames are going "
                    "to the watch. Install opencv-python-headless to shrink them."
                )
                self._thumb_warned = True
            return jpeg

        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jpeg
        height, width = image.shape[:2]
        longest = max(height, width)
        edge = self.settings.camera_thumbnail_long_edge
        if longest > edge:
            scale = edge / longest
            image = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
        return buffer.tobytes() if ok else jpeg
```

Start it in `start()`, next to `_sensor_task`:

```python
        self._thumbnail_task = asyncio.create_task(self._publish_thumbnails())
```

Declare it in `__init__` next to `_sensor_task`:

```python
        self._thumbnail_task: asyncio.Task[None] | None = None
```

Cancel it in `stop()`, mirroring the `_sensor_task` block:

```python
        if self._thumbnail_task is not None:
            self._thumbnail_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._thumbnail_task
            self._thumbnail_task = None
```

Add the import for `Source` to `runtime.py`:

```python
from hawkeye_backend.models.common import Source
```

- [ ] **Step 5: Add the room setting**

In `config.py`, under the camera block from Task 3:

```python
    # The room this one fixed camera covers. One camera sees one room, and every
    # vision claim carries that scope rather than implying it has none. Authored,
    # not sensed: the system does not map walls and cannot.
    camera_room: str = "Living room"
```

- [ ] **Step 6: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_frame_event.py -q
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: 3 passed, then the full suite green.

- [ ] **Step 7: Commit**

```bash
git add app/backend/hawkeye_backend/ app/backend/tests/test_frame_event.py
git commit -m "Put a thumbnail on the event stream, because a wrist is not a monitor"
```

---

## Task 7: The browser live page

**Files:**
- Create: `app/web/live/index.html`
- Create: `app/web/live/live.css`
- Create: `app/web/live/live.js`
- Modify: `app/backend/hawkeye_backend/main.py`

- [ ] **Step 1: Mount the directory**

In `app/backend/hawkeye_backend/main.py`, next to `REPLAY_SITE`:

```python
#: The live console. Same deal as REPLAY_SITE: a static directory, no bundler.
LIVE_SITE = Path(__file__).resolve().parents[2] / "web" / "live"
```

In `create_app`, immediately before the `/replay` mount:

```python
    if LIVE_SITE.is_dir():
        app.mount("/live", StaticFiles(directory=LIVE_SITE, html=True), name="live-console")
        logger.info("live console served at /live from %s", LIVE_SITE)
```

- [ ] **Step 2: Write the page**

Create `app/web/live/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Hawk Eye live</title>
    <link rel="stylesheet" href="live.css" />
  </head>
  <body>
    <header>
      <h1>Hawk Eye</h1>
      <p id="hub" class="muted">Connecting…</p>
    </header>

    <main>
      <section class="feed">
        <!-- src is set by live.js rather than here, so the page can show the
             unreachable state instead of a browser broken-image icon. -->
        <img id="camera" alt="Live camera" />
        <div id="cameraOverlay" class="overlay">No camera</div>
        <p id="cameraStatus" class="muted"></p>
      </section>

      <section class="controls">
        <h2>Controls</h2>
        <p class="muted">
          Every button here does exactly what the same button does on the phone
          and the watch. That is the point of the page.
        </p>
        <button id="startIncident" type="button" class="danger">Start incident</button>
        <button id="openShutter" type="button">Open shutter</button>
        <button id="closeShutter" type="button">Close shutter</button>
        <form id="contextForm">
          <label for="contextText">What is happening</label>
          <textarea id="contextText" rows="3" placeholder="Anything the operator should know"></textarea>
          <button type="submit">Send context</button>
        </form>
      </section>

      <section class="stream">
        <h2>Narration and events</h2>
        <ul id="events"></ul>
      </section>
    </main>

    <script src="live.js"></script>
  </body>
</html>
```

Create `app/web/live/live.css`:

```css
/* Deliberately plain. This page is a control surface and a proof that the
   backend is shared, not a design artifact. The phone is the designed one. */
:root {
  --ink: #12141a;
  --muted: #6b7280;
  --surface: #ffffff;
  --ground: #f4f5f7;
  --hairline: #e3e5e9;
  --danger: #b3261e;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #edeef2;
    --muted: #9aa1ad;
    --surface: #1a1d24;
    --ground: #101218;
    --hairline: #2a2e38;
    --danger: #f2b8b5;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
header { padding: 20px 24px 0; }
h1 { margin: 0; font-size: 20px; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.muted { color: var(--muted); font-size: 13px; }
main {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 20px;
  padding: 20px 24px 40px;
}
section {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 16px;
}
.feed { position: relative; grid-row: span 2; }
.feed img { width: 100%; border-radius: 8px; display: block; background: #000; }
.feed img[hidden] { display: none; }
.overlay {
  position: absolute; inset: 16px; border-radius: 8px;
  display: grid; place-items: center;
  background: var(--ground); border: 1px dashed var(--hairline);
  color: var(--muted); font-size: 14px; text-align: center; padding: 20px;
}
/* A stale frame is dimmed and captioned rather than hidden. It is still a true
   statement about the last thing the camera saw; it is just not the room now. */
.feed img.stale { filter: grayscale(1) brightness(0.55); }
button {
  font: inherit; padding: 10px 14px; border-radius: 8px;
  border: 1px solid var(--hairline); background: var(--surface); color: var(--ink);
  cursor: pointer; margin: 0 8px 8px 0;
}
button:hover { border-color: var(--muted); }
button.danger { border-color: var(--danger); color: var(--danger); font-weight: 600; }
textarea { width: 100%; font: inherit; padding: 8px; border-radius: 8px;
  border: 1px solid var(--hairline); background: var(--ground); color: var(--ink); }
label { display: block; font-size: 13px; color: var(--muted); margin: 12px 0 4px; }
#events { list-style: none; margin: 0; padding: 0; max-height: 50vh; overflow-y: auto; }
#events li { padding: 8px 0; border-bottom: 1px solid var(--hairline); font-size: 14px; }
#events li .kind { color: var(--muted); font-size: 12px; text-transform: uppercase; }
```

Create `app/web/live/live.js`:

```js
/* The browser surface.
 *
 * It exists to demonstrate one property: the backend is shared. A button here
 * does exactly what the same button does on the phone and the watch, and all
 * three see the result, because every one of them goes through
 * HubRuntime.emit().
 *
 * The camera rule this page obeys: a frame that is not current is never drawn
 * as if it were. It is dimmed and captioned, or replaced by the unreachable
 * state. A frozen picture of an empty room is the most dangerous thing this
 * system can display.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const api = (path) => new URL(path, window.location.origin).toString();

let activeIncidentId = null;

function addEvent(kind, text) {
  const li = document.createElement("li");
  const label = document.createElement("div");
  label.className = "kind";
  label.textContent = `${kind} · ${new Date().toLocaleTimeString()}`;
  const body = document.createElement("div");
  body.textContent = text;
  li.append(label, body);
  $("events").prepend(li);
}

function renderCamera(status) {
  const img = $("camera");
  const overlay = $("cameraOverlay");
  $("cameraStatus").textContent = status.detail || "";

  if (!status.linked && status.frames_received === 0) {
    img.hidden = true;
    overlay.hidden = false;
    overlay.textContent = "No camera. The edge has not connected.";
    return;
  }

  overlay.hidden = true;
  img.hidden = false;
  if (!img.src) {
    // Cache-busted once on first attach. The stream itself never caches.
    img.src = api(`/v1/camera/live?t=${Date.now()}`);
  }
  img.classList.toggle("stale", !status.live);
  if (!status.live) {
    overlay.hidden = false;
    overlay.textContent = "Camera unreachable. Showing the last frame seen.";
  }
}

async function refreshHub() {
  try {
    const res = await fetch(api("/v1/hub"));
    const hub = await res.json();
    $("hub").textContent = `${hub.hub_name} · ${hub.mode} · ${hub.site_address}`;
    renderCamera(hub.camera);
  } catch (err) {
    $("hub").textContent = "Hub unreachable.";
  }
}

function connectStream() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${proto}//${window.location.host}/v1/stream`);

  socket.addEventListener("message", (event) => {
    const envelope = JSON.parse(event.data);
    const payload = envelope.payload;
    switch (payload.kind) {
      case "frame":
        // The MJPEG element carries the picture. This event is for the watch;
        // here it is only used to keep the live/stale label honest.
        $("camera").classList.toggle("stale", !payload.live);
        break;
      case "narration":
        addEvent(`narration · ${payload.room || "unscoped"}`, payload.text);
        break;
      case "notice":
        addEvent("notice", `${payload.notice.title}: ${payload.notice.body}`);
        break;
      case "incident":
        activeIncidentId = payload.incident.incident_id;
        addEvent("incident", `${payload.phase}: ${payload.incident.incident_id}`);
        break;
      case "shield":
        addEvent(
          "shield",
          payload.refused
            ? `REFUSED: ${payload.refusal_reason}`
            : `${payload.position} (commanded, not measured)`
        );
        break;
      case "verification":
        addEvent("verification", `${payload.result.decision}: ${payload.result.detail || ""}`);
        break;
      case "transcript":
        addEvent(`transcript · ${payload.line.speaker}`, payload.line.text);
        break;
      case "hello":
        addEvent("connected", `${payload.hub_name} (${payload.mode})`);
        activeIncidentId = payload.active_incident_id;
        break;
      default:
        break;
    }
  });

  socket.addEventListener("close", () => {
    addEvent("disconnected", "Stream closed. Retrying in 2s.");
    setTimeout(connectStream, 2000);
  });
}

async function post(path, body) {
  const res = await fetch(api(path), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const detail = await res.text();
    addEvent("error", `${path} failed: ${res.status} ${detail}`);
    return null;
  }
  return res.json();
}

$("startIncident").addEventListener("click", async () => {
  const ack = await post("/v1/incident", { incident_type: "burglary" });
  if (ack) activeIncidentId = ack.incident_id;
});

$("openShutter").addEventListener("click", () =>
  post("/v1/shutter", { action: "open", reason: "opened from the web console" })
);
$("closeShutter").addEventListener("click", () =>
  post("/v1/shutter", { action: "close", reason: "closed from the web console" })
);

$("contextForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("contextText").value.trim();
  if (!text) return;
  if (!activeIncidentId) {
    addEvent("error", "No active incident to attach context to.");
    return;
  }
  await post(`/v1/incident/${activeIncidentId}/context`, { text });
  $("contextText").value = "";
});

refreshHub();
setInterval(refreshHub, 3000);
connectStream();
```

- [ ] **Step 3: Look at it**

With the hub and the edge running:

```bash
open http://127.0.0.1:8787/live/
```

Expected: live video, a hub line, and the controls. `Open shutter` will error until Task 10; that error appearing in the event list is the correct behaviour for now.

- [ ] **Step 4: Commit**

```bash
git add app/web/live app/backend/hawkeye_backend/main.py
git commit -m "Give the browser a live surface, so the shared backend is visible"
```

---

## Task 8: `RelayFrameSource`

Vision runs on the Mac and reads the relay. Everything below the seam is untouched.

**Files:**
- Create: `vision/hawkeye_vision/relay.py`
- Test: `vision/tests/test_relay.py`

- [ ] **Step 1: Write the failing test**

Create `vision/tests/test_relay.py`:

```python
"""RelayFrameSource: the tracker's camera is now the hub's relay.

The point of the FrameSource seam is that nothing downstream of it knows or
cares. These tests assert that this implementation satisfies the same contract
the webcam and the fixture do, including the part of it that exists to stop a
video file presenting as a camera.
"""

from __future__ import annotations

import numpy as np
import pytest

from hawkeye_backend.models.common import Source
from hawkeye_vision.relay import RelayFrameSource, RelayUnavailable


class FakeResponse:
    def __init__(self, jpeg: bytes, headers: dict[str, str], status: int = 200) -> None:
        self.content = jpeg
        self.headers = headers
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def encode(colour: int) -> bytes:
    import cv2

    image = np.full((48, 64, 3), colour, np.uint8)
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


def test_it_reports_the_source_the_hub_reports(monkeypatch):
    """Not hardcoded to CAMERA_UVC. If the hub says the frames come from a
    replayed video, this must say so too, or the seam's whole purpose is lost."""
    source = RelayFrameSource(base_url="http://hub.invalid", poll_interval_s=0)
    monkeypatch.setattr(
        source, "_fetch_status", lambda: {"source": "replay-video", "live": True}
    )
    source.refresh_source()
    assert source.source is Source.REPLAY_VIDEO


def test_frames_decode_to_images(monkeypatch):
    jpeg = encode(90)
    source = RelayFrameSource(base_url="http://hub.invalid", poll_interval_s=0, max_frames=2)
    monkeypatch.setattr(
        source,
        "_get_still",
        lambda: FakeResponse(jpeg, {"x-hawkeye-live": "true", "x-hawkeye-frame-age": "0.01"}),
    )

    frames = list(source.frames())
    assert len(frames) == 2
    assert frames[0].image.shape == (48, 64, 3)
    assert frames[0].index == 0
    assert frames[1].index == 1


def test_a_stale_frame_is_not_yielded(monkeypatch):
    """The tracker must not draw boxes on a frame that is not current, and
    narration must not describe a room from a minute ago."""
    jpeg = encode(90)
    source = RelayFrameSource(base_url="http://hub.invalid", poll_interval_s=0, max_frames=3)
    monkeypatch.setattr(
        source,
        "_get_still",
        lambda: FakeResponse(jpeg, {"x-hawkeye-live": "false", "x-hawkeye-frame-age": "40.0"}),
    )

    assert list(source.frames()) == []


def test_an_unreachable_hub_raises_rather_than_yielding_nothing(monkeypatch):
    """Silence and 'the hub is gone' must not share a representation. A consumer
    that cannot tell them apart will report an empty room."""

    def boom():
        raise RuntimeError("connection refused")

    source = RelayFrameSource(base_url="http://hub.invalid", poll_interval_s=0, max_frames=1)
    monkeypatch.setattr(source, "_get_still", boom)

    with pytest.raises(RelayUnavailable):
        list(source.frames())
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd vision && python3 -m pytest tests/test_relay.py -q
```

Expected: `ModuleNotFoundError: No module named 'hawkeye_vision.relay'`.

- [ ] **Step 3: Implement**

Create `vision/hawkeye_vision/relay.py`:

```python
"""A `FrameSource` that reads the hub's camera relay.

This is what lets the tracker run on the Mac while the camera is on the Pi.
Everything below the `FrameSource` seam is unchanged: YOLO, BoT-SORT, the
lighting state machine, the mp4 recorder and the narrator all keep working
against the same interface they always had.

It polls `/v1/camera/still` rather than consuming the MJPEG stream. The tracker
samples at its own rate and drops what it cannot keep up with anyway, so pulling
the newest frame on demand is both simpler and closer to what it wants than
being pushed a backlog it will discard.

**A stale frame is never yielded.** Drawing boxes on a frame from a minute ago,
or narrating a room from a minute ago, produces claims that are false in exactly
the way this project exists to prevent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import numpy as np
from hawkeye_backend.models.common import Source

from hawkeye_vision.frames import Frame, FrameSource, utc_now

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 0.1


class RelayUnavailable(RuntimeError):
    """The hub could not be reached.

    Raised rather than returning no frames, because a consumer that cannot tell
    "nothing is happening" from "the hub is gone" will report an empty room.
    """


class RelayFrameSource(FrameSource):
    """Frames pulled from `app/backend`'s camera relay."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        max_frames: int | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._poll_interval_s = poll_interval_s
        self._max_frames = max_frames
        self._timeout_s = timeout_s
        self._index = 0
        #: Until the hub says otherwise, we do not claim to be a camera.
        #: `CAMERA_SIM` is the honest default: it classes as SIMULATED, so
        #: anything rendering a provenance badge shows one until proven wrong.
        self.source: Source = Source.CAMERA_SIM
        self._client = None

    # ------------------------------------------------------------------ HTTP

    def _http(self):  # noqa: ANN202 - httpx.Client
        import httpx

        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout_s)
        return self._client

    def _get_still(self):  # noqa: ANN202 - httpx.Response
        return self._http().get("/v1/camera/still")

    def _fetch_status(self) -> dict:
        response = self._http().get("/v1/hub")
        response.raise_for_status()
        return response.json()["camera"]

    def refresh_source(self) -> None:
        """Ask the hub what is actually producing frames, and believe it.

        Not hardcoded. If the hub says the frames come from a replayed video,
        this reports a replayed video, and every claim built on it is labelled
        accordingly. That is the entire reason `FrameSource.source` is part of
        the interface.
        """
        try:
            status = self._fetch_status()
        except Exception as exc:  # noqa: BLE001
            raise RelayUnavailable(f"could not read camera status: {exc}") from exc
        raw = status.get("source")
        if raw:
            self.source = Source(raw)

    # ---------------------------------------------------------------- frames

    def frames(self) -> Iterator[Frame]:
        import cv2

        produced = 0
        while self._max_frames is None or produced < self._max_frames:
            try:
                response = self._get_still()
            except Exception as exc:  # noqa: BLE001
                raise RelayUnavailable(f"hub unreachable: {exc}") from exc

            if getattr(response, "status_code", 200) == 503:
                # No frame yet. Not an error: the edge may not have connected.
                produced += 1
                if self._poll_interval_s:
                    time.sleep(self._poll_interval_s)
                continue
            response.raise_for_status()

            produced += 1
            if response.headers.get("x-hawkeye-live", "false").lower() != "true":
                age = response.headers.get("x-hawkeye-frame-age", "?")
                logger.debug("relay: skipping a frame %ss old", age)
                if self._poll_interval_s:
                    time.sleep(self._poll_interval_s)
                continue

            image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                logger.warning("relay: the hub returned bytes OpenCV could not decode")
                continue

            yield Frame(image=image, index=self._index, captured_at=utc_now())
            self._index += 1

            if self._poll_interval_s:
                time.sleep(self._poll_interval_s)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
```

- [ ] **Step 4: Run the tests**

```bash
cd vision && python3 -m pytest tests/test_relay.py -q
cd vision && python3 -m pytest -q
```

Expected: 4 passed, then the whole vision suite green.

- [ ] **Step 5: Commit**

```bash
git add vision/hawkeye_vision/relay.py vision/tests/test_relay.py
git commit -m "Let the tracker read the hub's relay, so the Pi never runs a model"
```

---

## Task 9: Narration and occupancy endpoints

**Files:**
- Modify: `app/backend/hawkeye_backend/models/events.py`
- Modify: `app/backend/hawkeye_backend/api.py`
- Test: `app/backend/tests/test_vision_api.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_vision_api.py`:

```python
"""What vision posts back, and what every app then sees."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_a_narration_line_reaches_every_stream_subscriber(client: TestClient):
    """The property the whole integration exists for: one producer, every
    surface, one funnel."""
    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()  # hello

        response = client.post(
            "/v1/vision/narration",
            json={"text": "A person in a dark jacket is by the door.", "room": "Living room"},
        )
        assert response.status_code == 202

        while (envelope := ws.receive_json())["payload"]["kind"] != "narration":
            pass

    payload = envelope["payload"]
    assert payload["text"] == "A person in a dark jacket is by the door."
    assert payload["room"] == "Living room"


def test_narration_carries_its_sampling_window(client: TestClient):
    """Gemini samples about one frame per second, so narration is a sequence of
    observations and not continuous tracking. The root CLAUDE.md requires that
    limit to live in the data, not only in a comment."""
    response = client.post(
        "/v1/vision/narration",
        json={"text": "Someone is standing still.", "room": "Living room", "window_s": 1.0},
    )
    assert response.status_code == 202
    assert response.json()["window_s"] == 1.0


def test_narration_without_a_room_is_refused(client: TestClient):
    """One fixed camera sees one room. A scoped claim must not be presentable as
    an unscoped one by accident, so the scope is required rather than defaulted."""
    response = client.post("/v1/vision/narration", json={"text": "Something moved."})
    assert response.status_code == 422


def test_empty_narration_is_refused(client: TestClient):
    response = client.post("/v1/vision/narration", json={"text": "  ", "room": "Living room"})
    assert response.status_code == 422


def test_occupancy_reaches_the_stream(client: TestClient):
    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()
        response = client.post(
            "/v1/vision/occupancy",
            json={"person_present": True, "people": 1, "room": "Living room"},
        )
        assert response.status_code == 202
        while (envelope := ws.receive_json())["payload"]["kind"] != "occupancy":
            pass

    assert envelope["payload"]["person_present"] is True
    assert envelope["payload"]["people"] == 1
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_vision_api.py -q
```

Expected: 404s on both routes.

- [ ] **Step 3: Add the two events**

In `app/backend/hawkeye_backend/models/events.py`, add to `EventKind`:

```python
    NARRATION = "narration"
    OCCUPANCY = "occupancy"
```

Add after `FrameEvent`:

```python
class NarrationEvent(BaseModel):
    """One line the camera produced about what it is seeing.

    **Not a `TranscriptLine`.** That type is documented as one line of the
    caller-to-911 conversation, and collapsing the two would let a camera
    observation render as something an operator was told. When `caller` quotes
    one of these to an operator, that becomes a `TranscriptLine` whose
    `claim_ids` point back here, which is the existing mechanism for exactly
    this and needs nothing new.

    `room` and `window_s` are both required and both load-bearing. One fixed
    camera sees one room, and Gemini samples at roughly one frame per second, so
    this is a sequence of observations rather than continuous tracking. The root
    CLAUDE.md requires both limits to be carried in the data rather than only
    stated in a comment.
    """

    kind: Literal[EventKind.NARRATION] = EventKind.NARRATION
    text: str = Field(min_length=1)
    room: str = Field(min_length=1, description="The room this camera covers. Never absent.")
    window_s: float = Field(
        default=1.0,
        gt=0,
        description=(
            "Seconds of observation this line summarizes. About one frame per "
            "second reaches the model, so this is a sequence of glances rather "
            "than continuous tracking, and a reader is entitled to know that."
        ),
    )
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.AGENT_INFERENCE


class OccupancyEvent(BaseModel):
    """Whether the camera can see anybody. What closes the shutter again.

    Personhood only. This never says who: we have no database and no lawful
    basis for one, and `intruder` answers identity separately by asking the
    router which devices are present.
    """

    kind: Literal[EventKind.OCCUPANCY] = EventKind.OCCUPANCY
    person_present: bool
    people: int = Field(ge=0, description="How many tracks are currently present.")
    room: str = Field(min_length=1)
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.CAMERA_UVC
```

Add both to the `EventPayload` union.

- [ ] **Step 4: Add the routes**

In `app/backend/hawkeye_backend/api.py`, add the imports:

```python
from hawkeye_backend.models.events import NarrationEvent, OccupancyEvent
```

Add these request models next to `DemoRunAck`:

```python
class NarrationRequest(BaseModel):
    """What `vision/` posts for each Gemini line."""

    text: str = Field(min_length=1)
    room: str = Field(
        min_length=1,
        description=(
            "Required, never defaulted. One fixed camera sees one room, and a "
            "scoped claim must not become an unscoped one because a producer "
            "left a field out."
        ),
    )
    window_s: float = Field(default=1.0, gt=0)


class OccupancyRequest(BaseModel):
    person_present: bool
    people: int = Field(ge=0)
    room: str = Field(min_length=1)
```

Add the routes:

```python
@router.post("/vision/narration", status_code=202, summary="One line from the camera")
async def post_narration(request: Request, body: NarrationRequest) -> NarrationEvent:
    """`vision/` posts here; every app sees it.

    202 rather than 201: this creates nothing addressable, it publishes. The
    line is on the stream by the time this returns.
    """
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="narration text cannot be blank")
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    event = NarrationEvent(text=body.text.strip(), room=body.room, window_s=body.window_s)
    await runtime.emit(event, active.incident_id if active else None)
    return event


@router.post("/vision/occupancy", status_code=202, summary="Whether the camera sees anybody")
async def post_occupancy(request: Request, body: OccupancyRequest) -> OccupancyEvent:
    """Personhood, and nothing more.

    It says somebody is there. It never says who: we have no database and no
    lawful basis for one. Identity is `intruder`'s question and it answers it
    from the router's device roster, not from a face.
    """
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    event = OccupancyEvent(
        person_present=body.person_present, people=body.people, room=body.room
    )
    await runtime.emit(event, active.incident_id if active else None)
    return event
```

Blank text is rejected by `min_length=1` for the empty case and by the explicit strip check for whitespace. Both produce 422, which is what the test asserts. If FastAPI returns 422 before the handler runs, that is correct and the test still passes.

- [ ] **Step 5: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_vision_api.py -q
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: 5 passed, then the whole suite green.

- [ ] **Step 6: Commit**

```bash
git add app/backend/hawkeye_backend/ app/backend/tests/test_vision_api.py
git commit -m "Carry narration and occupancy from the camera to every surface"
```

---

## Task 10: The shutter control

The hero control. A grant travels down the edge link, the servo moves, the attestation comes back up, and every surface sees it, including when it is refused.

**Files:**
- Modify: `app/backend/hawkeye_backend/models/events.py`
- Modify: `app/backend/hawkeye_backend/api.py`
- Modify: `app/backend/hawkeye_backend/runtime.py`
- Test: `app/backend/tests/test_shutter_api.py`

- [ ] **Step 1: Write the failing test**

Create `app/backend/tests/test_shutter_api.py`:

```python
"""The shutter control, from any surface.

The refusal path matters more than the happy path here. A shutter that opens is
unremarkable; a shutter that refuses a grant it cannot verify, visibly, on every
screen at once, is the submission.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.edge.wire import EdgeAttestation, EdgeHello
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source

TOKEN = "test-edge-token"


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        mode="simulated", edge_token=TOKEN, replay_site_enabled=False, shutter_timeout_s=2.0
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_the_shutter_refuses_to_act_when_no_edge_is_connected(client: TestClient):
    """503 naming the problem, not a hang and not a lie. There is no servo to
    move and saying 'opened' would be the worst possible response."""
    response = client.post("/v1/shutter", json={"action": "open", "reason": "test"})
    assert response.status_code == 503
    assert "edge" in response.json()["detail"].lower()


def test_an_unknown_action_is_refused(client: TestClient):
    """Two actions exist. A third is a refusal, never a default."""
    response = client.post("/v1/shutter", json={"action": "wiggle", "reason": "test"})
    assert response.status_code == 422


def test_a_grant_reaches_the_edge_and_its_attestation_reaches_the_stream(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        with client.websocket_connect("/v1/stream") as stream:
            stream.receive_json()  # hello

            import threading

            result: dict = {}

            def call():
                result["response"] = client.post(
                    "/v1/shutter", json={"action": "open", "reason": "test"}
                )

            caller = threading.Thread(target=call)
            caller.start()

            grant = edge.receive_json()
            assert grant["kind"] == "grant"
            assert "grant_json" in grant

            edge.send_text(
                EdgeAttestation(
                    request_id=grant["request_id"],
                    attestation_json=json.dumps(
                        {"position": "open", "commanded_angle": 90, "position_basis": "commanded"}
                    ),
                    refused=False,
                ).model_dump_json()
            )
            caller.join(timeout=5)

            while (envelope := stream.receive_json())["payload"]["kind"] != "shield":
                pass

    assert result["response"].status_code == 202
    assert envelope["payload"]["position"] == "open"
    assert envelope["payload"]["refused"] is False
    assert envelope["payload"]["position_basis"] == "commanded"


def test_a_refused_grant_is_published_as_a_refusal_not_an_error(client: TestClient):
    """A refusal is the system working. It reaches every screen as a first-class
    outcome rather than being swallowed into a 500."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        with client.websocket_connect("/v1/stream") as stream:
            stream.receive_json()

            import threading

            result: dict = {}

            def call():
                result["response"] = client.post(
                    "/v1/shutter", json={"action": "open", "reason": "test"}
                )

            caller = threading.Thread(target=call)
            caller.start()

            grant = edge.receive_json()
            edge.send_text(
                EdgeAttestation(
                    request_id=grant["request_id"],
                    refused=True,
                    refusal_reason="unknown_issuer",
                ).model_dump_json()
            )
            caller.join(timeout=5)

            while (envelope := stream.receive_json())["payload"]["kind"] != "shield":
                pass

    assert result["response"].status_code == 202
    assert envelope["payload"]["refused"] is True
    assert envelope["payload"]["refusal_reason"] == "unknown_issuer"
    assert envelope["payload"]["position"] == "unknown"


def test_a_shutter_that_never_answers_reads_as_unknown_never_as_open(client: TestClient):
    """Timeout is the one case where guessing is genuinely dangerous. An unknown
    shield position is a true statement; 'open' would be a false one, and the
    difference is whether a camera is covered."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        response = client.post("/v1/shutter", json={"action": "open", "reason": "test"})

    assert response.status_code == 504
    assert "did not answer" in response.json()["detail"].lower()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_shutter_api.py -q
```

Expected: 404s on `/v1/shutter`.

- [ ] **Step 3: Add the setting**

In `config.py`, under the camera block:

```python
    # How long to wait for a shutter to answer a grant before reporting the
    # position unknown. Seconds. A grant's own TTL is ten seconds, so waiting
    # longer than that is waiting for something that has already expired.
    shutter_timeout_s: float = 8.0
```

- [ ] **Step 4: Add `ShieldEvent`**

In `models/events.py`, add to `EventKind`:

```python
    SHIELD = "shield"
```

Add after `OccupancyEvent`:

```python
class ShieldEvent(BaseModel):
    """Where the physical shield is, and what the shutter said about getting there.

    `position_basis` is `commanded` and never `measured`, and that is not a
    technicality. The SG92R is open-loop with no position feedback, so this is
    the angle the servo was told to reach and never the angle the shield
    actually reached. A jammed shield attests open while covering the lens, and
    the only thing that catches that is the frame itself being dark.

    `refused` is a first-class outcome. A shutter refusing a grant it cannot
    verify is the system working, and it is the thing this project most wants to
    be able to put on a screen.
    """

    kind: Literal[EventKind.SHIELD] = EventKind.SHIELD
    position: str = Field(
        description="`open`, `closed`, or `unknown`. Unknown when the shutter did not answer."
    )
    position_basis: str = Field(
        default="commanded",
        description="Always `commanded`. The servo has no position feedback.",
    )
    commanded_angle: int | None = None
    requested_action: str = Field(description="What was asked for: `open` or `close`.")
    refused: bool = False
    refusal_reason: str = ""
    reason: str = Field(default="", description="Why the move was requested. Recorded, not trusted.")
    at: datetime = Field(default_factory=utc_now)
    source: Source = Source.SERVO_GPIO
```

Add it to the `EventPayload` union.

- [ ] **Step 5: Give the runtime a way to send a grant**

In `runtime.py`, add this method after `await_attestation`:

```python
    async def send_grant(self, grant_json: str, request_id: str) -> None:
        """Push a signed grant down the edge link.

        Raises `EdgeUnavailable` when there is no link. Raising rather than
        queueing is deliberate: a grant has a ten second TTL, and one delivered
        after the situation that produced it has passed is a replay waiting to
        happen rather than a late success.
        """
        from hawkeye_backend.edge.wire import EdgeGrant

        edge = self.edge
        if edge is None:
            raise EdgeUnavailable("no edge box is connected, so there is no servo to move")
        await edge.send_text(
            EdgeGrant(request_id=request_id, grant_json=grant_json).model_dump_json()
        )
```

Add the exception near the top of `runtime.py`:

```python
class EdgeUnavailable(RuntimeError):
    """There is no edge box connected. Raised rather than pretended about."""
```

- [ ] **Step 6: Add the route**

In `api.py`, add the imports:

```python
import secrets
from hawkeye_backend.models.events import ShieldEvent
from hawkeye_backend.runtime import EdgeUnavailable
```

Add the request model:

```python
class ShutterRequest(BaseModel):
    """Ask the shield to move.

    Two actions exist and there is no third. An unknown one is a refusal rather
    than a default, which is the same rule `agents/shutter/grant.py` states.
    """

    action: Literal["open", "close"]
    reason: str = Field(
        default="",
        description=(
            "Why. Recorded into the sealed record so an investigator can follow "
            "the chain backwards. Nothing downstream reads it as authorization."
        ),
    )
```

Add the route:

```python
@router.post("/shutter", status_code=202, summary="Move the physical shield")
async def post_shutter(request: Request, body: ShutterRequest) -> ShieldEvent:
    """Issue a grant, wait for the attestation, publish what happened.

    Every outcome reaches every surface, including the refusal, which is the one
    that matters. A dispatch demo that works is unremarkable; a shutter that
    refuses an impostor, visibly, on stage, is the submission.

    Three failures, three different answers, none of them a guess:

    - **No edge connected** is a 503. There is no servo, and saying `opened`
      would be the worst possible response.
    - **The shutter refused** is a 202 carrying `refused: true`. The system
      worked; it just said no.
    - **The shutter never answered** is a 504 and a position of `unknown`. An
      unknown shield position is a true statement and `open` would be a false
      one, and the difference is whether a camera is covered.
    """
    runtime = _runtime(request)
    active = await runtime.store.get_active_incident()
    incident_id = active.incident_id if active else None
    request_id = secrets.token_urlsafe(9)

    # Registered before the grant is sent, so an attestation that comes back
    # faster than this coroutine resumes still has somewhere to land.
    waiter = runtime.await_attestation(request_id)

    try:
        grant_json = await runtime.client.issue_shutter_grant(
            action=body.action, reason=body.reason
        )
    except MasterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"agent mesh unavailable: {exc}") from exc

    try:
        await runtime.send_grant(grant_json, request_id)
    except EdgeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        attestation = await asyncio.wait_for(waiter, timeout=runtime.settings.shutter_timeout_s)
    except asyncio.TimeoutError:
        event = ShieldEvent(
            position="unknown",
            requested_action=body.action,
            reason=body.reason,
            refused=False,
            refusal_reason="the shutter did not answer",
        )
        await runtime.emit(event, incident_id)
        raise HTTPException(
            status_code=504,
            detail=(
                f"the shutter did not answer within {runtime.settings.shutter_timeout_s}s. "
                "The shield position is unknown."
            ),
        )

    if attestation.refused:
        event = ShieldEvent(
            position="unknown",
            requested_action=body.action,
            reason=body.reason,
            refused=True,
            refusal_reason=attestation.refusal_reason,
        )
    else:
        # Parsed only to read fields out of it for display. The signature was
        # verified by `shutter` over the grant, not by us over this.
        body_json = json.loads(attestation.attestation_json or "{}")
        event = ShieldEvent(
            position=body_json.get("position", "unknown"),
            commanded_angle=body_json.get("commanded_angle"),
            position_basis=body_json.get("position_basis", "commanded"),
            requested_action=body.action,
            reason=body.reason,
        )

    await runtime.emit(event, incident_id)
    return event
```

Add `import json` to the top of `api.py`.

- [ ] **Step 7: Give the master clients a grant issuer**

In `app/backend/hawkeye_backend/master/base.py`, add to the `MasterClient` protocol:

```python
    async def issue_shutter_grant(self, *, action: str, reason: str) -> str:
        """Return a signed grant as the opaque JSON string it crosses the wire as.

        A string, never an object. The bytes that were signed must be the bytes
        that are verified, and any layer that parses and re-serializes breaks
        every signature in a way indistinguishable from tampering.
        """
        ...
```

In `master/simulated.py`, add to `SimulatedMasterClient`:

```python
    async def issue_shutter_grant(self, *, action: str, reason: str) -> str:
        """A grant signed by this process's own demo key.

        Simulated mode has no `agents/master`, so the hub signs with a key it
        generated at startup. `shutter` still verifies the signature and still
        refuses anything it cannot, which is the property being demonstrated;
        what is simulated is which agent holds the key, not whether the check
        happens.
        """
        import json
        from datetime import timedelta

        from hawkeye_backend.models.common import utc_now
        from hawkeye_backend.verification.b64 import b64u_encode
        from hawkeye_backend.verification.canonical import canonicalize

        now = utc_now()
        payload = {
            "schema_version": "1.0",
            "nonce": self._next_nonce(),
            "issuer": self._master_ansname,
            "action": action,
            "reason": reason,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=10)).isoformat(),
        }
        signature = self._grant_key.sign(canonicalize(payload))
        payload["signature"] = b64u_encode(signature)
        return json.dumps(payload, separators=(",", ":"))

    def _next_nonce(self) -> str:
        """A fresh nonce per grant. Never cached.

        Holding one open across two grants would give an attacker a window in
        which a captured grant is still live. `agents/master/shutter_client.py`
        states this and this mirrors it.
        """
        import secrets

        return secrets.token_urlsafe(12)
```

In that class's `__init__`, add:

```python
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        # Generated per process, never persisted. A demo key that survived a
        # restart would be a key somebody could eventually find.
        self._grant_key = Ed25519PrivateKey.generate()
        self._master_ansname = "ans://v1.0.0.master.hawkeye.invalid"
```

In `master/live.py`, add:

```python
    async def issue_shutter_grant(self, *, action: str, reason: str) -> str:
        """Ask the real master to sign a grant. Returned opaque, never re-parsed."""
        payload = await self._post(
            "/v1/shutter/grant", {"action": action, "reason": reason}
        )
        grant = payload.get("grant_json")
        if not isinstance(grant, str) or not grant:
            raise MasterUnavailable("master returned no grant_json")
        return grant
```

- [ ] **Step 8: Run the tests**

```bash
cd app/backend && .venv/bin/python -m pytest tests/test_shutter_api.py -q
cd app/backend && .venv/bin/python -m pytest -q
```

Expected: 5 passed, then the whole suite green.

- [ ] **Step 9: Commit**

```bash
git add app/backend/hawkeye_backend/ app/backend/tests/test_shutter_api.py
git commit -m "Move the shield from any surface, and publish the refusal too"
```

---

## Task 11: The Pi forwards grants to the local shutter agent

**Files:**
- Modify: `vision/hawkeye_vision/edge.py`

- [ ] **Step 1: Replace `_receive`**

In `vision/hawkeye_vision/edge.py`, replace the whole `_receive` function with:

```python
async def _receive(socket) -> None:  # noqa: ANN001 - websockets client protocol
    """Handle everything the hub sends down.

    A grant is forwarded verbatim to the shutter agent on this box. Verbatim is
    the whole requirement: `shutter` verifies the signature over exactly these
    bytes, so this process must not parse, reformat or re-serialize the grant on
    its way through. It is a pipe, not a participant.

    That is also why relaying a grant over this link costs nothing in trust. The
    signature is what `shutter` checks, and it checks it no matter how the bytes
    arrived.
    """
    import httpx

    from hawkeye_backend.edge.wire import EdgeAttestation, EdgeError, EdgeGrant, decode_edge_message

    shutter_url = os.environ.get("HAWKEYE_SHUTTER_URL", "http://127.0.0.1:8106")

    async for raw in socket:
        if isinstance(raw, bytes):
            logger.warning("edge: the hub sent binary, which it never should. Ignored.")
            continue
        try:
            message = decode_edge_message(raw)
        except Exception:
            logger.exception("edge: the hub sent something unparseable")
            continue

        if isinstance(message, EdgeError):
            logger.error("edge: the hub refused us (%s): %s", message.code, message.message)
            continue

        if not isinstance(message, EdgeGrant):
            logger.info("edge: ignoring %s, which this side does not handle", message.kind)
            continue

        logger.info("edge: forwarding a grant to the shutter at %s", shutter_url)
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                response = await http.post(
                    f"{shutter_url}/a2a",
                    content=message.grant_json,
                    headers={"content-type": "application/json"},
                )
            if response.status_code >= 400:
                await socket.send(
                    EdgeAttestation(
                        request_id=message.request_id,
                        refused=True,
                        refusal_reason=f"shutter returned {response.status_code}: {response.text[:200]}",
                    ).model_dump_json()
                )
                continue
            await socket.send(
                EdgeAttestation(
                    request_id=message.request_id,
                    attestation_json=response.text,
                    refused=False,
                ).model_dump_json()
            )
        except Exception as exc:  # noqa: BLE001
            # Reported as a refusal rather than dropped. A hub waiting on an
            # attestation that never comes reports the position unknown, which
            # is correct but slow; saying so immediately is better.
            logger.exception("edge: could not reach the shutter")
            await socket.send(
                EdgeAttestation(
                    request_id=message.request_id,
                    refused=True,
                    refusal_reason=f"could not reach the shutter agent: {exc}",
                ).model_dump_json()
            )
```

- [ ] **Step 2: Exercise the whole path with a stub servo**

On the Mac, three terminals.

```bash
# 1. the hub
cd app/backend && HAWKEYE_EDGE_TOKEN=dev-token .venv/bin/python -m hawkeye_backend.main

# 2. the shutter agent, stub backend, no hardware needed
cd agents && python -m agents shutter --port 8106

# 3. the edge
cd vision && python3 -m hawkeye_vision.edge --hub ws://127.0.0.1:8787 --token dev-token
```

Then:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/shutter \
  -H 'content-type: application/json' \
  -d '{"action":"open","reason":"manual check"}' | python3 -m json.tool
```

Expected: either a `ShieldEvent` with `position` set, or one with `refused: true` and a named reason. Both are correct outcomes. A hang is not, and means the attestation is not coming back.

Watch `/live` in a browser at the same time: the shield line must appear in the event list.

- [ ] **Step 3: Commit**

```bash
git add vision/hawkeye_vision/edge.py
git commit -m "Forward a grant to the shutter verbatim, because the bytes are the signature"
```

---

## Task 12: Document the seams

**Files:**
- Modify: `docs/swapping-in-real-parts.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the four rows**

Append to `docs/swapping-in-real-parts.md`, matching the existing table or section format in that file:

```markdown
## The edge link (added 2026-09-20)

| Thing | Seam | Flip it | Tell the flip worked | Half-flipped state that looks like something else |
|---|---|---|---|---|
| **Camera** | `FrameSource` in `vision/hawkeye_vision/frames.py` | Run `python -m hawkeye_vision.edge --source camera` on the Pi instead of `--source fixture` | `GET /v1/hub` reports `camera.source` as `camera-uvc` and `camera.live` true | A fixture running with `--source camera` is impossible by construction, because `source` comes from the `FrameSource` and not from the flag. A **stale** camera is the dangerous one: `linked` true, `live` false. The page dims and captions it; anything that only reads `linked` will draw an old room as the current one |
| **Narration** | `GeminiLiveNarrator` in `vision/hawkeye_vision/narrate.py` | Set `GEMINI_API_KEY` and run the narrator against the relay | Narration lines appear on `/live` with a room and a window | No key means no lines at all, which looks exactly like a quiet room. Check the vision process's log, not the page |
| **Servo** | `ShutterBackend` in `agents/agents/shutter/backend.py` | Run the shutter agent on the Pi with the pigpio backend instead of `StubShutter` | `ShieldEvent.source` is `servo-gpio` rather than `servo-stub`, and the shield physically moves | A servo browning out the Pi under load reboots the box mid-move. The attestation says `open` because the position is **commanded**, never measured. The frame going dark is the only thing that catches a jammed or unpowered shield |
| **Replay archive** | `ReplayArchive` in `app/backend/hawkeye_backend/replay/archive.py` | `HAWKEYE_REPLAY_ARCHIVE=mongodb` with a URI | `GET /v1/replay` reports `archive.connected` true | A configured but unreachable archive looks exactly like "nothing has happened yet" unless the page reads `archive`, which it does |
```

- [ ] **Step 2: Update the root CLAUDE.md**

In the "What exists right now" list, update the `app/backend` and `vision/` entries to say the edge link exists, and add the topology diagram from the spec's section 1 under Architecture.

- [ ] **Step 3: Commit**

```bash
git add docs/swapping-in-real-parts.md CLAUDE.md
git commit -m "Record the four new seams and which half-flipped states lie"
```

---

## Final verification

- [ ] **Run every suite**

```bash
cd app/backend && .venv/bin/python -m pytest -q
cd ../../vision && python3 -m pytest -q
cd ../agents && python -m pytest -q
```

Expected: all green, zero skips.

- [ ] **Run the whole thing end to end**

Four processes, as in Task 11 step 2, plus a browser on `/live`. Then:

1. Video moves on `/live`.
2. `POST /v1/vision/narration` puts a line in the event list.
3. `POST /v1/shutter` moves the shield and the result appears in the event list.
4. Kill the edge process. Within three seconds the page says **camera unreachable** and dims the last frame. It does not keep showing it as live. This is the one that matters.

- [ ] **Code review**

Only now, per the instruction to hold review until the end. Use `superpowers:requesting-code-review` across the whole branch.
