"""Gemini Live narration: one session per incident, frames in, sentences out.

This is the generated half of the camera path, and it is deliberately the only
module in this package that touches the network.

**It owns no camera and no disk.** That is the whole reason the file is shaped
this way. `vision/CLAUDE.md` requires that a Gemini Live session which drops
mid-incident costs narration and costs nothing else, and the cheapest way to
guarantee that is for the narrator to have nothing else to lose: it is handed
JPEG bytes that somebody else already captured, and it writes nothing anywhere.
The recorder cannot be affected by a failure here because it shares no state
with this object.

## What the caller owes this module

`offer` sends a frame to a language model and gets back a description of it. It
has no idea whether the lens is uncovered or whether the room is lit, and it
must not guess:

- **Do not call `offer` without a current shutter attestation.** No attestation,
  or a stale one, is `Unknown(reason="shield_closed")`, decided upstream.
- **Do not call `offer` on a frame below the darkness threshold.** The model will
  cheerfully describe an unlit room, which is the failure that looks like
  success. `hawkeye_vision.lighting` decides that, and `TOO_DARK` means
  `Unknown(reason="frame_too_dark")` with no frame sent.

Both gates live upstream because both are about *whether a claim may exist*, and
this module is about what the sentence says once one may.

## The transcription wrinkle, and why the code looks like this

Measured 2026-09-19 against the project's key. Every live-capable model the key
can reach - `gemini-3.8-live`, `gemini-3.1-flash-live-preview`, the
native-audio family - **refuses `response_modalities=["TEXT"]`**:

    APIError: 1007. The requested combination of response modalities (TEXT)
    is not supported by the model.

The live models on this key are audio-native. So the session asks for AUDIO and
turns on `output_audio_transcription`, and the narration text arrives as the
transcript of speech the model is synthesising. The audio itself is discarded:
`agents/caller` speaks through ElevenLabs, and a second voice on the same call
would be a second thing for a dispatcher to mistrust.

This matters for latency, which is why `_reader` is a separate task rather than
a loop inside `offer`. Measured against the live endpoint on this key:

    connect               0.21s
    first transcript      0.70 - 0.92s
    generation_complete   1.77 - 2.89s   <- the model has finished thinking
    turn_complete         4.28 - 6.82s   <- the server has finished draining audio

**`generation_complete` is the signal, not `turn_complete`.** The 2.5 to 4
second gap between them is audio nobody listens to being streamed to a client
that throws it away, and waiting it out would put narration past the budget in
root `CLAUDE.md`. So the reader publishes at `generation_complete` and lets the
audio drain behind it, while the claim is already on its way to the watch.

## One frame per turn, and the frames in between are dropped

Learned the hard way, 2026-09-19, against the live endpoint.

The obvious shape - stream frames with `send_realtime_input` and ask for a
sentence with `send_client_content` - narrates exactly once and then wedges. The
second turn is accepted and never generates, never completes, and the session
sits there looking healthy while the room goes undescribed. Mixing a realtime
input stream with explicit client turns puts the server's activity detection and
the turn state machine in disagreement, and the turn loses.

So a turn is self-contained: the JPEG and the prompt go together as two parts of
one `send_client_content`, and there is no realtime stream at all. Four turns in
a row cycle cleanly this way, which the mixed shape never managed twice.

The cost is real and is stated rather than hidden. A turn takes four to seven
seconds end to end and frames arrive at 1 fps, so **roughly one frame in five is
described and the rest are dropped** - counted in `frames_dropped`, not silently
discarded. The session still holds context across turns, which is the thing
`vision/CLAUDE.md` actually needs from the Live API: "the person has moved into
the hallway, still carrying the bag" requires remembering the bag, and it
remembers it. What is lost is the pretence that every frame was looked at, and
root `CLAUDE.md` requires the narration be described as a sequence of
observations rather than continuous tracking anyway.

## Why the Live API rather than a call per frame

Settled in `vision/CLAUDE.md`: the session holds context across the incident.
"The person has moved into the hallway, still carrying the bag" requires
remembering the bag, and per-frame requests remember nothing, so the caller
agent ends up reading the operator the same sentence four times.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps google-genai optional
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

#: The model to open a session against.
#:
#: Pinned rather than "latest" on purpose: the response-modality failure above
#: is per-model, so a silently moving target here is a demo that stops narrating
#: for a reason nobody can see. Confirmed working 2026-09-19.
DEFAULT_MODEL = "gemini-3.8-live"

#: `google-genai` needs this to reach the Live endpoint.
API_VERSION = "v1alpha"

#: What the narrator is told it is. Every limit in `vision/CLAUDE.md` that the
#: model itself can honour is stated here, in the model's own instructions,
#: rather than being checked after the fact - a sentence that was never
#: generated cannot be accidentally spoken to a dispatcher.
#:
#: The ones it cannot honour are enforced in code instead: the shield gate, the
#: darkness gate, and the `source: generated` label on every claim.
SYSTEM_INSTRUCTION = """\
You are the narrator for a single fixed security camera covering one room: {room}.

