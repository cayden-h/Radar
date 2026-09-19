"""The household HTTP surface: `GET/POST /v1/household`, unclaimed devices, and
presence approval.

No 409 test here. Getting a real observed device into a `TestClient` app
requires the simulated master to have emitted a frame, which is timing-dependent
and would make this suite flaky. The 409 path is covered at the roster level by
`test_a_device_cannot_be_claimed_twice` in `tests/test_household_roster.py`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


@pytest.fixture
def client():
    app = create_app(Settings(_env_file=None, mode="simulated"))
    with TestClient(app) as c:
        yield c


def test_empty_household_is_empty(client: TestClient) -> None:
    resp = client.get("/v1/household")
    assert resp.status_code == 200
    assert resp.json() == {"members": []}


def test_remembering_without_a_device_creates_a_guest(client: TestClient) -> None:
    resp = client.post("/v1/household/remember", json={"name": "Grandma"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Grandma"
    assert body["devices"] == []


def test_remembering_an_unseen_device_is_404(client: TestClient) -> None:
    resp = client.post(
        "/v1/household/remember", json={"name": "Grandma", "device_id": "obs-nope"}
    )
    assert resp.status_code == 404
    assert "obs-nope" in resp.json()["detail"]


def test_a_blank_name_is_rejected(client: TestClient) -> None:
    resp = client.post("/v1/household/remember", json={"name": "   "})
    assert resp.status_code == 422


def test_a_remembered_member_appears_in_the_household(client: TestClient) -> None:
    client.post("/v1/household/remember", json={"name": "Grandma"})
    resp = client.get("/v1/household")
    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()["members"]]
    assert names == ["Grandma"]


def test_deleting_a_member_empties_the_roster(client: TestClient) -> None:
    created = client.post("/v1/household/remember", json={"name": "Grandma"}).json()
    resp = client.delete(f"/v1/household/members/{created['member_id']}")
    assert resp.status_code == 204
    assert client.get("/v1/household").json() == {"members": []}


def test_deleting_an_absent_member_is_404(client: TestClient) -> None:
    resp = client.delete("/v1/household/members/mem-does-not-exist")
    assert resp.status_code == 404


def test_approving_a_presence_is_202_and_idempotent(client: TestClient) -> None:
    first = client.post("/v1/presences/p4/approve")
    assert first.status_code == 202
    second = client.post("/v1/presences/p4/approve")
    assert second.status_code == 202


def test_unclaimed_devices_returns_the_shape(client: TestClient) -> None:
    """Not asserted empty: the simulated master's association table (task 9)
    observes two resident devices in the background as soon as it ticks, and
    nothing on this roster claims them, so they are legitimately unclaimed.
    The contract under test is the response shape, not a timing-dependent count.
    """
    resp = client.get("/v1/household/unclaimed-devices")
    assert resp.status_code == 200
    body = resp.json()
    assert "devices" in body
    assert isinstance(body["devices"], list)
