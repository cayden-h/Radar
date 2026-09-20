"""RelayFrameSource: the tracker's camera is now the hub's relay.

The point of the FrameSource seam is that nothing downstream of it knows or
cares which implementation it got. These tests assert this one satisfies the
same contract the webcam and the fixture do, including the part that exists to
stop a video file presenting as a camera.
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


def test_it_does_not_claim_to_be_a_camera_before_the_hub_says_so():
    """The default classes as SIMULATED, so a provenance badge shows until
    proven wrong rather than after."""
    assert RelayFrameSource().source is Source.CAMERA_SIM


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


def test_no_frame_yet_is_not_an_error(monkeypatch):
    """503 means the edge has not connected, which is a normal startup state
    rather than a failure to raise on."""
    source = RelayFrameSource(base_url="http://hub.invalid", poll_interval_s=0, max_frames=2)
    monkeypatch.setattr(source, "_get_still", lambda: FakeResponse(b"", {}, status=503))
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


def test_it_gives_up_rather_than_waiting_forever_on_a_stopped_camera(monkeypatch):
    """A consumer blocked forever on a camera that stopped is the same failure
    as a frozen frame on a screen. Silence and "the camera is gone" must not
    share a representation."""
    jpeg = encode(90)
    source = RelayFrameSource(
        base_url="http://hub.invalid", poll_interval_s=0, give_up_after_s=0.2
    )
    monkeypatch.setattr(
        source,
        "_get_still",
        lambda: FakeResponse(jpeg, {"x-hawkeye-live": "false", "x-hawkeye-frame-age": "99"}),
    )

    with pytest.raises(RelayUnavailable, match="not the same as an empty room"):
        list(source.frames())
