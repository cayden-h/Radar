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
    assert envelope.payload.room == "Living room"


@pytest.mark.asyncio
async def test_the_thumbnail_task_publishes_nothing_when_there_is_no_frame():
    """Silence, not a placeholder. A watch showing a grey rectangle labelled as
    a camera frame is the failure this whole design exists to avoid."""
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


@pytest.mark.asyncio
async def test_a_stale_frame_is_published_labelled_as_not_live():
    """It is still published, because it is a true statement about the last
    thing seen. What stops it being drawn as the room now is the label."""
    from datetime import timedelta

    settings = Settings(
        mode="simulated",
        edge_token="t",
        camera_thumbnail_interval_s=0.05,
        replay_site_enabled=False,
    )
    runtime = build_runtime(settings)
    sub = await runtime.bus.subscribe()
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now() - timedelta(seconds=60))

    task = asyncio.create_task(runtime._publish_thumbnails())
    try:
        envelope = await asyncio.wait_for(sub.queue.get(), timeout=2.0)
    finally:
        task.cancel()

    assert envelope.payload.live is False
