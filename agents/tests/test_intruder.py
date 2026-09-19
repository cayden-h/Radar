"""agents/intruder: roster arithmetic over a verified personhood verdict."""

from __future__ import annotations

from agents.intruder import IntruderAgent
from agents.people import PeopleAgent

from .test_people import unknown_fields, values


def _observe(feed, roster, mesh, seconds=35):
    feed.advance(seconds)
    mesh.publish(PeopleAgent(feed, roster).run_once())
    return IntruderAgent(roster, mesh).run_once()


def test_an_empty_house_with_a_body_names_the_zone(feed, roster, mesh):
    """The clean case: no resident device associated, one breathing presence."""
    roster.leave("dev-a")
    roster.leave("dev-b")
    feed.occupy("living_room", bpm=16.0)
    observation = _observe(feed, roster, mesh)

    assert values(observation, "intruder.unexpected_presence") == ["true"]
    assert values(observation, "intruder.intruder_zone") == ["living_room"]


def test_with_residents_home_the_intruder_zone_is_refused(feed, roster, mesh):
    """Three bodies, two residents home. We know there is a stranger.

    We do not know which one, because there is no re-identification, and
    guessing would send officers to the wrong room. Reporting every occupied
    zone is the honest answer and still an extremely useful one.
    """
    for zone, bpm in (("main_bedroom", 15.0), ("second_bedroom", 17.0), ("kitchen", 13.0)):
        feed.occupy(zone, bpm=bpm)
    observation = _observe(feed, roster, mesh)

    assert values(observation, "intruder.unexpected_presence") == ["true"]
    assert not values(observation, "intruder.intruder_zone")
    assert "intruder.intruder_zone" in unknown_fields(observation)
    assert values(observation, "intruder.occupied_zones")


def test_no_personhood_verdict_means_no_intruder_decision(roster, mesh):
    """No observation from agents/people at all. Refuse rather than guess."""
    observation = IntruderAgent(roster, mesh).run_once()

    assert not observation.healthy
    assert "intruder.unexpected_presence" in unknown_fields(observation)


def test_a_curtain_never_becomes_an_intruder(feed, roster, mesh):
    """Roster arithmetic runs over bodies, and a curtain is not one."""
    roster.leave("dev-a")
    roster.leave("dev-b")
    feed.perturb("laundry")
    observation = _observe(feed, roster, mesh)

    assert values(observation, "intruder.unexpected_presence") == ["false"]


def test_the_track_survives_a_missed_breath(feed, roster, mesh):
    """A track that flickers off and back on tells an officer the intruder left.

    Once declared, the track is held through clear ticks rather than dropped on
    the first one.
    """
    roster.leave("dev-a")
    roster.leave("dev-b")
    feed.occupy("living_room", bpm=16.0)
    feed.advance(35)

    people = PeopleAgent(feed, roster)
    intruder = IntruderAgent(roster, mesh)
    mesh.publish(people.run_once())
    intruder.run_once()

    feed.vacate("living_room")
    feed.advance(35)
    mesh.publish(people.run_once())
    observation = intruder.run_once()

    assert values(observation, "intruder.unexpected_presence") == ["true"]
