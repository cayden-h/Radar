"""The trust boundary: what master admits, what it discards, and what may be spoken.

These are the tests that matter most. The refusal path is the submission; a
dispatch demo that works is unremarkable, and a dispatch demo that correctly
refuses an impostor is the thing being judged.
"""

from __future__ import annotations

import pytest
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.incident import IncidentType, RaisedBy
from hawkeye_backend.models.verification import TrustProfile, VerificationDecision
from hawkeye_backend.verification.envelope import Severity

from agents.core.observations import AgentObservation, Assertion
from agents.master import AutonomousDialRefused, MasterAgent, SimulatedCoSensor, TrustGate
from agents.people import PeopleAgent


def _assertion(field, value, *, ceiling=Severity.ACTIONABLE, zone="main_bedroom"):
    return Assertion(
        field=field,
        value=value,
        zone_scope=zone,
        severity_ceiling=ceiling,
        confidence=0.9,
        basis="fixture",
        provenance=Provenance(source=Source.RUVIEW_SIM, producer="test"),
    )


def _observation(agent, ansname, assertions):
    return AgentObservation(agent=agent, ansname=ansname, assertions=tuple(assertions))


# ----------------------------------------------------------------- the gate


def test_an_unregistered_agent_is_refused():
    """Unknown is a refusal, never an unknown-therefore-allow. Battery #11."""
    gate = TrustGate()
    admitted = gate.admit(
        _observation(
            "agents/impostor",
            "ans://v0.1.0.people.hawkeye.evil",
            [_assertion("people.personhood", "living_body")],
        )
    )

    assert admitted == []
    assert len(gate.discarded) == 1
    assert gate.discarded[0].decision is VerificationDecision.DISCARDED
    assert "not one of the" in gate.discarded[0].reason


def test_an_agent_may_only_speak_for_itself():
    """agents/replay asserting a respiration reading is out of its namespace."""
    gate = TrustGate()
    admitted = gate.admit(
        _observation(
            "agents/replay",
            "ans://v0.1.0.replay.batradar.club",
            [_assertion("people.respiration", "breathing")],
        )
    )

    assert admitted == []
    assert "belongs to agents/people" in gate.discarded[0].reason


def test_an_untrusted_agent_is_discarded_and_logged():
    """Suppression, not revocation. Only the RA revokes."""
    gate = TrustGate(profiles={"people": TrustProfile.UNTRUSTED})
    admitted = gate.admit(
        _observation(
            "agents/people",
            "ans://v0.1.0.people.batradar.club",
            [_assertion("people.personhood", "living_body")],
        )
    )

    assert admitted == []
    assert "discovery suppression, not revocation" in gate.discarded[0].reason


def test_a_valid_claim_is_still_capped_by_its_source_profile():
    """Authentication is not authorization. The battery's `underpay_valid_sig`.

    A READ_ONLY agent's claim asking for DISPATCHABLE is correctly formed,
    correctly attributed and still refused the magnitude it asked for.
    """
    gate = TrustGate(profiles={"people": TrustProfile.READ_ONLY})
    admitted = gate.admit(
        _observation(
            "agents/people",
            "ans://v0.1.0.people.batradar.club",
            [_assertion("people.respiration_lost", "240", ceiling=Severity.DISPATCHABLE)],
        ),
        envelope_verified=True,
    )

    assert len(admitted) == 1
    assert admitted[0].granted is Severity.CORROBORATING
    assert admitted[0].result.decision is VerificationDecision.CORROBORATION_ONLY


def test_nothing_is_speakable_while_the_transport_is_unwired():
    """Every claim caller speaks has a verified source or it does not get spoken.

    The rule is not relaxed because a demo is running, and it is not relaxed for
    a FIDUCIARY source either.
    """
    gate = TrustGate()
    admitted = gate.admit(
        _observation(
            "agents/people",
            "ans://v0.1.0.people.batradar.club",
            [_assertion("people.personhood", "living_body")],
        ),
        envelope_verified=False,
    )

    assert len(admitted) == 1
    assert admitted[0].spoken is False
    assert gate.speakable() == []
    check = next(c for c in admitted[0].result.checks if c.name == "envelope_verified")
    assert check.passed is False


def test_a_verified_fiduciary_claim_is_asserted():
    """The happy path, once the wire exists."""
    gate = TrustGate()
    admitted = gate.admit(
        _observation(
            "agents/people",
            "ans://v0.1.0.people.batradar.club",
            [_assertion("people.personhood", "living_body")],
        ),
        envelope_verified=True,
    )

    assert admitted[0].result.decision is VerificationDecision.ASSERTED
    assert admitted[0].spoken is True


# --------------------------------------------------------------- the master


def test_master_never_dials_on_its_own(mesh):
    """The whole project in reverse is a house that dials with nobody asking."""
    master = MasterAgent(mesh)
    master.raise_incident(IncidentType.FIRE, RaisedBy.SYSTEM)

    with pytest.raises(AutonomousDialRefused, match="never calls 911 on its own"):
        master.release_for_call()


