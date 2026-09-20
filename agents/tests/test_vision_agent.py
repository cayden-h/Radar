"""The ANS wrapper over the camera pipeline.

Runs entirely on a scripted source. No weights, no camera, no MPS backend -
the same rule `StubShutter` follows, because the demo must never depend on
hardware being alive.

The shutter-attestation gate is the T16 rule: `vision` produces no claim
without a current, verified, open attestation from `shutter`. The occupancy
tests below therefore run behind a fresh open attestation; the gate itself is
exercised directly at the bottom of the file - absent, stale, and valid, with
only the valid case producing a description.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hawkeye_backend.models.common import Source, SourceClass
from hawkeye_vision.narrate import UNREACHABLE, Narration
from hawkeye_vision.occupancy import Occupancy

from agents.shutter.backend import CLOSED_ANGLE, OPEN_ANGLE
from agents.shutter.shutter import Attestation
from agents.vision.agent import VisionAgent
from agents.vision.attestation import (
    ATTESTATION_TTL_S,
    InProcessAttestations,
    InProcessNarrations,
)

ROOM = "living_room"


class _FakeSource:
    """Stands in for the capture loop: hands over one frame's verdict."""

    def __init__(self, verdict: Occupancy) -> None:
        self._verdict = verdict

    def occupancy(self) -> Occupancy:
        return self._verdict


def _open(*, age_s: float = 0.0, position: str = "open") -> Attestation:
    """An attestation aged `age_s` seconds into the past."""
    angle = OPEN_ANGLE if position == "open" else CLOSED_ANGLE
    return Attestation(
        position=position,
        commanded_angle=angle,
        nonce="test-nonce",
        at=datetime.now(UTC) - timedelta(seconds=age_s),
    )


def _line(text: str = "A person is standing near the door.") -> Narration:
    return Narration(text=text, at=datetime.now(UTC), frame_index=0, model="test", latency_s=0.0)


def _agent(
    verdict: Occupancy,
    *,
    source: Source = Source.CAMERA_UVC,
    attestation: Attestation | None = None,
    narration: Narration | None = None,
) -> VisionAgent:
    """A vision agent behind a fresh open attestation unless told otherwise."""
    att = attestation if attestation is not None else _open()
    nar = narration if narration is not None else _line()
    return VisionAgent(
        _FakeSource(verdict),
        attestations=InProcessAttestations(att),
        narrations=InProcessNarrations(nar),
        room=ROOM,
        source_kind=source,
    )


def test_no_person_is_asserted_and_scoped() -> None:
    obs = _agent(Occupancy.NO_PERSON).tick()
    (assertion,) = [a for a in obs.assertions if a.field == "vision.occupancy"]
    assert assertion.value == "no_person"
    assert assertion.zone_scope == ROOM


def test_person_present_is_asserted() -> None:
    obs = _agent(Occupancy.PERSON_PRESENT).tick()
    assert obs.value("vision.occupancy") == "person_present"


def test_unavailable_tracker_asserts_nothing_and_says_why() -> None:
    """A blind camera must not produce an occupancy assertion at all. An
    assertion of `tracker_unavailable` would still be a value a careless
    consumer could compare against, so it goes in `unknowns` instead."""
    obs = _agent(Occupancy.TRACKER_UNAVAILABLE).tick()
    assert obs.value("vision.occupancy") is None
    (unknown,) = [u for u in obs.unknowns if u.field == "vision.occupancy"]
    assert "could not look" in unknown.reason.lower()


def test_a_real_camera_is_labelled_measured() -> None:
    obs = _agent(Occupancy.NO_PERSON, source=Source.CAMERA_UVC).tick()
    (assertion,) = [a for a in obs.assertions if a.field == "vision.occupancy"]
    assert assertion.provenance.source is Source.CAMERA_UVC
    assert assertion.provenance.source_class is SourceClass.MEASURED_LIVE
    assert assertion.provenance.producer == "agents/vision"


