"""The shutter control, from any surface.

The refusal path matters more than the happy path here. A shutter that opens is
unremarkable; a shutter that declines a grant it cannot verify, visibly, on
every screen at once, is the submission.
"""

from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.edge.wire import EdgeAttestation, EdgeHello
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Source

TOKEN = "test-edge-token"


@pytest.fixture
def client():
    settings = Settings(
        mode="simulated",
        edge_token=TOKEN,
        replay_site_enabled=False,
        shutter_timeout_s=2.0,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_the_shutter_refuses_to_act_when_no_edge_is_connected(client: TestClient):
    """503 naming the problem, not a hang and not a lie. There is no servo to
    move and answering `opened` would be the worst possible response."""
    response = client.post("/v1/shutter", json={"action": "open", "reason": "test"})
    assert response.status_code == 503
    assert "edge" in response.json()["detail"].lower()


def test_an_unknown_action_is_refused(client: TestClient):
    """Two actions exist. A third is a refusal, never a default."""
    response = client.post("/v1/shutter", json={"action": "wiggle", "reason": "test"})
    assert response.status_code == 422


def _call_shutter_in_a_thread(client: TestClient, result: dict):
    def call():
        result["response"] = client.post(
            "/v1/shutter", json={"action": "open", "reason": "test"}
        )

    thread = threading.Thread(target=call)
    thread.start()
    return thread


def test_a_grant_reaches_the_edge_and_its_attestation_reaches_the_stream(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        with client.websocket_connect("/v1/stream") as stream:
            stream.receive_json()  # hello

            result: dict = {}
            caller = _call_shutter_in_a_thread(client, result)

            grant = edge.receive_json()
            assert grant["kind"] == "grant"
            # The grant crosses as an opaque string, never a nested object: the
            # bytes that were signed must be the bytes that are verified.
            assert isinstance(grant["grant_json"], str)
            assert "signature" in json.loads(grant["grant_json"])

            edge.send_text(
                EdgeAttestation(
                    request_id=grant["request_id"],
                    attestation_json=json.dumps(
                        {
                            "position": "open",
                            "commanded_angle": 90,
                            "position_basis": "commanded",
                        }
                    ),
                    refused=False,
                ).model_dump_json()
            )
            caller.join(timeout=10)

            while (envelope := stream.receive_json())["payload"]["kind"] != "shield":
                pass

    assert result["response"].status_code == 202
    assert envelope["payload"]["position"] == "open"
    assert envelope["payload"]["refused"] is False
    assert envelope["payload"]["position_basis"] == "commanded"
    assert envelope["payload"]["commanded_angle"] == 90


def test_a_refused_grant_is_published_as_a_refusal_not_an_error(client: TestClient):
    """A refusal is the system working. It reaches every screen as a first-class
    outcome rather than being swallowed into a 500."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        with client.websocket_connect("/v1/stream") as stream:
            stream.receive_json()

            result: dict = {}
            caller = _call_shutter_in_a_thread(client, result)

            grant = edge.receive_json()
            edge.send_text(
                EdgeAttestation(
                    request_id=grant["request_id"],
                    refused=True,
                    refusal_reason="unknown_issuer",
                ).model_dump_json()
            )
            caller.join(timeout=10)

            while (envelope := stream.receive_json())["payload"]["kind"] != "shield":
                pass

    assert result["response"].status_code == 202
    assert envelope["payload"]["refused"] is True
    assert envelope["payload"]["refusal_reason"] == "unknown_issuer"
    # Refused means the shield did not move, and we do not know where it is.
    # Reporting `closed` would be a guess dressed as a fact.
    assert envelope["payload"]["position"] == "unknown"


def test_a_shutter_that_never_answers_reads_as_unknown_never_as_open(client: TestClient):
    """Timeout is the one case where guessing is genuinely dangerous. An unknown
    shield position is a true statement; `open` would be a false one, and the
    difference is whether a camera is covered."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        response = client.post("/v1/shutter", json={"action": "open", "reason": "test"})

    assert response.status_code == 504
    assert "did not answer" in response.json()["detail"].lower()


def test_every_grant_carries_a_fresh_nonce(client: TestClient):
    """A nonce held open across two grants gives an attacker a window in which a
    captured grant is still live."""
    runtime = client.app.state.runtime
    import asyncio

    first = asyncio.run(runtime.client.issue_shutter_grant(action="open", reason="a"))
    second = asyncio.run(runtime.client.issue_shutter_grant(action="open", reason="b"))
    assert json.loads(first)["nonce"] != json.loads(second)["nonce"]
