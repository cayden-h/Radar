"""agents/presence, tested against the claims it must not make.

Every test here corresponds to a line in `docs/research/agent-briefs.md` under
"must not claim", and to a line published on the agent's own card. Those are the
lines that lose the judging conversation, so they are the ones with tests.

**Rewritten 2026-09-20.** Most of this file used to test respiration:
personhood, breathing rate, heart rate, and the responsiveness clock. That
reader was deleted when the camera took personhood, so what is left tests the
two facts the radio can still support without a caveat paragraph - something
moved, and which room - plus the claims this agent must now refuse to make.
"""

from __future__ import annotations

from agents.core.dev import SyntheticCsiFeed
from agents.presence import PresenceAgent

from .conftest import ZONES


def values(observation, field):
    return [a.value for a in observation.assertions if a.field == field]


def zones(observation, field, value=None):
    return {
        a.zone_scope
        for a in observation.assertions
        if a.field == field and (value is None or a.value == value)
    }


def unknown_fields(observation):
    return {u.field for u in observation.unknowns}


def warm(agent, feed, seconds):
    """Run the agent for `seconds` of simulated time, one tick per second."""
    observation = None
    for _ in range(seconds):
        feed.advance(1)
        observation = agent.run_once()
    return observation


# ------------------------------------------------------------------- motion


def test_movement_in_a_learned_room_is_reported_as_motion(feed, roster):
    """The one thing this agent still does. The baseline is warmed on a quiet
    room first, because a disturbance that has been there the whole time *is*
    the baseline - that is what a rolling percentile does, and it is correct."""
    agent = PresenceAgent(feed, roster)
    warm(agent, feed, 130)
    feed.perturb("laundry")
    observation = warm(agent, feed, 5)

    assert "laundry" in zones(observation, "presence.motion")
    assert "laundry" in zones(observation, "presence.zone")


def test_motion_never_claims_a_person(feed, roster):
    """The line the whole 2026-09-20 change rests on.

    A curtain and a burglar look identical on a 1x1 link. This agent says
    something moved; whether it is a person is the camera's question, and the
    basis has to say so where a dispatcher would read it.
    """
    agent = PresenceAgent(feed, roster)
    warm(agent, feed, 130)
    feed.perturb("laundry")
    observation = warm(agent, feed, 5)

    basis = next(a.basis for a in observation.assertions if a.field == "presence.motion")
    assert "curtain" in basis.lower()
    assert "camera" in basis.lower()


def test_motion_can_never_dispatch(feed, roster):
    """CORROBORATING is the ceiling and it is not negotiable. What motion may
    trigger is a shutter opening, which is a privacy decision master makes."""
    from hawkeye_backend.verification.envelope import Severity

    agent = PresenceAgent(feed, roster)
    warm(agent, feed, 130)
    feed.perturb("laundry")
    observation = warm(agent, feed, 5)

    for assertion in observation.assertions:
        assert assertion.severity_ceiling is not Severity.DISPATCHABLE


def test_no_zone_is_answered_before_the_baseline_is_old_enough(feed, roster):
    """A stale or unformed baseline produces confident nonsense. Say so instead."""
    feed.occupy("main_bedroom", bpm=15.0)
    observation = warm(PresenceAgent(feed, roster), feed, 40)

    assert not observation.healthy
    assert "presence.zone" in unknown_fields(observation)


def test_a_slow_feed_refuses_to_answer(roster):
    """Below the rate floor, motion and noise are not separable. A confident
    answer from data that cannot support it is the failure mode here, and every
    component downstream reports healthy while it happens."""
    slow = SyntheticCsiFeed(zones=ZONES, rate_hz=1.0)
    slow.advance(60)

    observation = PresenceAgent(slow, roster).run_once()

    assert not observation.healthy
    assert "presence.motion" in unknown_fields(observation)


# ------------------------------------------- what it must no longer claim


def test_presence_makes_no_respiration_claim_of_any_kind(feed, roster):
    """Respiration sensing was cut on 2026-09-19 and deleted on 2026-09-20.

    A field surviving the deletion would be a capability claimed in the data
    and absent from the code, which is drift in the most expensive direction.
    """
    agent = PresenceAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    observation = warm(agent, feed, 130)

    emitted = {a.field for a in observation.assertions} | unknown_fields(observation)
    for banned in (
        "presence.personhood",
        "presence.respiration",
        "presence.respiration_lost",
        "presence.breathing_bpm",
        "presence.heart_bpm",
        "presence.presence_class",
        "presence.headcount",
    ):
        assert banned not in emitted, f"{banned} survived the deletion"


def test_the_respiration_module_is_gone(feed, roster):
    """Deleted, not merely unused. An unused reader is one import away from
    being load-bearing again."""
    import importlib

    for module in ("agents.presence.respiration", "agents.people"):
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{module} still imports")