Reply with ONE short factual sentence about the current frame, then stop. No
preamble, no greeting, no offer to help.

Describe what a witness would say: how many people are visible, their build,
their clothing, what they are carrying, and what they are doing. Prefer
"a person in a dark jacket" over any stronger noun.

Rules you must not break:
- Never name or identify anyone. You do not know who these people are.
- Never say anything about a room other than {room}, or about the building as a
  whole. You can see one room.
- If nobody is visible, say exactly: No people are visible.
- If you cannot tell, say so. Do not fill a gap with a plausible detail.
- Never mention cameras, frames, images, or that you are a model. The sentence
  is read aloud to a 911 dispatcher.
"""

#: Split the running transcript on sentence terminators. The reader publishes a
#: narration the moment one of these lands, which is what buys the ~3s budget.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

#: The reason string that goes into `Unknown(field="vision.description", ...)`
#: when this module cannot produce a sentence. Named once, here, because
#: `vision/CLAUDE.md` specifies the exact string and two spellings of it in two
#: files is how a required behaviour quietly stops being tested.
UNREACHABLE = "narrator_unreachable"


#: Longest edge a frame is shrunk to before it goes on the wire.
#:
#: Narration-specific rather than a capture setting, which is why it lives here
#: and not in `config.py`: the recorded segments keep full resolution because
#: they are evidence, and the only thing being traded away is upload cost on a
#: Pi 4B's uplink. A description of a person's build and clothing survives 768px
#: intact; the model is not reading a licence plate and must never be asked to.
NARRATION_LONG_EDGE = 768

#: JPEG quality for the same. Below about 70 the compression artefacts start
#: inventing texture, and invented texture in a frame a dispatcher is being read
#: from is the exact failure this project exists to not have.
NARRATION_JPEG_QUALITY = 80


def encode_jpeg(
    image,  # noqa: ANN001 - np.ndarray, untyped to keep numpy off the import path
    *,
    long_edge: int = NARRATION_LONG_EDGE,
    quality: int = NARRATION_JPEG_QUALITY,
) -> bytes:
    """One BGR frame, shrunk and compressed for the wire.

    Separate from `offer` so the sampler can encode once and hand the same bytes
    to anything else that wants them, and so a test can assert on the bytes
    without a session existing.
    """
    import cv2

    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > long_edge:
        scale = long_edge / longest
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("OpenCV could not encode the frame as JPEG")
    return buffer.tobytes()


def utc_now() -> datetime:
    """Timezone-aware now. Every timestamp in this package is UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Narration:
    """One sentence the model produced, and what it was produced from.

    `frame_index` is the frame that was most recently offered when the sentence
    landed, not a frame the model was asked about in isolation. The Live session
    holds context, so a sentence can legitimately depend on frames before this
    one - that is the point of using it - and the field is the anchor into the
    recording, not a claim of one-to-one correspondence.
    """

    text: str
    at: datetime
    frame_index: int
    model: str
    latency_s: float
    """Seconds from the turn being requested to this sentence arriving.

    Carried because the timing budget in root `CLAUDE.md` is a target with a
    test behind it, and the only way to keep it honest is to measure it on the
    real path rather than in a benchmark.
    """


class Narrator(Protocol):
    """Something that turns frames into sentences, or says why it cannot."""

    @property
    def available(self) -> bool:
        """False once the session is gone. Claims become `Unknown` from here."""

    @property
    def reason(self) -> str | None:
        """Why not, when `available` is False. `UNREACHABLE`, usually."""

    async def start(self) -> None:
        """Open the session. Safe to call again after a failure."""

    async def offer(self, jpeg: bytes, frame_index: int) -> None:
        """Hand over one sampled frame. Never raises for a dead session."""

    def poll(self) -> Narration | None:
        """The next finished sentence, or None. Never blocks."""

    async def aclose(self) -> None:
        """Close the session. Idempotent."""


def drain(narrator: Narrator) -> list[Narration]:
    """Every sentence waiting, oldest first. The normal way to read one.

    A single frame can produce more than one sentence and a dropped frame can
    produce none, so the sampler drains rather than assuming a 1:1 rhythm.
    """
    out: list[Narration] = []
    while (narration := narrator.poll()) is not None:
        out.append(narration)
    return out


