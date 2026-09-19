"""agents/people, tested against the claims it must not make.

Every test here corresponds to a line in `docs/research/agent-briefs.md` under
"must not claim", and to a line published on the agent's own card. Those are the
lines that lose the judging conversation, so they are the ones with tests.
"""

from __future__ import annotations

from agents.core.dev import SyntheticCsiFeed
from agents.people import PeopleAgent

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


# --------------------------------------------------------------- personhood


def test_breathing_body_is_a_person(feed, roster):
    """The basic case. A chest wall moving at 15 a minute is a living body."""
    feed.occupy("main_bedroom", bpm=15.0)
    feed.advance(35)
    observation = PeopleAgent(feed, roster).run_once()

    assert "main_bedroom" in zones(observation, "people.personhood", "living_body")
    bpm = float(values(observation, "people.breathing_bpm")[0])
    assert 13.0 < bpm < 17.0, f"resolved {bpm} BPM against a 15 BPM source"


def test_a_curtain_is_not_a_person(feed, roster):
    """The failure mode the whole personhood verdict exists to prevent.

    A perturbation that moves the channel without breathing must produce an
    Unknown, never a personhood claim. Calling police on a curtain is the
    documented failure mode for `intruder`, and this is where it is stopped.
    """
    feed.perturb("laundry")
    feed.advance(35)
    observation = PeopleAgent(feed, roster).run_once()

    assert "laundry" not in zones(observation, "people.personhood")
    assert "people.personhood" in unknown_fields(observation)


def test_absence_of_signature_is_never_absence_of_a_person(feed, roster):
    """An empty-looking zone produces an Unknown with a stated reason.

    Not an assertion that the zone is empty. Shallow breathing, breath-holding
    and range limits all degrade to exactly this measurement.
    """
    feed.advance(35)
    observation = PeopleAgent(feed, roster).run_once()

    assert not values(observation, "people.personhood")
    reasons = [u.reason for u in observation.unknowns if u.field == "people.personhood"]
    assert reasons and "not evidence" in reasons[0]


def test_a_slow_feed_refuses_to_answer(roster):
    """Beacons alone are ~10 Hz. The agent says so rather than reporting healthy.

    This is the failure sensor/CLAUDE.md warns about twice: every component
    reports fine while the data cannot support any of it.
    """
    slow = SyntheticCsiFeed(ZONES, rate_hz=0.8)
    slow.occupy("main_bedroom", bpm=15.0)
    slow.advance(60)
    observation = PeopleAgent(slow, roster).run_once()

    assert not observation.healthy
    assert "Nyquist" in (observation.note or "")


def test_heart_rate_is_never_the_personhood_test(feed, roster):
    """Heart rate may be absent while personhood is resolved. Never the reverse."""
    feed.occupy("main_bedroom", bpm=15.0)
    feed.advance(35)
    observation = PeopleAgent(feed, roster).run_once()

    assert values(observation, "people.personhood") == ["living_body"]
    for assertion in observation.assertions:
        if assertion.field == "people.heart_bpm":
            assert assertion.severity_ceiling.value == "INFORMATIONAL"


# ------------------------------------------------------- responsiveness


def test_a_signature_that_was_never_there_is_not_a_lost_signature(feed, roster):
    """A zone that never resolved breathing must not claim breathing was lost.

    This is the whole reason the transition is the signal. An empty room and a
    room holding someone whose breathing we cannot resolve look identical on
    minute one; only the transition separates them.
    """
    agent = PeopleAgent(feed, roster)
    observation = warm(agent, feed, 40)

    assert values(observation, "people.respiration_lost") == []


def test_a_signature_that_disappears_is_reported_with_its_elapsed_time(feed, roster):
    """Breathing was resolvable here, and now it is not. Say so, with the clock."""
    agent = PeopleAgent(feed, roster)
    # Still and breathing, not moving: a moving body's respiration is not
    # recoverable on a 1x1 link, so there would be no signature to lose.
    feed.occupy("main_bedroom", bpm=15.0)
    warm(agent, feed, 35)

    # Long enough that the 30s analysis window has fully flushed the breathing
    # frames, and then some: the claim is about elapsed time since the last
    # signature, so the test has to let real time pass after it goes.
    feed.vacate("main_bedroom")
    observation = warm(agent, feed, 70)

    gone = float(values(observation, "people.respiration_lost")[0])
    assert gone > 30.0, "the clock runs from the last signature, not from this tick"


def test_a_lost_signature_is_never_a_finding_that_breathing_stopped(feed, roster):
    """The most urgent uncertainty this system can produce, and it stays one."""
    agent = PeopleAgent(feed, roster)
    # Still and breathing, not moving: a moving body's respiration is not
    # recoverable on a 1x1 link, so there would be no signature to lose.
    feed.occupy("main_bedroom", bpm=15.0)
    warm(agent, feed, 35)

    feed.vacate("main_bedroom")
    observation = warm(agent, feed, 40)

    reasons = [u.reason for u in observation.unknowns if u.field == "people.respiration"]
    assert any("NOT a finding" in r for r in reasons)

    bases = [a.basis for a in observation.assertions if a.field == "people.respiration_lost"]
    assert not any("collapse" in b.lower() for b in bases), (
        "the collapse reader is gone; this claim must stand on its own"
    )


