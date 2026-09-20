"""The narrator's contract, and the one failure that matters most.

Every test here runs against a fake session. There is no network in this file
and there must never be: the live path is exercised by `test_narrate_live.py`,
which is marked `integration` and needs a key.

The test this module exists for is `test_a_dropped_session_never_raises_at_the
_sampler`. `vision/CLAUDE.md` requires that a Gemini Live session which drops
mid-incident stops narration and leaves the recording running, and the only
structural guarantee of that is the narrator never raising into the loop that
owns the recorder. Everything else here is supporting detail.
"""

from __future__ import annotations

import asyncio
from collections import deque

import numpy as np
import pytest

from hawkeye_vision.narrate import (
    UNREACHABLE,
    GeminiLiveNarrator,
    Narration,
    StubNarrator,
    drain,
    encode_jpeg,
)

# --------------------------------------------------------------------- a fake


class FakeSession:
    """A Gemini Live session that yields whatever the test scripted.

    Two properties are copied from the real thing because the narrator's
    correctness depends on both, and a fake that got either wrong would have
    hidden the bug that cost the most to find:

    **The event stream is consumed, not replayed.** `receive()` is re-entered
    after every turn, and re-entry continues from where the last one stopped. A
    fake that restarted its script on re-entry would loop forever on turn one
    and look, from the test's side, exactly like the real bug looks from
    outside: healthy, busy, and describing nothing.

    **It parks rather than ending.** The real generator stops yielding between
    turns without raising and without terminating, so a reader that only
    re-enters on `StopAsyncIteration` never re-enters at all.
    """

    def __init__(self, events: list[object], *, raise_after: int | None = None) -> None:
        self._events = deque(events)
        self.raise_after = raise_after
        self.turns_requested = 0
        self._delivered = 0
        self._parked = asyncio.Event()

    async def receive(self):
        while self._events:
            if self.raise_after is not None and self._delivered >= self.raise_after:
                raise ConnectionError("socket went away mid-incident")
            event = self._events.popleft()
            self._delivered += 1
            yield event
            await asyncio.sleep(0)
        if self.raise_after is not None and self._delivered >= self.raise_after:
            raise ConnectionError("socket went away mid-incident")
        await self._parked.wait()

    async def send_client_content(self, *, turns, turn_complete) -> None:
        self.turns_requested += 1


class FakeConnect:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeClient:
    """Shaped like `genai.Client`, down to `client.aio.live.connect(...)`."""

    def __init__(self, session: FakeSession | None = None, *, fail: bool = False) -> None:
        self.session = session
        self.fail = fail
        self.aio = self

    @property
    def live(self):
        return self

    def connect(self, *, model, config):
        if self.fail:
            raise ConnectionError("no route to the live endpoint")
        return FakeConnect(self.session)


class Transcription:
    def __init__(self, text: str) -> None:
        self.text = text


class ServerContent:
    """Shaped like the real one, including the two different "done" signals.

    `generation_complete` means the model stopped thinking; `turn_complete`
    means the server stopped sending audio. Measured 2.5 to 4 seconds apart on
    the live endpoint, which is why the narrator treats them differently and why
    this fake keeps them separate.
    """

    def __init__(
        self,
        text: str | None = None,
        *,
        generation_complete: bool = False,
        turn_complete: bool = False,
    ) -> None:
        self.output_transcription = Transcription(text) if text is not None else None
        self.generation_complete = generation_complete
        self.turn_complete = turn_complete


class Event:
    def __init__(self, content: ServerContent | None) -> None:
        self.server_content = content


def narrator(session: FakeSession | None = None, *, fail: bool = False) -> GeminiLiveNarrator:
    return GeminiLiveNarrator(
        "test-key", room="living room", client=FakeClient(session, fail=fail)
    )


# ------------------------------------------------------------------- encoding


def test_encode_jpeg_shrinks_a_large_frame_to_the_long_edge():
    encoded = encode_jpeg(np.full((1080, 1920, 3), 120, np.uint8))

    import cv2

    decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
    assert max(decoded.shape[:2]) == 768
    # Aspect ratio survives, or an overlay drawn from the tracker's normalised
    # boxes would not line up with what the model was shown.
    assert decoded.shape[1] / decoded.shape[0] == pytest.approx(1920 / 1080, abs=0.01)


def test_encode_jpeg_leaves_a_small_frame_alone():
    decoded_shape = (480, 640, 3)
    encoded = encode_jpeg(np.full(decoded_shape, 90, np.uint8))

    import cv2

    decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == decoded_shape


