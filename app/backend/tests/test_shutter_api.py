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
from hawkeye_backend.edge.wire import EdgeAttestation, EdgeChallenge, EdgeHello
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


def _answer_challenge(edge, nonce: str = "chal-from-the-shutter") -> str:
    """Play the shutter's first half: it issues the nonce the grant binds to."""
    ask = edge.receive_json()
    assert ask["kind"] == "challenge_request"
    edge.send_text(
        EdgeChallenge(request_id=ask["request_id"], nonce=nonce).model_dump_json()
    )
    return nonce


def test_a_grant_reaches_the_edge_and_its_attestation_reaches_the_stream(client: TestClient):
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        with client.websocket_connect("/v1/stream") as stream:
            stream.receive_json()  # hello

            result: dict = {}
            caller = _call_shutter_in_a_thread(client, result)

            nonce = _answer_challenge(edge)

            grant = edge.receive_json()
            assert grant["kind"] == "grant"
            # The grant crosses as an opaque string, never a nested object: the
            # bytes that were signed must be the bytes that are verified.
            assert isinstance(grant["grant_json"], str)
            signed = json.loads(grant["grant_json"])
            assert "signature" in signed
            # Bound to the nonce the shutter issued, never one this process made
            # up. That binding is what makes a replayed grant detectable.
            assert signed["envelope"]["nonce"] == nonce

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

            _answer_challenge(edge)
            grant = edge.receive_json()
            edge.send_text(
                EdgeAttestation(
                    request_id=grant["request_id"],
                    refused=True,
                    refusal_reason="unknown_issuer",
                    position="closed",
                    commanded_angle=0,
                ).model_dump_json()
            )
            caller.join(timeout=10)

            while (envelope := stream.receive_json())["payload"]["kind"] != "shield":
                pass

    assert result["response"].status_code == 202
    assert envelope["payload"]["refused"] is True
    assert envelope["payload"]["refusal_reason"] == "unknown_issuer"
    # The shutter reported where the shield still is, so that is carried rather
    # than replaced with `unknown`. It did not move, and saying so is a true
    # fact worth more than a shrug.
    assert envelope["payload"]["position"] == "closed"


def test_a_shutter_that_never_answers_a_challenge_reads_as_unknown(client: TestClient):
    """Timeout is the one case where guessing is genuinely dangerous. An unknown
    shield position is a true statement; `open` would be a false one, and the
    difference is whether a camera is covered."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())
        response = client.post("/v1/shutter", json={"action": "open", "reason": "test"})

    assert response.status_code == 504
    assert "did not answer" in response.json()["detail"].lower()


def test_a_shutter_that_will_not_issue_a_nonce_is_a_refusal(client: TestClient):
    """No nonce means no grant can be bound, so none is signed. Refusing to sign
    an unbindable grant is better than signing one and hoping."""
    with client.websocket_connect(f"/v1/edge/link?token={TOKEN}") as edge:
        edge.send_text(EdgeHello(edge_id="pi-01", source=Source.CAMERA_UVC).model_dump_json())

        result: dict = {}
        caller = _call_shutter_in_a_thread(client, result)

        ask = edge.receive_json()
        edge.send_text(
            EdgeChallenge(
                request_id=ask["request_id"], failed=True, detail="servo unpowered"
            ).model_dump_json()
        )
        caller.join(timeout=10)

    assert result["response"].status_code == 202
    payload = result["response"].json()
    assert payload["refused"] is True
    assert "servo unpowered" in payload["refusal_reason"]
    assert payload["position"] == "unknown"


def test_the_grant_is_the_shape_shutter_verifies(client: TestClient):
    """Built through agents.shutter.grant, never by hand. A hand-built dict
    serializes datetimes differently from pydantic and produces a mismatch
    indistinguishable from an attack, which is battery probe #13."""
    import asyncio

    runtime = client.app.state.runtime
    raw = asyncio.run(
        runtime.client.issue_shutter_grant(action="open", reason="a", nonce="chal-1")
    )
    signed = json.loads(raw)
    assert sorted(signed) == ["algorithm", "envelope", "signature"]
    assert signed["envelope"]["nonce"] == "chal-1"
    assert signed["envelope"]["issuer"].startswith("ans://")
