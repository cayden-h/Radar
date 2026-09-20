"""agents/intruder: roster arithmetic over a verified camera verdict.

Rewritten 2026-09-20. It used to feed CSI body counts through `agents/people`,
which resolved personhood from a respiration signature. That signature was cut
on 2026-09-19 and the code deleted on 2026-09-20, so the evidence is now a
camera and a router: two sensors that fail in genuinely unrelated ways.
"""

from __future__ import annotations

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity

from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion
from agents.core.ports import FetchedObservation
from agents.intruder import IntruderAgent

from .test_presence import unknown_fields, values

ROOM = "living_room"


def _vision(value: str, *, room: str = ROOM) -> AgentObservation:
    ident = identity("vision")
    return AgentObservation(
        agent=ident.name,
        ansname=ident.ansname,
        assertions=(
            Assertion(
                field="vision.occupancy",
                value=value,
                zone_scope=room,
                severity_ceiling=Severity.ACTIONABLE,
                confidence=0.9,
                basis="test fixture",
                provenance=Provenance(
                    source=Source.CAMERA_UVC,
                    producer=ident.name,
                    ansname=ident.ansname,
                    detail="test",
                ),
            ),
        ),
    )


class _Mesh:
    """A mesh whose verification status the test controls.

    `LocalMesh` always reports envelope_verified=False, which is the whole point
    of it, so a test about the verified path has to say so explicitly.
    """

    def __init__(self) -> None:
        self._obs: dict[str, FetchedObservation] = {}

    def put(self, slug: str, obs: AgentObservation, *, verified: bool = True) -> None:
        self._obs[slug] = FetchedObservation(observation=obs, envelope_verified=verified)

    def fetch(self, slug: str) -> FetchedObservation | None:
        return self._obs.get(slug)


def _seen(value: str, *, verified: bool = True) -> _Mesh:
    mesh = _Mesh()
    mesh.put("vision", _vision(value), verified=verified)
    return mesh


def test_a_person_with_no_associated_device_is_unexpected(roster):
    """The clean case: house registered empty, a person in frame."""
    roster.leave("dev-a")
    roster.leave("dev-b")

    observation = IntruderAgent(roster, _seen("person_present")).run_once()

    assert values(observation, "intruder.unexpected_presence") == ["true"]
    assert values(observation, "intruder.intruder_zone") == [ROOM]


def test_a_person_with_an_associated_device_is_accounted_for(roster):
    """A resident is home by device association, so the person in frame is
    explained. The camera never says which person, and does not need to."""
    observation = IntruderAgent(roster, _seen("person_present")).run_once()

    assert values(observation, "intruder.unexpected_presence") == ["false"]


def test_no_person_is_never_an_intruder(roster):
    """The curtain case, and the reason the camera took this job from the
    radio. An empty frame after motion is a curtain, a pet, or a draft."""
    roster.leave("dev-a")
    roster.leave("dev-b")

    observation = IntruderAgent(roster, _seen("no_person")).run_once()

    assert values(observation, "intruder.unexpected_presence") == ["false"]


def test_no_camera_verdict_is_blind_rather_than_false(roster):
    """Absence of a verdict is not evidence of absence. The agent reports that
    it could not decide rather than deciding there is nobody."""
    observation = IntruderAgent(roster, _Mesh()).run_once()

    assert not observation.healthy
    assert "intruder.unexpected_presence" in unknown_fields(observation)


def test_the_basis_names_the_holes(roster):
    """The rule's gaps get said out loud in the claim itself, because they are
    what a judge will ask about."""
    roster.leave("dev-a")
    roster.leave("dev-b")

    observation = IntruderAgent(roster, _seen("person_present")).run_once()

    (basis,) = [
        a.basis
        for a in observation.assertions
        if a.field == "intruder.unexpected_presence"
    ]
    assert "phone" in basis.lower()
    assert "guest" in basis.lower()


def test_an_unverified_camera_verdict_caps_severity(roster):
    """An unverified upstream verdict is still reported - the information is
    real and a resident should see it - but it must not send anyone."""
    roster.leave("dev-a")
    roster.leave("dev-b")

    observation = IntruderAgent(
        roster, _seen("person_present", verified=False)
    ).run_once()

    (assertion,) = [
        a for a in observation.assertions if a.field == "intruder.unexpected_presence"
    ]
    assert assertion.severity_ceiling is Severity.CORROBORATING


def test_the_track_survives_a_frame_with_nobody_in_it(roster):
    """A track that flickers off and back on tells an officer the intruder
    left. Once declared it is held through clear ticks."""
    roster.leave("dev-a")
    roster.leave("dev-b")
    mesh = _Mesh()
    agent = IntruderAgent(roster, mesh)

    mesh.put("vision", _vision("person_present"))
    agent.run_once()

    mesh.put("vision", _vision("no_person"))
    observation = agent.run_once()

    assert values(observation, "intruder.unexpected_presence") == ["true"]
