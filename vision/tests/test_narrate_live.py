"""The live path, against the real Gemini Live endpoint. Marked `integration`.

Deselected by default, because it needs a key and the network and costs money.
Run it deliberately:

    cd vision && python -m pytest tests/test_narrate_live.py -m integration -q

What it is for is the thing a fake session can never tell you: that the model,
the modality and the transcription path this project pinned still work. Every
live model the key can reach refuses `response_modalities=["TEXT"]`, so
narration arrives as the transcript of synthesised speech, and the day that
changes is a day the demo stops narrating for a reason nobody can see from a
unit test. See the `narrate` module docstring.
"""

from __future__ import annotations

import asyncio
import pathlib
import time

import numpy as np
import pytest

from hawkeye_vision.narrate import GeminiLiveNarrator, drain, encode_jpeg

ENV = pathlib.Path(__file__).resolve().parents[2] / "app" / "backend" / ".env"

#: What root `CLAUDE.md` budgets between the shutter attesting open and the
#: first narration landing on the watch. Asserted loosely: this is a network
#: call at a hackathon venue, and a test that fails on a slow uplink teaches
#: nothing. It is here to catch an order-of-magnitude regression.
FIRST_SENTENCE_BUDGET_S = 6.0


def api_key() -> str | None:
    if not ENV.exists():
        return None
    for line in ENV.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def a_lit_room() -> bytes:
    """A synthetic frame. Not a person - the point is the round trip, not the verdict."""
    import cv2

    image = np.full((480, 640, 3), 40, np.uint8)
    cv2.rectangle(image, (0, 380), (640, 480), (70, 60, 55), -1)
    cv2.rectangle(image, (480, 120), (610, 400), (90, 80, 70), -1)
    return encode_jpeg(image)


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_a_real_session_returns_a_sentence_inside_the_budget():
    key = api_key()
    if not key:
        pytest.skip("no GEMINI_API_KEY in app/backend/.env")

    live = GeminiLiveNarrator(key, room="living room")
    await live.start()
    assert live.available, f"session did not open: {live.reason}"

    started = time.monotonic()
    await live.offer(a_lit_room(), 0)

    narrations = []
    while time.monotonic() - started < FIRST_SENTENCE_BUDGET_S:
        narrations = drain(live)
        if narrations:
            break
        await asyncio.sleep(0.05)

    elapsed = time.monotonic() - started
    await live.aclose()

    assert narrations, f"no narration inside {FIRST_SENTENCE_BUDGET_S}s (reason: {live.reason})"
    assert narrations[0].text.strip()
    assert elapsed < FIRST_SENTENCE_BUDGET_S
