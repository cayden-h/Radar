"""agents/caller: what gets said, what does not, and who may open a microphone."""

from __future__ import annotations

import pytest
from hawkeye_backend.models.incident import IncidentType, RaisedBy

from agents.caller import (
    Bridge,
    CallerAgent,
    Leg,
    ModeChangeRefused,
    ParticipationMode,
    route_question,
)
from agents.caller.agent import _speak_value
from agents.master import MasterAgent, SimulatedCoSensor
from agents.people import PeopleAgent


# ------------------------------------------------------------------- speech


def test_an_unrecognised_question_is_i_dont_know(mesh):
    """Not the nearest match. A guess delivered to 911 in a confident voice."""
    caller = CallerAgent(mesh, MasterAgent(mesh))
    answer = caller.answer_operator("what colour is the front door?")

    assert answer.text.startswith("I don't know")


def test_questions_match_on_meaning_not_exact_strings():
    """A dispatcher will not say the phrase anyone hardcoded."""
    assert route_question("is she still breathing?") == "people.respiration"
    assert route_question("how long has she been down for?") == "people.respiration_lost"
    assert route_question("is anyone else in there?") == "people.headcount"
    assert route_question("which room is he in") == "people.zone"


def test_a_question_reaches_the_field_about_its_own_subject():
    """The routing table's real failure mode, pinned in a dispatcher's words.

    `QUESTION_ROUTES` returns the first entry whose keywords appear, so a broad
    keyword high in the table does not merely waste a route - it answers a
    question that was never asked. Every phrasing below once routed to
    `people.respiration_lost`, which meant an operator asking about carbon
    monoxide was told "I had a breathing signature in the main bedroom four
    minutes ago and I do not have one now", confidently, as the answer.

    Cross-field leakage is the thing to test here, not the happy path: each of
    these is a question whose subject is written on its face, and each one used
    to be swallowed by a route about something else.
    """
    assert route_question("how long has the carbon monoxide been elevated?") == "master.co_ppm"
    assert (
        route_question("what has the gas reading been since the alarm went off?")
        == "master.co_ppm"
    )
    assert (
        route_question("is the carbon monoxide still rising since you called?") == "master.co_ppm"
    )
    assert (
        route_question("how long has the intruder been inside?") == "intruder.unexpected_presence"
    )
    assert route_question("when did the intruder get in?") == "intruder.unexpected_presence"
    assert route_question("can you answer how many people are inside?") == "people.headcount"

    # Neither of these is about a person we are tracking, and neither has a
    # field behind it. Nothing measures how long a fire has burned, and the
    # door is not something this system senses at all. "I don't know" is the
    # honest answer and it is what the operator gets.
    assert route_question("how long since the fire started?") is None
    assert route_question("has anyone answered the door?") is None

    # And the responsiveness route still answers the questions it is for.
    assert route_question("is she responsive?") == "people.respiration_lost"
    assert route_question("will she answer you?") == "people.respiration_lost"
    assert route_question("how long since you had breathing?") == "people.respiration_lost"


def test_nothing_is_spoken_when_the_transport_verifies_nothing(mesh, feed, roster):
    """The refusal, said out loud on the call, rather than silence or a guess."""
    people = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(130):
        feed.advance(1)
        mesh.publish(people.run_once())

    master = MasterAgent(mesh, gas=SimulatedCoSensor())
    master.run_once()
    lines = CallerAgent(mesh, master).opening_report(IncidentType.FIRE, "1 Fictional Way")

    assert "I am not a person" in lines[0].text
    assert any("will not repeat anything I cannot verify" in line.text for line in lines)


def test_a_verified_claim_is_spoken_and_attributed(verified_mesh, feed, roster):
    people = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(130):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    master = MasterAgent(verified_mesh)
    master.run_once()
    lines = CallerAgent(verified_mesh, master).opening_report(
        IncidentType.FIRE, "1 Fictional Way"
    )

    spoken = [line for line in lines if line.claim_fields]
    assert spoken, "verified claims reach the operator"
    assert all(line.attributed_to.startswith("agents/") for line in spoken)


def test_a_negative_claim_is_never_read_to_a_dispatcher(mesh, verified_mesh, feed, roster):
    """A verified negative is still not something to read to a dispatcher.

    Found on 2026-09-19 on a boolean field that has since been removed with
    fall detection, and the two defects behind it both outlived the field. The
    speech mapping rendered a boolean by assuming its positive case, and the
    opening report spoke every verified claim rather than every claim worth
    saying. A dispatcher has seconds; a list of things that are not happening
    is how the one thing that is gets buried.

    "went down" is asserted against because no surviving field may bring that
    sentence back: with fall detection gone there is nothing this system can
    verify that supports it.
    """
    people = PeopleAgent(feed, roster)
    for _ in range(130):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    master = MasterAgent(verified_mesh)
    master.run_once()
    lines = CallerAgent(verified_mesh, master).opening_report(
        IncidentType.FIRE, "1 Fictional Way"
    )

    spoken = " ".join(line.text for line in lines)
    assert "went down" not in spoken, "a false collapse claim must not be read as a fall"
    assert "at least 0" not in spoken


def test_a_quiet_verified_house_says_so_rather_than_nothing(mesh, verified_mesh, feed, roster):
    """Verified, and nothing to report, is a real answer a dispatcher can use."""
    people = PeopleAgent(feed, roster)
    for _ in range(130):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    master = MasterAgent(verified_mesh)
    master.run_once()
    lines = CallerAgent(verified_mesh, master).opening_report(
        IncidentType.FIRE, "1 Fictional Way"
    )

    assert len(lines) >= 2
    assert not any("will not repeat anything I cannot verify" in line.text for line in lines)