def test_a_human_tap_releases_the_call(mesh):
    master = MasterAgent(mesh)
    master.raise_incident(IncidentType.FIRE, RaisedBy.USER)
    incident = master.release_for_call()

    assert incident.released_for_call is True
    assert incident.traceparent.startswith("00-")


def test_co_with_a_lost_breathing_signature_is_a_fire_with_someone_who_may_not_respond(
    verified_mesh, feed, roster
):
    """The two-modality case, and the one worth showing a judge.

    CSI resolved the breathing and then lost it; a separate gas sensor read the
    air. Neither alone is this verdict. And the verdict must not overclaim: a
    lost signature is not a finding that breathing stopped.
    """
    people = PeopleAgent(feed, roster)
    # Still and breathing, NOT moving. `SyntheticCsiFeed.occupy(moving=True)`
    # deliberately makes respiration unrecoverable - broadband motion noise
    # swamps the chest sinusoid - so a moving presence never establishes a
    # signature and therefore can never lose one. Task 1 found this the hard
    # way.
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(35):
        feed.advance(1)
        verified_mesh.publish(people.run_once())
    feed.vacate("main_bedroom")
    # 70 rather than 40: the 30s analysis window keeps resolving residual
    # breathing frames for roughly 22s after the body leaves, so the clock
    # only starts then.
    for _ in range(70):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    sensor = SimulatedCoSensor(ramp_ppm_per_s=200.0)
    sensor.trigger()
    sensor.advance(2.0)
    master = MasterAgent(verified_mesh, gas=sensor)
    master.run_once()
    observation = master.run_once()

    verdicts = [a for a in observation.assertions if a.field == "master.incident_type"]
    assert [a.value for a in verdicts] == [IncidentType.FIRE.value]
    assert "main_bedroom" in verdicts[0].basis
    assert "may not be able to respond" in verdicts[0].basis
    assert "not a finding" in verdicts[0].basis.lower()


def test_co_with_a_still_breathing_presence_is_a_fire_with_someone_not_moving(
    verified_mesh, feed, roster
):
    """The classic fire fatality: asleep while the air goes bad.

    Ranks below a lost signature and must say what it cannot tell. A radio
    that sees stillness and breathing cannot separate unconsciousness from
    sleep, and must not imply it can.
    """
    people = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(35):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    sensor = SimulatedCoSensor(ramp_ppm_per_s=200.0)
    sensor.trigger()
    sensor.advance(2.0)
    master = MasterAgent(verified_mesh, gas=sensor)
    master.run_once()
    observation = master.run_once()

    verdicts = [a for a in observation.assertions if a.field == "master.incident_type"]
    assert [a.value for a in verdicts] == [IncidentType.FIRE.value]
    assert "not moving" in verdicts[0].basis
    assert "unconsciousness from sleep" in verdicts[0].basis


def test_nothing_corroborating_and_nothing_raised_produces_no_classification(mesh):
    """The placeholder verdict is gone. No claims and no tap means no answer.

    Master used to publish `master.incident_type=faint` at confidence 0.0 on
    every idle tick. A placeholder that is shaped exactly like a verdict is how
    a placeholder gets read as one.
    """
    master = MasterAgent(mesh)
    observation = master.run_once()

    assert [a for a in observation.assertions if a.field == "master.incident_type"] == []


def test_the_air_reading_is_never_speakable_and_never_measured(verified_mesh):
    """A simulated reading from an unverified local input, labelled as both."""
    master = MasterAgent(verified_mesh, gas=SimulatedCoSensor())
    master.run_once()

    air = [c for c in master.admitted if c.assertion.field.startswith("master.co_")]
    assert air, "master publishes its air reading"
    for claim in air:
        assert claim.spoken is False
        assert claim.assertion.provenance.simulated is True
        assert claim.granted is Severity.CORROBORATING
        check = next(c for c in claim.result.checks if c.name == "measured")
        assert check.passed is False


def test_an_unreachable_agent_is_not_an_empty_one(mesh):
    """Unreachable and 'nothing to report' are different facts."""
    observation = MasterAgent(mesh).run_once()

    assert not observation.healthy
    assert {u.field for u in observation.unknowns} == {"people.*", "intruder.*"}


def test_an_operator_question_is_answered_from_a_fresh_pass(verified_mesh, feed, roster):
    """`answer` re-reads and re-admits rather than reading a cache."""
    people = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(130):
        feed.advance(1)
        verified_mesh.publish(people.run_once())

    master = MasterAgent(verified_mesh)
    value, why = master.answer("people.headcount")

    assert value == "2"
    assert "device associated" in why


def test_an_unverifiable_claim_answers_i_dont_know(mesh, feed, roster):
    """Verified-but-unspeakable is its own answer, and it is not 'no'."""
    people = PeopleAgent(feed, roster)
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(130):
        feed.advance(1)
        mesh.publish(people.run_once())

    master = MasterAgent(mesh)
    value, why = master.answer("people.headcount")

    assert value is None
    assert "not cryptographically verified" in why