# ----------------------------------------------------------------------- stub


@pytest.mark.asyncio
async def test_the_stub_hands_back_its_scripted_lines():
    stub = StubNarrator(["A person in a dark jacket is standing by the door."])
    await stub.start()
    await stub.offer(b"jpeg", 7)

    [narration] = drain(stub)
    assert narration.text.startswith("A person in a dark jacket")
    assert narration.frame_index == 7
    assert drain(stub) == []


@pytest.mark.asyncio
async def test_the_stub_goes_unavailable_without_raising():
    stub = StubNarrator(["one", "two"], fail_after=1)
    await stub.start()
    await stub.offer(b"jpeg", 0)
    await stub.offer(b"jpeg", 1)

    assert stub.available is False
    assert stub.reason == UNREACHABLE


# ------------------------------------------------------------------ the wire


@pytest.mark.asyncio
async def test_a_sentence_is_published_before_the_turn_completes():
    """The 3.0s budget. `turn_complete` arrives at ~4s; the sentence does not."""
    session = FakeSession(
        [Event(ServerContent("A person is standing by the door. "))]
    )
    live = narrator(session)
    await live.start()
    await live.offer(b"jpeg", 3)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    [narration] = drain(live)
    assert isinstance(narration, Narration)
    assert narration.text == "A person is standing by the door."
    assert narration.frame_index == 3
    assert narration.model == "gemini-3.8-live"
    await live.aclose()


