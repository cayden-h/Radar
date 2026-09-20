"""Dismissing a notice from one surface clears it on all of them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.events import NoticeEvent
from hawkeye_backend.models.notice import Notice, NoticeSeverity


def a_notice(notice_id: str = "ntc-1") -> Notice:
    return Notice(
        notice_id=notice_id,
        severity=NoticeSeverity.ATTENTION,
        title="Unexpected person",
        body="Someone is in the living room.",
        provenance=Provenance(source=Source.AGENT_INFERENCE, producer="agents/vision"),
        narration="A person in a dark jacket is by the door.",
    )


@pytest.fixture
def client():
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_dismissing_republishes_the_notice_to_every_subscriber(client: TestClient):
    runtime = client.app.state.runtime

    with client.websocket_connect("/v1/stream") as ws:
        ws.receive_json()  # hello

        import asyncio

        asyncio.run(runtime.emit_notice(NoticeEvent(notice=a_notice())))
        response = client.post("/v1/notice/ntc-1/dismiss")
        assert response.status_code == 202

        dismissed = None
        for _ in range(10):
            envelope = ws.receive_json()
            if (
                envelope["payload"]["kind"] == "notice"
                and envelope["payload"]["notice"]["dismissed"]
            ):
                dismissed = envelope["payload"]["notice"]
                break

    assert dismissed is not None
    assert dismissed["notice_id"] == "ntc-1"
    # The whole notice comes back, not a bare id, so a surface that joined after
    # the dismissal renders a complete cleared notice rather than an empty one.
    assert dismissed["title"] == "Unexpected person"
    assert dismissed["narration"] == "A person in a dark jacket is by the door."


def test_dismissing_is_idempotent(client: TestClient):
    """A resident tapping twice under stress is not a condition worth surfacing."""
    assert client.post("/v1/notice/ntc-9/dismiss").status_code == 202
    assert client.post("/v1/notice/ntc-9/dismiss").status_code == 202


def test_dismissing_an_unknown_notice_does_not_404(client: TestClient):
    """The resident may be clearing something raised before a restart, and
    refusing would leave them with a banner they cannot get rid of."""
    response = client.post("/v1/notice/never-seen/dismiss")
    assert response.status_code == 202
    assert response.json()["dismissed"] is True


def test_dismissing_does_not_vouch_for_the_presence(client: TestClient):
    """Clearing a banner and vouching for a person are separate controls with
    separate words, because one control for both would persist strangers
    because somebody wanted a banner gone."""
    runtime = client.app.state.runtime
    client.post("/v1/notice/ntc-2/dismiss")
    assert runtime.approved_presences == set()
    assert client.get("/v1/household").json()["members"] == []
