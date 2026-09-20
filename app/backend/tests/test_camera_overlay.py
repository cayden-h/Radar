"""The detector's boxes, from `agents/vision` to a screen.

The overlay's whole job is to let a human check the detector rather than take it
on trust, so the tests that matter are the ones about *not* drawing: a box that
outlives the detector that measured it is worse than no box at all, because it
is a confident statement about a room nobody is looking at.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.edge.annotate import draw_tracks
from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.models.camera import TrackBox
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source, utc_now


@pytest.fixture
def client():
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _jpeg(width: int = 320, height: int = 240) -> bytes:
    """A mid-grey frame, so a drawn box is unambiguously a difference."""
    image = np.full((height, width, 3), 128, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _box(track_id: int = 1) -> TrackBox:
    return TrackBox(track_id=track_id, x1=0.2, y1=0.2, x2=0.6, y2=0.8, confidence=0.9)


# ------------------------------------------------------------------ the model


def test_a_box_with_inverted_corners_is_refused() -> None:
    """Garbage geometry is rejected at the boundary, not drawn.

    cv2.rectangle happily accepts a box whose corners are the wrong way round
    and draws something; letting that through would put a rectangle on a screen
    that corresponds to nothing the detector said.
    """
    with pytest.raises(ValueError, match="ordered top-left to bottom-right"):
        TrackBox(track_id=1, x1=0.6, y1=0.2, x2=0.2, y2=0.8)


def test_a_box_outside_the_frame_is_refused() -> None:
    with pytest.raises(ValueError):
        TrackBox(track_id=1, x1=0.2, y1=0.2, x2=1.4, y2=0.8)


# --------------------------------------------------------------- the drawing


def test_drawing_a_box_changes_the_frame() -> None:
    clean = _jpeg()
    drawn = draw_tracks(clean, [_box()])
    assert drawn != clean


def test_drawing_no_boxes_returns_the_frame_untouched() -> None:
    """Byte-identical, not merely similar.

    An empty track list must not cost a decode and re-encode: it is the common
    case in an empty room, and a re-encode would degrade every frame slightly
    for no reason.
    """
    clean = _jpeg()
    assert draw_tracks(clean, []) is clean


def test_undecodable_bytes_come_back_unchanged_rather_than_raising() -> None:
    """The overlay sits in front of every surface and must never be the thing
    that takes the camera down."""
    junk = b"not a jpeg at all"
    assert draw_tracks(junk, [_box()]) == junk


# ------------------------------------------------------------- the staleness


def test_tracks_are_served_while_fresh() -> None:
    camera = LiveCamera()
    camera.set_tracks([_box()])
    assert len(camera.tracks) == 1


def test_tracks_age_out_rather_than_hovering_over_an_unwatched_room() -> None:
    """The failure this overlay could plausibly introduce, and the guard for it.

    `agents/vision` publishing on every pass means silence is evidence that the
    detector stopped. A box left on screen through that silence is a claim that
    somebody is standing in a particular place, made by nothing.
    """
    camera = LiveCamera(track_stale_after_s=0.0)
    camera.set_tracks([_box()])
    assert camera.tracks == ()


def test_a_camera_that_has_never_been_told_anything_draws_nothing() -> None:
    assert LiveCamera().tracks == ()


def test_an_empty_publish_clears_the_boxes_immediately() -> None:
    """The detector saying "nobody" must take the last box off at once, rather
    than waiting for the staleness window."""
    camera = LiveCamera()
    camera.set_tracks([_box()])
    camera.set_tracks([])
    assert camera.tracks == ()


# ------------------------------------------------------------- the endpoints


def test_posting_tracks_then_reading_the_still_draws_them(client) -> None:
    clean = _jpeg()
    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="test", source=Source.CAMERA_UVC)
    runtime.camera.accept(clean, index=0, captured_at=utc_now())

    posted = client.post(
        "/v1/camera/tracks",
        json={"tracks": [_box().model_dump(mode="json")]},
    )
    assert posted.status_code == 202
    assert posted.json() == {"tracks": 1}

    annotated = client.get("/v1/camera/still")
    assert annotated.status_code == 200
    assert annotated.headers["X-HawkEye-Tracks"] == "1"
    assert annotated.content != clean


def test_raw_asks_for_the_frame_the_detector_must_be_fed(client) -> None:
    """`agents/vision` polls with `raw=1`, and this is why.

    A detector handed a frame with its own previous boxes painted on it is
    measuring its own output. The clean frame must come back byte-identical to
    what the edge sent.
    """
    clean = _jpeg()
    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="test", source=Source.CAMERA_UVC)
    runtime.camera.accept(clean, index=0, captured_at=utc_now())
    client.post("/v1/camera/tracks", json={"tracks": [_box().model_dump(mode="json")]})

    raw = client.get("/v1/camera/still", params={"raw": "1"})
    assert raw.status_code == 200
    assert raw.content == clean
    assert raw.headers["X-HawkEye-Tracks"] == "0"