@pytest.mark.asyncio
async def test_two_sentences_in_one_turn_become_two_narrations():
    session = FakeSession(
        [Event(ServerContent("A person is by the door. They are carrying a bag. "))]
    )
    live = narrator(session)
    await live.start()
    await live.offer(b"jpeg", 1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert [n.text for n in drain(live)] == [
        "A person is by the door.",
        "They are carrying a bag.",
    ]
    await live.aclose()


@pytest.mark.asyncio
async def test_an_unterminated_tail_is_published_rather_than_dropped():
    """A sentence the model trailed off on is still the only description we have."""
    session = FakeSession(
        [
            Event(ServerContent("A person is moving toward the hallway")),
            Event(ServerContent(generation_complete=True)),
        ]
    )
    live = narrator(session)
    await live.start()
    await live.offer(b"jpeg", 2)
    for _ in range(4):
        await asyncio.sleep(0)

    assert [n.text for n in drain(live)] == ["A person is moving toward the hallway"]
    await live.aclose()


@pytest.mark.asyncio
async def test_frames_offered_during_a_turn_are_dropped_and_counted():
    """Not queued. A backlog would narrate a room somebody left a minute ago.

    Counted rather than silently discarded, because the claim this narrator
    feeds says the narration is a sequence of observations and this is the
    number that makes that checkable.
    """
    session = FakeSession([])
    live = narrator(session)
    await live.start()
    for index in range(4):
        await live.offer(b"jpeg", index)

    assert session.turns_requested == 1
    assert live.frames_dropped == 3
    await live.aclose()



@pytest.mark.asyncio
async def test_a_new_turn_waits_for_the_server_not_just_the_model():
    """`generation_complete` publishes; only `turn_complete` opens the next turn.

    Sending a turn while the server is still draining the last one is what
    wedges the session - it accepts the turn, never generates, never completes,
    and looks healthy the whole time.
    """
    # The model has finished thinking and the server has not finished sending.
    thinking_done = FakeSession(
        [Event(ServerContent("Nobody is visible.", generation_complete=True))]
    )
    live = narrator(thinking_done)
    await live.start()
    await live.offer(b"jpeg", 0)
    for _ in range(4):
        await asyncio.sleep(0)

    # The sentence is out - that is the budget being met - and the turn is not.
    assert [n.text for n in drain(live)] == ["Nobody is visible."]
    await live.offer(b"jpeg", 1)
    assert thinking_done.turns_requested == 1
    assert live.frames_dropped == 1
    await live.aclose()

    # Same turn, now with the server done too. The next frame gets a turn.
    server_done = FakeSession(
        [
            Event(ServerContent("Nobody is visible.", generation_complete=True)),
            Event(ServerContent(turn_complete=True)),
        ]
    )
    live = narrator(server_done)
    await live.start()
    await live.offer(b"jpeg", 0)
    for _ in range(6):
        await asyncio.sleep(0)
    await live.offer(b"jpeg", 1)

    assert server_done.turns_requested == 2
    assert live.frames_dropped == 0
    await live.aclose()


@pytest.mark.asyncio
async def test_one_reader_task_survives_more_than_one_turn():
    """The bug that cost the most, and the one a fake can hide.

    A single long-lived `async for` over `receive()` delivers turn one and then
    yields nothing ever again - no raise, no end, just silence, while the
    session reports healthy and every later turn is accepted and never heard.
    The reader has to break at `turn_complete` and call `receive()` again.

    Two turns is the whole test. One turn passes with the bug present.
    """
    session = FakeSession(
        [
            Event(ServerContent("A person is by the door.", generation_complete=True)),
            Event(ServerContent(turn_complete=True)),
            Event(ServerContent("They have moved to the hallway.", generation_complete=True)),
            Event(ServerContent(turn_complete=True)),
        ]
    )
    live = narrator(session)
    await live.start()

    await live.offer(b"jpeg", 0)
    for _ in range(6):
        await asyncio.sleep(0)
    await live.offer(b"jpeg", 1)
    for _ in range(6):
        await asyncio.sleep(0)

    assert session.turns_requested == 2
    assert [n.text for n in drain(live)] == [
        "A person is by the door.",
        "They have moved to the hallway.",
    ]
    await live.aclose()


@pytest.mark.asyncio
async def test_the_sentence_lands_at_generation_complete_not_turn_complete():
    """The budget. Measured 2.5 to 4 seconds between the two on the live endpoint.

    The transcript arrives in fragments and the last one closes the sentence
    without trailing whitespace - "No motion is detected ", "in the monitored",
    " area." - so the splitter alone never fires on it. Publishing at
    `generation_complete` is what gets it out.
    """
    session = FakeSession(
        [
            Event(ServerContent("No motion is detected ")),
            Event(ServerContent("in the monitored")),
            Event(ServerContent(" area.", generation_complete=True)),
        ]
    )
    live = narrator(session)
    await live.start()
    await live.offer(b"jpeg", 5)
    for _ in range(6):
        await asyncio.sleep(0)

    assert [n.text for n in drain(live)] == ["No motion is detected in the monitored area."]
    await live.aclose()


# --------------------------------------------------------------- the failures


@pytest.mark.asyncio
async def test_a_dropped_session_never_raises_at_the_sampler():
    """The test this file exists for.

    `vision/CLAUDE.md`: a Gemini Live session that drops costs narration and
    costs nothing else. The recorder runs in the sampler's loop, so the
    narrator raising into that loop is the one way it could cost more. It does
    not raise on the read, and it does not raise on the sends that follow.
    """
    session = FakeSession([Event(ServerContent("A person is by the door. "))], raise_after=1)
    live = narrator(session)
    await live.start()
    await live.offer(b"jpeg", 0)
    for _ in range(6):
        await asyncio.sleep(0)

    assert live.available is False
    assert live.reason == UNREACHABLE

    # The sentence that arrived before the drop is still delivered. It was true
    # when it was made and the incident record should carry it.
    assert [n.text for n in drain(live)] == ["A person is by the door."]

    # And the sampler keeps calling, because it does not know anything happened.
    for index in range(1, 4):
        await live.offer(b"jpeg", index)
    assert drain(live) == []
    await live.aclose()


@pytest.mark.asyncio
async def test_a_session_that_will_not_open_reports_rather_than_raises():
    live = narrator(fail=True)
    await live.start()

    assert live.available is False
    assert live.reason == UNREACHABLE
    await live.offer(b"jpeg", 0)  # still no raise
    await live.aclose()


@pytest.mark.asyncio
async def test_a_dropped_session_can_be_restarted():
    """There is no hidden reconnect. Restarting is a decision, made in the open."""
    dead = FakeSession([], raise_after=0)
    live = narrator(dead)
    await live.start()
    for _ in range(4):
        await asyncio.sleep(0)
    assert live.available is False

    live._client = FakeClient(FakeSession([Event(ServerContent("Nobody is visible. "))]))
    await live.start()
    assert live.available is True

    await live.offer(b"jpeg", 9)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [n.text for n in drain(live)] == ["Nobody is visible."]
    await live.aclose()


def test_a_narrator_refuses_to_exist_without_a_key():
    """Failing at construction beats a session that opens and says nothing."""
    with pytest.raises(ValueError, match="no Gemini API key"):
        GeminiLiveNarrator("", room="living room")


@pytest.mark.asyncio
async def test_closing_twice_is_fine():
    live = narrator(FakeSession([]))
    await live.start()
    await live.aclose()
    await live.aclose()
    assert live.available is False