def test_resident_context_is_attributed_to_the_resident(mesh):
    """Context, never a system observation. The resident typed it."""
    utterance = CallerAgent(mesh).speak_resident_context("the smoke is from the laundry")

    assert utterance.attributed_to == "resident"
    assert utterance.text.startswith("The resident reports:")


def test_ending_a_call_is_never_silent(mesh):
    """An abandoned 911 call causes a dispatch. PSAPs treat a drop as real."""
    caller = CallerAgent(mesh)
    cancelled = caller.end_call(cancelled_by_resident=True, resident_reachable=True)
    unreachable = caller.end_call(cancelled_by_resident=False, resident_reachable=False)

    assert "no emergency at this address" in cancelled.text
    assert "staying on the line" in unreachable.text


# ------------------------------------------------------------------- bridge


def test_whisper_is_send_on_receive_off():
    """The resident is heard and the phone stays silent."""
    bridge = Bridge()
    bridge.set_mode(ParticipationMode.WHISPER, by_human=True)
    state = bridge.leg_state(Leg.RESIDENT)

    assert state.send is True
    assert state.receive is False


def test_automation_may_never_open_a_microphone():
    """Automation may only ever move toward quieter. Going louder needs a hand."""
    bridge = Bridge()

    with pytest.raises(ModeChangeRefused, match="toward quieter"):
        bridge.set_mode(ParticipationMode.WHISPER, by_human=False)


def test_automation_may_always_go_quieter():
    bridge = Bridge()
    bridge.set_mode(ParticipationMode.FULL_VOICE, by_human=True)
    bridge.set_mode(ParticipationMode.WATCHING, by_human=False)

    assert bridge.resident_mode is ParticipationMode.WATCHING


def test_joining_by_whisper_is_announced_as_what_it_means():
    """Real information for a dispatcher: an active threat, a concealed caller."""
    bridge = Bridge()
    announcement = bridge.set_mode(ParticipationMode.WHISPER, by_human=True)

    assert "cannot hear you" in announcement
    assert "hiding" in announcement


def test_the_operator_may_request_but_never_grant():
    """Pressure from an authority figure is the vector, not the exception."""
    bridge = Bridge()
    bridge.request_resident()

    assert bridge.resident_mode is ParticipationMode.WATCHING
    assert bridge.operator_requested_resident is True


def test_the_agent_yields_the_instant_a_human_speaks():
    """Barge-in is load-bearing. It is what makes the 1.5s hold safe."""
    bridge = Bridge()
    bridge.yield_to_human()

    assert bridge.agent_speaking is False
    assert bridge.leg_state(Leg.CALLER).send is False
    # It keeps listening, which is what makes it a teleprompter afterwards.
    assert bridge.leg_state(Leg.CALLER).receive is True


# ---------------------------------------------------------------- guidance


def test_guidance_defers_to_the_dispatcher(mesh):
    """Dispatchers are trained in emergency medical dispatch protocols. We are not."""
    caller = CallerAgent(mesh)
    caller.operator_said("I've dispatched units, they're two minutes out")
    instructions = caller.resident_guidance(IncidentType.FIRE)

    assert caller.resident.deferring is True
    assert [i.text for i in instructions] == ["Follow what the dispatcher is telling you."]


def test_fire_guidance_is_to_leave_not_to_investigate(mesh):
    """One to two minutes to escape; a modern room unsurvivable in under three."""
    texts = [i.text for i in CallerAgent(mesh).resident_guidance(IncidentType.FIRE)]

    assert texts[0].startswith("Get out now")
    assert any("stay out" in t for t in texts)


def test_operator_cues_match_on_meaning(mesh):
    caller = CallerAgent(mesh)
    instructions = caller.operator_said("help is coming, unlock the door if you can")

    assert len(instructions) == 2
    assert all(i.defers_to_operator for i in instructions)


def test_a_lost_signature_is_spoken_with_its_limit_attached():
    """The one line that justifies keeping respiration, and it must not overclaim.

    A dispatcher hearing "she is not breathing" will act on it. The radio cannot
    support that sentence, so the caller says what it measured and what that
    does not mean, in that order.
    """
    spoken = _speak_value("people.respiration_lost", "240", zone="main_bedroom")

    assert "main bedroom" in spoken
    assert "4 minutes" in spoken
    assert "not the same as" in spoken
    assert "stopped breathing" in spoken


def test_asking_whether_to_expect_an_answer_routes_to_the_lost_signature():
    """The dispatcher's actual question, in the words a dispatcher uses."""
    for question in (
        "is she responsive?",
        "will she answer the door?",
        "how long since you had breathing?",
    ):
        assert route_question(question) == "people.respiration_lost", question


def test_fire_guidance_never_tells_a_resident_to_stay_and_help():
    """A modern room is unsurvivable in under three minutes. Leaving is the protocol.

    This is the line the Faint protocol used to blur, and deleting it is the
    point: there is no incident type where "stay and do CPR" is our guidance.
    """
    from agents.caller.guidance import PROTOCOL

    text = " ".join(i.text.lower() for i in PROTOCOL[IncidentType.FIRE])
    assert "get out now" in text
    assert "cpr" not in text
    assert "recovery position" not in text