class StubNarrator:
    """Scripted sentences, no network. What every test in this package runs on.

    It is not a mock in the usual sense: it implements the same contract with
    the same failure semantics, including the one that matters - going
    unavailable mid-incident without raising into the sampler's loop.
    """

    def __init__(
        self,
        lines: "Sequence[str]" = (),
        *,
        fail_after: int | None = None,
        model: str = "stub",
    ) -> None:
        self._lines = deque(lines)
        self._fail_after = fail_after
        self._model = model
        self._offers = 0
        self._pending: deque[Narration] = deque()
        self._available = False
        self._reason: str | None = "not started"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def reason(self) -> str | None:
        return self._reason

    async def start(self) -> None:
        self._available = True
        self._reason = None

    async def offer(self, jpeg: bytes, frame_index: int) -> None:
        if not self._available:
            return
        self._offers += 1
        if self._fail_after is not None and self._offers > self._fail_after:
            self._fail(UNREACHABLE)
            return
        if not self._lines:
            return
        self._pending.append(
            Narration(
                text=self._lines.popleft(),
                at=utc_now(),
                frame_index=frame_index,
                model=self._model,
                latency_s=0.0,
            )
        )

    def poll(self) -> Narration | None:
        return self._pending.popleft() if self._pending else None

    async def aclose(self) -> None:
        self._available = False
        self._reason = "closed"

    def _fail(self, reason: str) -> None:
        self._available = False
        self._reason = reason


