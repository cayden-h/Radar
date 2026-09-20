"""The camera's HTTP surface: one still, and a stream."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source, utc_now

JPEG = b"\xff\xd8\xff\xe0not-really-a-jpeg\xff\xd9"
BOUNDARY = b"--hawkeyeframe"


@pytest.fixture
def client():
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


def test_the_still_endpoint_labels_a_stale_frame_as_not_live(client, monkeypatch):
    """Stale is measured by arrival on this machine, not by the Pi's clock.
    See test_edge_camera.py for why that distinction is load-bearing."""
    import hawkeye_backend.edge.camera as camera_module

    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now())

    real = camera_module.time.monotonic()
    monkeypatch.setattr(camera_module.time, "monotonic", lambda: real + 60.0)

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


def test_the_live_stream_ends_when_frames_stop_arriving(client: TestClient):
    """A browser whose <img> stops receiving parts paints the last one forever,
    with no way for the page to know. Ending the response is what lets the page
    fall back to the unreachable state instead of showing a frozen room."""
    runtime = client.app.state.runtime
    runtime.camera.link_opened(edge_id="pi-01", source=Source.CAMERA_UVC)
    runtime.camera.accept(JPEG, index=0, captured_at=utc_now())

    with client.stream("GET", "/v1/camera/live") as response:
        chunks = list(response.iter_bytes())

    # It terminated rather than blocking forever, and it delivered the one frame
    # it had before giving up on the next.
    assert b"".join(chunks).count(BOUNDARY) == 1
