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
    """A two-bedroom, two-bathroom apartment. Metres, origin at the top-left.

    Coordinates are floorplan geometry, not a localization claim. Presences get
    a zone centroid; see the note on `Position`.

    `patio` is the one zone that is outside sensor coverage. It is outdoors, and
    CSI does not reach it. The burglary script depends on that being true: the
    intruder is not seen approaching, only once they cross into coverage.
    """
    return Floorplan(
        site_id=site_id,
        name="Ridgeview Apartment",
        width_m=14.0,
        depth_m=9.0,
        rooms=[
            Room(
                zone="main_closet",
                name="Closet",
                polygon=[(0.0, 0.0), (2.4, 0.0), (2.4, 2.0), (0.0, 2.0)],
            ),
            Room(
                zone="main_bath",
                name="Main bath",
                polygon=[(2.4, 0.0), (4.8, 0.0), (4.8, 2.0), (2.4, 2.0)],
            ),
            Room(
                zone="second_bath",
                name="Second bath",
                polygon=[(4.8, 0.0), (7.2, 0.0), (7.2, 2.0), (4.8, 2.0)],
            ),
            Room(
                zone="linen_closet",
                name="Linen closet",
                polygon=[(7.2, 0.0), (8.8, 0.0), (8.8, 2.0), (7.2, 2.0)],
            ),
            Room(
                zone="dining_room",
                name="Dining room",
                polygon=[(8.8, 0.0), (14.0, 0.0), (14.0, 3.4), (8.8, 3.4)],
            ),
            Room(
                zone="hallway",
                name="Hallway",
                polygon=[(0.0, 2.0), (8.8, 2.0), (8.8, 3.2), (0.0, 3.2)],
            ),
            Room(
                zone="main_bedroom",
                name="Main bedroom",
                polygon=[(0.0, 3.2), (4.6, 3.2), (4.6, 9.0), (0.0, 9.0)],
            ),
            Room(
                zone="second_bedroom",
                name="Second bedroom",
                polygon=[(4.6, 3.2), (8.8, 3.2), (8.8, 6.8), (4.6, 6.8)],
            ),
            Room(
                zone="laundry",
                name="Laundry",
                polygon=[(4.6, 6.8), (8.8, 6.8), (8.8, 9.0), (4.6, 9.0)],
            ),
            Room(
                zone="kitchen",
                name="Kitchen",
                polygon=[(8.8, 3.4), (11.4, 3.4), (11.4, 7.4), (8.8, 7.4)],
            ),
            Room(
                zone="living_room",
                name="Living room",
                polygon=[(11.4, 3.4), (14.0, 3.4), (14.0, 7.4), (11.4, 7.4)],
            ),
            Room(
                zone="patio",
                name="Patio",
                polygon=[(8.8, 7.4), (14.0, 7.4), (14.0, 9.0), (8.8, 9.0)],
            ),
        ],
    )


#: Zones the CSI capture does not reach. The patio is outdoors, so nothing in
#: this system can see it, and every agent that is asked about it answers that
#: it does not know rather than guessing.
UNCOVERED_ZONES: frozenset[str] = frozenset({"patio"})


ZONE_CENTROID: dict[str, tuple[float, float]] = {
    "main_closet": (1.2, 1.0),
    "main_bath": (3.6, 1.0),
    "second_bath": (6.0, 1.0),
    "linen_closet": (8.0, 1.0),
    "dining_room": (11.4, 1.7),
    "hallway": (4.4, 2.6),
    "main_bedroom": (2.3, 6.1),
    "second_bedroom": (6.7, 5.0),
    "laundry": (6.7, 7.9),
    "kitchen": (10.1, 5.4),
    "living_room": (12.7, 5.4),
    "patio": (11.4, 8.2),
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