class GeminiLiveNarrator:
    """One Gemini Live session, held open for the duration of an incident.

    Three things about the shape, all of them load-bearing:

    **One reader task owns the socket.** `session.receive()` is a single async
    generator over one websocket and is not safe to iterate from two places, so
    exactly one task consumes it and publishes onto a queue. This is also what
    lets a sentence be published at 0.7s while the rest of the turn drains
    behind it.

    **One frame per turn, and a turn at a time.** A frame offered while a turn
    is in flight is dropped and counted, not queued. Queueing would narrate the
    past: frames arrive at 1 fps, a turn takes four to seven seconds, and a
    backlog would grow for the length of the incident until the sentence being
    read to a dispatcher described a room somebody left a minute ago.

    **A dead session stays dead until somebody restarts it.** There is no hidden
    reconnect loop. `available` goes False with a reason, the agent's next tick
    sees that and emits `Unknown(reason="narrator_unreachable")`, and restarting
    is `start()` again - a decision made in the open by the caller rather than a
    background task quietly papering over a link that is not working.
    """

    def __init__(
        self,
        api_key: str,
        *,
        room: str,
        model: str = DEFAULT_MODEL,
        client: object | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("no Gemini API key: narration cannot start without one")
        self._api_key = api_key
        self._room = room
        self._model = model
        # Injected only by tests, which hand in a fake with the same surface.
        # Nothing in the shipping path passes it.
        self._client = client

        self._session: object | None = None
        self._context: object | None = None
        self._reader: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Narration] = asyncio.Queue()

        self._available = False
        self._reason: str | None = "not started"
        self._turn_open = False
        self._turn_started: float = 0.0
        self._frame_index = -1
        self._partial = ""
        self._frames_dropped = 0

    # ------------------------------------------------------------------ state

    @property
    def available(self) -> bool:
        return self._available

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def model(self) -> str:
        return self._model

    @property
    def frames_dropped(self) -> int:
        """Frames offered while a turn was in flight, and therefore never seen.

        Carried rather than swallowed. The claim this narrator feeds says the
        narration is a sequence of observations rather than continuous tracking,
        and this is the number that makes that statement checkable instead of
        merely asserted.
        """
        return self._frames_dropped

    # ----------------------------------------------------------------- session

    async def start(self) -> None:
        """Open the session and start reading. Failure is reported, not raised.

        A narrator that raises on connect takes the sampler's loop down with it,
        and the recording lives in that loop. So the only thing a failure here
        changes is `available`.
        """
        await self.aclose()
        try:
            client = self._client or self._build_client()
            self._context = client.aio.live.connect(  # type: ignore[attr-defined]
                model=self._model, config=self._config()
            )
            self._session = await self._context.__aenter__()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - every failure is the same failure
            logger.warning("gemini live session did not open: %s", exc)
            self._fail(UNREACHABLE)
            return
        self._available = True
        self._reason = None
        self._reader = asyncio.create_task(self._read(), name="gemini-live-reader")

    async def offer(self, jpeg: bytes, frame_index: int) -> None:
        """Offer one sampled frame. Described if the model is idle, dropped if not."""
        if not self._available or self._session is None:
            return
        if self._turn_open:
            self._frames_dropped += 1
            return
        self._frame_index = frame_index
        self._turn_open = True
        self._turn_started = asyncio.get_running_loop().time()
        try:
            await self._send_turn(jpeg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini live send failed: %s", exc)
            self._fail(UNREACHABLE)

    def poll(self) -> Narration | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def aclose(self) -> None:
        """Close the session and stop the reader. Safe to call on a dead one."""
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        context, self._context = self._context, None
        self._session = None
        if context is not None:
            try:
                await context.__aexit__(None, None, None)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                logger.debug("gemini live session close was untidy: %s", exc)
        self._turn_open = False
        self._partial = ""
        if self._available:
            self._available = False
            self._reason = "closed"

    # ------------------------------------------------------------- the reader

    async def _read(self) -> None:
        """Consume the socket for the length of the incident, one turn at a time.

        **`receive()` is re-entered after every turn, and that is not a style
        choice.** Measured against the live endpoint 2026-09-19: a single
        long-lived `async for` over `receive()` delivers the first turn
        completely - transcript, `generation_complete`, `turn_complete` - and
        then yields nothing ever again. It does not raise and it does not end;
        the task simply parks inside the generator while every subsequent turn
        is accepted by the server and never heard.

        That failure is invisible from the outside. The session reports healthy,
        frames are accepted, turns are requested, and the room goes undescribed
        for the length of the incident. Breaking out at `turn_complete` and
        calling `receive()` again cycles indefinitely.
        """
        try:
            while True:
                async for response in self._session.receive():  # type: ignore[union-attr]
                    if self._consume(response):
                        break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a dropped socket is ordinary
            logger.warning("gemini live session dropped: %s", exc)
            self._fail(UNREACHABLE)

    def _consume(self, response: object) -> bool:
        """One event off the socket. Returns True when the turn is over.

        The return value is what tells `_read` to re-enter `receive()`.
        """
        content = getattr(response, "server_content", None)
        if content is None:
            return False

        transcription = getattr(content, "output_transcription", None)
        chunk = getattr(transcription, "text", None) if transcription is not None else None
        if chunk:
            self._partial += chunk
            self._publish_sentences()

        if getattr(content, "generation_complete", False):
            # The model has finished thinking. Everything after this is audio
            # being drained to a client that discards it, and waiting for that
            # is two to four seconds of the budget spent on nothing.
            #
            # Whatever is left in `_partial` never got a terminator followed by
            # whitespace, which is the normal way a final sentence arrives: the
            # transcript lands as "No motion is detected ", "in the monitored",
            # " area." and the last chunk closes the sentence without a space
            # after it. Publish it rather than dropping it.
            self._flush()

        if getattr(content, "turn_complete", False):
            # The server is done. Only now may another turn be sent - asking
            # sooner is what wedges the session. `_flush` again in case a turn
            # ended without ever generating.
            self._flush()
            self._turn_open = False
            return True

        return False

    def _flush(self) -> None:
        """Publish whatever transcript is held, and hold nothing. Idempotent."""
        partial, self._partial = self._partial, ""
        self._publish(partial)

    def _publish_sentences(self) -> None:
        *complete, remainder = _SENTENCE_END.split(self._partial)
        for sentence in complete:
            self._publish(sentence)
        self._partial = remainder

    def _publish(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        loop = asyncio.get_running_loop()
        self._queue.put_nowait(
            Narration(
                text=text,
                at=utc_now(),
                frame_index=self._frame_index,
                model=self._model,
                latency_s=max(0.0, loop.time() - self._turn_started),
            )
        )

    # ------------------------------------------------------------- the wire

    def _build_client(self) -> object:
        # Imported here rather than at module scope so that importing this
        # package - which the fast test suite does - never needs google-genai
        # installed, matching how `yolo_tracker` treats torch.
        from google import genai

        return genai.Client(api_key=self._api_key, http_options={"api_version": API_VERSION})

    def _config(self) -> object:
        from google.genai import types

        return types.LiveConnectConfig(
            # AUDIO, not TEXT, and not by preference. See the module docstring:
            # every live model this key can reach rejects TEXT outright.
            response_modalities=["AUDIO"],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=SYSTEM_INSTRUCTION.format(room=self._room),
        )

    async def _send_turn(self, jpeg: bytes) -> None:
        """One turn carrying the frame and the prompt together.

        Deliberately not `send_realtime_input` plus a separate client turn. See
        the module docstring: that shape narrates once and then wedges.
        """
        from google.genai import types

        await self._session.send_client_content(  # type: ignore[union-attr]
            turns=types.Content(
                role="user",
                parts=[
                    types.Part(inline_data=types.Blob(data=jpeg, mime_type="image/jpeg")),
                    types.Part(text="Describe the current frame now."),
                ],
            ),
            turn_complete=True,
        )

    # ------------------------------------------------------------------ misc

    def _fail(self, reason: str) -> None:
        self._available = False
        self._reason = reason
        self._turn_open = False
