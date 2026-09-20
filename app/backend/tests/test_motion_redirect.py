"""The hub's address for the RSSI motion detector.

The detector in `wifi-rssi-motion-template/` is a separate process on a
separate port, deliberately self-contained. All the hub does is hold a stable
address for it so the consoles do not have to hardcode that port.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from hawkeye_backend.config import Settings
from hawkeye_backend.main import create_app


def _client(**overrides) -> TestClient:
    settings = Settings(
        mode="simulated",
        edge_token="t",
        replay_site_enabled=False,
        live_site_enabled=False,
        **overrides,
    )
    return TestClient(create_app(settings))


def test_motion_redirects_to_the_configured_detector():
    with _client(motion_console_url="http://localhost:8766/index.html") as client:
        response = client.get("/motion", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "http://localhost:8766/index.html"


def test_the_detector_can_live_anywhere_the_configuration_says():
    """The detector runs on whichever machine is near the router, which is not
    always the one running the hub."""
    with _client(motion_console_url="http://192.168.1.44:8766/index.html") as client:
        response = client.get("/motion", follow_redirects=False)

    assert response.headers["location"] == "http://192.168.1.44:8766/index.html"


def test_an_empty_url_drops_the_route_rather_than_redirecting_nowhere():
    """A 404 says the detector is not configured. A redirect to "" would send
    the browser back to the hub root, which looks like the page working."""
    with _client(motion_console_url="") as client:
        response = client.get("/motion", follow_redirects=False)

    assert response.status_code == 404