# ------------------------------------------------------- location and count


def test_headcount_comes_from_the_roster_not_the_radio(feed, roster):
    """Two phones on the network is a count. One resolved zone is not."""
    feed.occupy("main_bedroom", bpm=15.0)
    observation = warm(PeopleAgent(feed, roster), feed, 130)

    assert values(observation, "people.headcount") == ["2"]
    assert values(observation, "people.sensed_presences")[0].startswith("at least")


def test_headcount_survives_the_radio_being_useless(feed, roster):
    """The roster answer is produced whether or not any zone resolves.

    If CSI is dead and two phones are associated, "two residents are home" is
    still true and still the most useful thing a dispatcher can be told.
    """
    observation = warm(PeopleAgent(feed, roster), feed, 130)
    assert values(observation, "people.headcount") == ["2"]


def test_sensed_count_can_never_dispatch(feed, roster):
    """A 1x1 link cannot deliver a count that should move anybody."""
    feed.occupy("main_bedroom", bpm=15.0)
    observation = warm(PeopleAgent(feed, roster), feed, 130)

    ceiling = next(
        a.severity_ceiling for a in observation.assertions if a.field == "people.sensed_presences"
    )
    assert ceiling.value == "CORROBORATING"


def test_no_zone_is_answered_before_the_baseline_is_old_enough(feed, roster):
    """A stale or unformed baseline produces confident nonsense. Say so instead."""
    feed.occupy("main_bedroom", bpm=15.0)
    observation = warm(PeopleAgent(feed, roster), feed, 40)

    assert not observation.healthy
    assert "people.zone" in unknown_fields(observation)


def test_a_perturbation_is_not_an_occupied_zone(feed, roster):
    """Amplitude alone never produces a zone claim.

    The baseline is warmed on a quiet room first, because a perturbation that
    has been there the whole time *is* the baseline - that is what a rolling
    percentile does, and it is the right behaviour. The interesting case is a
    curtain that starts moving after the room has been learned.
    """
    agent = PeopleAgent(feed, roster)
    warm(agent, feed, 130)
    feed.perturb("laundry")
    observation = warm(agent, feed, 5)

    assert "laundry" not in zones(observation, "people.zone")
    assert "laundry" in zones(observation, "people.perturbation")


def test_class_comes_from_respiration_rate(feed, roster):
    """Adult versus small-and-fast-breathing, and never from amplitude."""
    feed.occupy("second_bedroom", bpm=26.0)
    observation = warm(PeopleAgent(feed, roster), feed, 130)

    assert values(observation, "people.presence_class") == ["child"]
    basis = next(a.basis for a in observation.assertions if a.field == "people.presence_class")
    assert "overlap" in basis or "dog or cat" in basis


# -------------------------------------------------------------------- falls


def test_a_fall_followed_by_stillness_is_a_collapse(feed, roster):
    """The headline case, and the clock runs from the transient."""
    agent = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0, moving=True)
    warm(agent, feed, 35)

    feed.transient("main_bedroom")
    feed.advance(1)
    feed.settle("main_bedroom", bpm=8.0)
    observation = warm(agent, feed, 40)

    assert values(observation, "people.collapse_detected") == ["true"]
    down = float(values(observation, "people.still_down_s")[0])
    assert down > 30.0, "still_down_s is measured from the fall, not from the detection"


def test_sitting_down_hard_is_not_a_collapse(feed, roster):
    """A transient followed by movement is somebody sitting down. Silence."""
    agent = PeopleAgent(feed, roster)
    feed.occupy("living_room", bpm=15.0, moving=True)
    warm(agent, feed, 35)

    feed.transient("living_room")
    feed.advance(1)
    feed.occupy("living_room", bpm=15.0, moving=True)
    observation = warm(agent, feed, 40)

    assert values(observation, "people.collapse_detected") == ["false"]


def test_nothing_is_said_during_the_debounce(feed, roster):
    """The whole point of the debounce is that nothing leaves the agent."""
    agent = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0, moving=True)
    warm(agent, feed, 35)

    feed.transient("main_bedroom")
    feed.advance(1)
    feed.settle("main_bedroom", bpm=8.0)
    observation = warm(agent, feed, 8)

    assert values(observation, "people.collapse_detected") == ["false"]


def test_a_collapse_with_no_resolvable_breathing_escalates_uncertainty(feed, roster):
    """The most urgent uncertainty this system can produce, and it stays one.

    A confirmed collapse where respiration is not resolvable must NOT become a
    finding that the person is not breathing. Shallow breathing and range limits
    look identical to this.
    """
    agent = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0, moving=True)
    warm(agent, feed, 35)

    feed.transient("main_bedroom")
    feed.advance(1)
    feed.vacate("main_bedroom")
    observation = warm(agent, feed, 40)

    assert values(observation, "people.collapse_detected") == ["true"]
    reasons = [u.reason for u in observation.unknowns if u.field == "people.respiration"]
    assert any("NOT a finding" in r for r in reasons)
