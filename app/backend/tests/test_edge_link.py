"""The edge link endpoint.

Almost everything here is about what the link refuses. It is the one door this
process opens onto an untrusted LAN, and it is also the door a shutter grant
leaves by, so the refusals are the feature rather than the edge cases.
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
def client():
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
    assert response.headers["x-hawkeye-live"] == "true"


def test_a_binary_message_with_no_header_before_it_is_refused(client: TestClient):
    """The pairing between header and payload is what keeps a frame honest about
    when it was taken. An unpaired payload has no timestamp, and stamping it
    with arrival time would quietly substitute one for the other."""
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


def test_an_unconfigured_token_refuses_every_connection():
    """Empty token means closed, never open. A camera feed anyone on the WiFi
    can write to is worse than no camera feed."""
    settings = Settings(mode="simulated", edge_token="", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/v1/edge/link?token=anything"):
                pass
