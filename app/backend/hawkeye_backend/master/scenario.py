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
    """The Chestnut: a two-bedroom, two-bathroom apartment, 14.8m x 6.8m.

    Long and shallow, roughly 2.2:1, which is what the real unit is. 100.6 m2,
    or 1083 sq ft against a published 1086.

    Coordinates are floorplan geometry, not a localization claim. Presences get
    a zone centroid; see the note on `Position`.

    Eleven zones, and they tile the rectangle completely. Every one of them is
    inside the unit and inside sensor coverage. What is outside coverage is
    everything past the front door: the building corridor, the stairwell, the
    street. Nothing in this system can see any of it, and no agent may answer a
    question about it.

    The street address is fictional and stays that way. A simulated 911 call
    must never carry a real residential address.
    """
    return Floorplan(
        site_id=site_id,
        name="Chestnut",
        width_m=14.8,
        depth_m=6.8,
        rooms=[
            Room(
                zone="main_closet",
                name="Closet",
                polygon=[(0.0, 0.0), (1.9, 0.0), (1.9, 1.9), (0.0, 1.9)],
            ),
            Room(
                zone="main_bath",
                name="Bath 1",
                polygon=[(1.9, 0.0), (3.7, 0.0), (3.7, 1.9), (1.9, 1.9)],
            ),
            Room(
                zone="second_bath",
                name="Bath 2",
                polygon=[(3.7, 0.0), (5.8, 0.0), (5.8, 1.9), (3.7, 1.9)],
            ),
            Room(
                zone="linen_closet",
                name="Linen",
                polygon=[(5.8, 0.0), (6.9, 0.0), (6.9, 1.9), (5.8, 1.9)],
            ),
            Room(
                zone="dining_room",
                name="Dining room",
                polygon=[(6.9, 0.0), (10.8, 0.0), (10.8, 3.1), (6.9, 3.1)],
            ),
            Room(
                zone="living_room",
                name="Living room",
                polygon=[(10.8, 0.0), (14.8, 0.0), (14.8, 6.8), (10.8, 6.8)],
            ),
            Room(
                zone="main_bedroom",
                name="Main bedroom",
                polygon=[(0.0, 1.9), (3.7, 1.9), (3.7, 6.8), (0.0, 6.8)],
            ),
            Room(
                zone="hallway",
                name="Hallway",
                polygon=[(3.7, 1.9), (6.9, 1.9), (6.9, 3.0), (3.7, 3.0)],
            ),
            Room(
                zone="second_bedroom",
                name="Second bedroom",
                polygon=[(3.7, 3.0), (6.9, 3.0), (6.9, 6.8), (3.7, 6.8)],
            ),
            Room(
                zone="kitchen",
                name="Kitchen",
                polygon=[(6.9, 3.1), (10.8, 3.1), (10.8, 5.4), (6.9, 5.4)],
            ),
            Room(
                zone="laundry",
                name="Laundry",
                polygon=[(6.9, 5.4), (10.8, 5.4), (10.8, 6.8), (6.9, 6.8)],
            ),
        ],
    )


ZONE_CENTROID: dict[str, tuple[float, float]] = {
    "main_closet": (0.95, 0.95),
    "main_bath": (2.80, 0.95),
    "second_bath": (4.75, 0.95),
    "linen_closet": (6.35, 0.95),
    "dining_room": (8.85, 1.55),
    "living_room": (12.80, 3.40),
    "main_bedroom": (1.85, 4.35),
    "hallway": (5.30, 2.45),
    "second_bedroom": (5.30, 4.90),
    "kitchen": (8.85, 4.25),
    "laundry": (8.85, 6.10),
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
