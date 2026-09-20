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
