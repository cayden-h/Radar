"""The vouch ledger's lifecycle, and the endpoints a surface taps through.

The grace window is the part worth testing hardest. It is the difference
between a resident who steps behind a sofa staying vouched for and becoming an
intruder, and it is measured against a clock, so every test here injects one
rather than sleeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.edge.vouch import GRACE_S, VouchLedger
from hawkeye_backend.main import create_app
from hawkeye_backend.models.camera import TrackBox

T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def client():
    settings = Settings(mode="simulated", edge_token="t", replay_site_enabled=False)
    with TestClient(create_app(settings)) as c:
        yield c


# --------------------------------------------------------------- the ledger


def test_a_vouch_is_held_while_the_tracker_holds_the_id() -> None:
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    ledger.observe(frozenset({3}), now=at(30))

    (vouch,) = ledger.active(now=at(30))
    assert vouch.name == "Jordan"
    assert vouch.held is True


def test_losing_the_track_starts_the_grace_window_rather_than_clearing_it() -> None:
    """A person behind a sofa is still a person the resident vouched for."""
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    ledger.observe(frozenset(), now=at(5))

    (vouch,) = ledger.active(now=at(5))
    assert vouch.name == "Jordan"
    # Held goes false so a surface can draw the difference. A vouch inside its
    # grace window and a vouch on a person in frame are different statements.
    assert vouch.held is False


def test_the_same_id_coming_back_inside_the_window_restores_the_name() -> None:
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)
    ledger.observe(frozenset(), now=at(5))

    ledger.observe(frozenset({3}), now=at(20))

    (vouch,) = ledger.active(now=at(20))
    assert vouch.held is True
    assert vouch.name == "Jordan"


def test_a_vouch_lapses_once_the_window_passes() -> None:
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    ledger.observe(frozenset(), now=at(GRACE_S + 1))

    assert ledger.active(now=at(GRACE_S + 1)) == ()
    assert ledger.get(3) is None


def test_expiry_is_evaluated_on_read_as_well() -> None:
    """A dropped camera link stops `observe` running. Vouches must still lapse.

    Otherwise a hub whose edge disconnected would serve a vouch forever, which
    is the exact failure the grace window exists to bound.
    """
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    assert ledger.active(now=at(GRACE_S + 1)) == ()


def test_re_vouching_replaces_the_name_without_a_revoke_first() -> None:
    ledger = VouchLedger()
    ledger.vouch(3, "Jordn", now=T0)

    ledger.vouch(3, "Jordan", now=at(1))

    (vouch,) = ledger.active(now=at(1))
    assert vouch.name == "Jordan"


def test_revoking_returns_what_it_removed_and_is_safe_to_repeat() -> None:
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    removed = ledger.revoke(3)

    assert removed is not None and removed.name == "Jordan"
    assert ledger.revoke(3) is None
    assert ledger.active(now=T0) == ()


def test_names_are_stripped_so_a_keyboard_space_is_not_a_different_person() -> None:
    ledger = VouchLedger()
    assert ledger.vouch(3, "  Jordan ", now=T0).name == "Jordan"


def test_one_persons_vouch_does_not_cover_another_box() -> None:
    """The room is never vouched for. Only the box that was tapped is."""
    ledger = VouchLedger()
    ledger.vouch(3, "Jordan", now=T0)

    ledger.observe(frozenset({3, 7}), now=at(1))

    assert [v.track_id for v in ledger.active(now=at(1))] == [3]


# ------------------------------------------------------------- the endpoints


def test_tap_name_and_the_box_comes_back_vouched(client) -> None:
    box = TrackBox(track_id=3, x1=0.1, y1=0.1, x2=0.4, y2=0.9)
    client.post("/v1/camera/tracks", json={"tracks": [box.model_dump(mode="json")]})

    vouched = client.post("/v1/camera/vouch", json={"track_id": 3, "name": "Jordan"})
    assert vouched.status_code == 202

    snapshot = (client.get("/v1/camera/tracks")).json()
    assert [t["track_id"] for t in snapshot["tracks"]] == [3]
    assert [(v["track_id"], v["name"]) for v in snapshot["vouches"]] == [(3, "Jordan")]


def test_revoking_clears_it_from_the_snapshot(client) -> None:
    client.post("/v1/camera/vouch", json={"track_id": 3, "name": "Jordan"})

    assert (client.delete("/v1/camera/vouch/3")).status_code == 204

    assert (client.get("/v1/camera/tracks")).json()["vouches"] == []


def test_revoking_something_never_vouched_for_is_not_an_error(client) -> None:
    """The resident's intent is "not vouched for", which is already true."""
    assert (client.delete("/v1/camera/vouch/99")).status_code == 204


def test_an_empty_name_is_refused(client) -> None:
    """A blank vouch would put an unlabelled green box on the feed.

    That reads as "the system recognised somebody" to anyone glancing at it,
    which is the one thing this feature must never imply.
    """
    response = client.post("/v1/camera/vouch", json={"track_id": 3, "name": "  "})
    assert response.status_code in {400, 422}


def test_vouching_a_box_the_tracker_no_longer_holds_is_accepted(client) -> None:
    """The boxes move under the resident's thumb. A near miss is not an error."""
    response = client.post("/v1/camera/vouch", json={"track_id": 404, "name": "Jordan"})
    assert response.status_code == 202
