"""Fixtures shared by both master clients: the floorplan, the agent roster, and
the identity helpers.

The floorplan is static building geometry and is the same in both modes. The
agent roster is the nine agents from agents/CLAUDE.md, in tier order.
"""

from __future__ import annotations

from hawkeye_backend.models.hub import AgentReachability, Reachability
from hawkeye_backend.models.state import Floorplan, Room
from hawkeye_backend.models.verification import TrustProfile

# The nine agents. name -> (tier, ans subdomain, trust profile the mesh expects).
#
# TODO(ans): these ANSNames are placeholders on an unregistered domain
# (`.invalid` is reserved by RFC 2606 precisely so it can never resolve, which
# keeps them from being mistaken for real registrations). Replace with the
# ANSNames actually registered through GoDaddy once ans/ has a domain, and
# confirm the naming convention: is an agent `collapse.hawkeye.example` or
# `hawkeye.example/agents/collapse`? agent.webmesh.ai's index at
# /.well-known/agents-index.json is the reference to check against.
AGENT_ROSTER: list[tuple[str, int, str, TrustProfile]] = [
    ("agents/occupancy", 1, "occupancy.hawkeye.invalid", TrustProfile.TRANSACTIONAL),
    ("agents/intruder", 1, "intruder.hawkeye.invalid", TrustProfile.TRANSACTIONAL),
    ("agents/biometrics", 1, "biometrics.hawkeye.invalid", TrustProfile.FIDUCIARY),
    ("agents/collapse", 1, "collapse.hawkeye.invalid", TrustProfile.FIDUCIARY),
    ("agents/master", 1, "master.hawkeye.invalid", TrustProfile.FIDUCIARY),
    ("agents/caller", 1, "caller.hawkeye.invalid", TrustProfile.FIDUCIARY),
    ("agents/guidance", 2, "guidance.hawkeye.invalid", TrustProfile.TRANSACTIONAL),
    ("agents/environment", 3, "environment.hawkeye.invalid", TrustProfile.READ_ONLY),
    ("agents/replay", 3, "replay.hawkeye.invalid", TrustProfile.TRANSACTIONAL),
]

ANSNAME: dict[str, str] = {name: ans for name, _, ans, _ in AGENT_ROSTER}
PROFILE: dict[str, TrustProfile] = {name: profile for name, _, _, profile in AGENT_ROSTER}


def build_floorplan(site_id: str) -> Floorplan:
    """A small single-storey house. Metres, origin at the south-west corner.

    Coordinates are floorplan geometry, not a localization claim. Presences get
    a zone centroid; see the note on `Position`.
    """
    return Floorplan(
        site_id=site_id,
        name="Ridgeview Lane",
        width_m=12.0,
        depth_m=9.0,
        rooms=[
            Room(
                zone="living_room",
                name="Living room",
                polygon=[(0.0, 0.0), (6.0, 0.0), (6.0, 5.0), (0.0, 5.0)],
            ),
            Room(
                zone="kitchen",
                name="Kitchen",
                polygon=[(6.0, 0.0), (12.0, 0.0), (12.0, 4.0), (6.0, 4.0)],
            ),
            Room(
                zone="hallway",
                name="Hallway",
                polygon=[(0.0, 5.0), (12.0, 5.0), (12.0, 6.5), (0.0, 6.5)],
            ),
            Room(
                zone="west_bedroom",
                name="West bedroom",
                polygon=[(0.0, 6.5), (5.0, 6.5), (5.0, 9.0), (0.0, 9.0)],
            ),
            Room(
                zone="east_bedroom",
                name="East bedroom",
                polygon=[(5.0, 6.5), (9.0, 6.5), (9.0, 9.0), (5.0, 9.0)],
            ),
            Room(
                zone="garage",
                name="Garage",
                polygon=[(9.0, 6.5), (12.0, 6.5), (12.0, 9.0), (9.0, 9.0)],
            ),
        ],
    )


ZONE_CENTROID: dict[str, tuple[float, float]] = {
    "living_room": (3.0, 2.5),
    "kitchen": (9.0, 2.0),
    "hallway": (6.0, 5.75),
    "west_bedroom": (2.5, 7.75),
    "east_bedroom": (7.0, 7.75),
    "garage": (10.5, 7.75),
}


def roster_reachability(status: Reachability, detail: str | None = None) -> list[AgentReachability]:
    """Report every agent in the roster with the same reachability.

    Used by the simulated client, which has no agents to reach and says so
    rather than claiming them healthy.
    """
    return [
        AgentReachability(
            name=name,
            ansname=ans,
            tier=tier,
            reachability=status,
            detail=detail,
        )
        for name, tier, ans, _ in AGENT_ROSTER
    ]