def test_a_fixture_cannot_present_as_a_camera() -> None:
    """The honesty rule, enforced in the data. A synthetic feed carries
    CAMERA_SIM and computes to simulated, so the app's badge is not optional."""
    obs = _agent(Occupancy.NO_PERSON, source=Source.CAMERA_SIM).tick()
    (assertion,) = [a for a in obs.assertions if a.field == "vision.occupancy"]
    assert assertion.provenance.simulated is True


def test_the_source_must_be_a_camera() -> None:
    """A vision claim carrying a CSI or servo source would be a lie about
    which sensor produced it, and it is refused at construction."""
    with pytest.raises(ValueError, match="camera"):
        VisionAgent(
            _FakeSource(Occupancy.NO_PERSON),
            attestations=InProcessAttestations(_open()),
            narrations=InProcessNarrations(_line()),
            room=ROOM,
            source_kind=Source.NEXMON_CSI,
        )


@pytest.mark.parametrize("verdict", list(Occupancy))
def test_every_verdict_keeps_the_agent_healthy(verdict: Occupancy) -> None:
    """An unavailable tracker is a fact to report, not a crash."""
    assert _agent(verdict).tick().healthy is True


# --------------------------------------------------------------- the gate (T16)


def test_absent_attestation_claims_nothing() -> None:
    """No attestation at all: both occupancy and description are withheld, and
    each says why. A camera that cannot prove the shield is clear must not
    describe the room even when the tracker sees a person."""
    agent = VisionAgent(
        _FakeSource(Occupancy.PERSON_PRESENT),
        attestations=InProcessAttestations(None),
        narrations=InProcessNarrations(_line()),
        room=ROOM,
        source_kind=Source.CAMERA_UVC,
    )
    obs = agent.tick()
    assert obs.assertions == ()
    fields = {u.field: u.reason for u in obs.unknowns}
    assert fields["vision.occupancy"] == "shield_closed"
    assert fields["vision.description"] == "shield_closed"


def test_stale_attestation_claims_nothing() -> None:
    """An attestation older than the TTL is as good as none. A stale grant is
    exactly what a jammed or reclosed shield looks like, so it fails closed."""
    obs = _agent(
        Occupancy.PERSON_PRESENT,
        attestation=_open(age_s=ATTESTATION_TTL_S + 5.0),
    ).tick()
    assert obs.assertions == ()
    fields = {u.field: u.reason for u in obs.unknowns}
    assert fields["vision.description"] == "shield_closed"


def test_a_closed_attestation_claims_nothing() -> None:
    """A fresh attestation that reports the shield still closed is not a grant
    to see. Freshness alone is not the gate; the position has to read open."""
    obs = _agent(Occupancy.PERSON_PRESENT, attestation=_open(position="closed")).tick()
    assert obs.assertions == ()
    assert {u.field for u in obs.unknowns} >= {"vision.occupancy", "vision.description"}


def test_valid_attestation_produces_a_description() -> None:
    """The one case that narrates: a fresh, open attestation. The description
    carries the narration text and is labelled generated, and occupancy is
    asserted alongside it."""
    obs = _agent(Occupancy.PERSON_PRESENT, narration=_line("A person is by the window.")).tick()
    (desc,) = [a for a in obs.assertions if a.field == "vision.description"]
    assert desc.value == "A person is by the window."
    assert desc.zone_scope == ROOM
    assert obs.value("vision.occupancy") == "person_present"


def test_valid_attestation_but_no_narration_is_unreachable() -> None:
    """Behind an open shield with nothing from the narrator, occupancy still
    asserts but the description is an honest gap rather than an invention."""
    obs = VisionAgent(
        _FakeSource(Occupancy.PERSON_PRESENT),
        attestations=InProcessAttestations(_open()),
        narrations=InProcessNarrations(None),
        room=ROOM,
        source_kind=Source.CAMERA_UVC,
    ).tick()
    assert obs.value("vision.occupancy") == "person_present"
    (unknown,) = [u for u in obs.unknowns if u.field == "vision.description"]
    assert unknown.reason == UNREACHABLE
