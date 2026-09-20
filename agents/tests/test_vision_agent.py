"""The ANS wrapper over the camera pipeline.

Runs entirely on a scripted source. No weights, no camera, no MPS backend -
the same rule `StubShutter` follows, because the demo must never depend on
hardware being alive.
"""

from __future__ import annotations

import pytest
from hawkeye_backend.models.common import Source, SourceClass
from hawkeye_vision.occupancy import Occupancy

from agents.vision.agent import VisionAgent

ROOM = "living_room"


class _FakeSource:
    """Stands in for the capture loop: hands over one frame's verdict."""

    def __init__(self, verdict: Occupancy) -> None:
        self._verdict = verdict

    def occupancy(self) -> Occupancy:
        return self._verdict


def _agent(verdict: Occupancy, *, source: Source = Source.CAMERA_UVC) -> VisionAgent:
    return VisionAgent(_FakeSource(verdict), room=ROOM, source_kind=source)


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
        VisionAgent(_FakeSource(Occupancy.NO_PERSON), room=ROOM, source_kind=Source.NEXMON_CSI)


@pytest.mark.parametrize("verdict", list(Occupancy))
def test_every_verdict_keeps_the_agent_healthy(verdict: Occupancy) -> None:
    """An unavailable tracker is a fact to report, not a crash."""
    assert _agent(verdict).tick().healthy is True
