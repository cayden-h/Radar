"""agents/tests/test_hub_wiring.py

`master` serves two HTTP surfaces on one app, and `agents/__main__.py` is the
only place they are assembled together:

- `hub_api.hub_router` - the read/incident/grant/stream surface `app/backend`'s
  `LiveMasterClient` polls (`/v1/state`, `/v1/sensor`, `/v1/agents`,
  `/v1/stream`, `/v1/shutter/grant`), mounted through `build_app`'s
  `routers`/`on_start`/`on_stop` hooks.
- `transport.attach_call_bridge_routes` - the `/a2a/{start-call,set-mode}` call
  bridge, the only path to a phone call.

These once regressed silently: a merge kept the call bridge and dropped the hub
router, so `HAWKEYE_MODE=live` had a master to talk to for dialing but nothing
serving state, and every surface fell back to the scripted incident. Nothing
caught it because nothing tested the assembly. This is that test.

It also guards the deliberate choice *not* to mount `hub_api.a2a_hub_router`:
it defines the same two `/a2a` paths as the call bridge but gates without
dialing, so mounting both would shadow the dialing routes with a start-call
that never reaches `agents/caller`.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from agents.__main__ import build_agent, build_master_app
from agents.core.identity import identity
from agents.core.keys import load_or_create
from agents.core.signing import ClaimSigner
from agents.master.transport import attach_call_bridge_routes


def _master_app():
    """The master app exactly as `agents/__main__.py` assembles it.

    `HAWKEYE_PEERS` is cleared so `build_agent` takes the in-process `LocalMesh`
    path and the test needs no network. The call bridge is attached with
    `caller_client=None`, matching an undeployed caller: the routes exist and
    fail closed rather than being absent.
    """
    os.environ.pop("HAWKEYE_PEERS", None)
    agent = build_agent("master")
    key = load_or_create("master")
    app = build_master_app(agent, ClaimSigner(identity("master"), key), key)
    attach_call_bridge_routes(app, agent, caller_client=None)
    return app


def test_both_surfaces_are_mounted() -> None:
    app = _master_app()
    paths = {getattr(route, "path", None) for route in app.routes}
    for path in (
        "/v1/state",
        "/v1/sensor",
        "/v1/agents",
        "/v1/incident",
        "/v1/shutter/grant",
        "/v1/stream",
        "/a2a/start-call",
        "/a2a/set-mode",
    ):
        assert path in paths, f"{path} is not served by the master app"


def test_call_bridge_routes_are_not_duplicated() -> None:
    """Exactly one handler per `/a2a` call-bridge path.

    Two would mean `hub_api.a2a_hub_router` was also mounted, and the one that
    never dials could win the match - a start-call that gates and returns
    success while `agents/caller` is never reached.
    """
    app = _master_app()
    for path in ("/a2a/start-call", "/a2a/set-mode"):
        matching = [r for r in app.routes if getattr(r, "path", None) == path]
        assert len(matching) == 1, f"{path} mounted {len(matching)} times, expected 1"


def test_security_mode_starts_disarmed_and_can_be_armed_over_the_hub() -> None:
    """The replay console's toggle talks to this pair of routes: read the
    current arm state, then flip it, with no restart in between."""
    with TestClient(_master_app()) as client:
        before = client.get("/v1/security-mode")
        assert before.status_code == 200
        assert before.json() == {"enabled": False}

        armed = client.post("/v1/security-mode", json={"enabled": True})
        assert armed.status_code == 200
        assert armed.json() == {"enabled": True}

        after = client.get("/v1/security-mode")
        assert after.json() == {"enabled": True}


def test_state_is_served_with_the_publisher_running() -> None:
    """GET /v1/state returns the composed InteriorState under the app lifespan.

    Using the app as a context manager runs startup/shutdown, which is where the
    hub's background publisher (`on_start=hub.start`) is started and stopped. A
    200 here proves the router is mounted *and* the publisher lifecycle wired
    through `build_app` did not raise on the way up or down.
    """
    with TestClient(_master_app()) as client:
        response = client.get("/v1/state")
        assert response.status_code == 200
        body = response.json()
        # site scope comes from hawkeye_backend settings, the same source the
        # simulated client reads, so a surface renders one installation.
        assert body["site_id"]
        assert "presences" in body and "floorplan" in body
