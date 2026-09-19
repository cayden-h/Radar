"""Shared fixtures. Zones match the demo floorplan the hub already ships."""

from __future__ import annotations

import pytest

from agents.core.dev import StaticRoster, SyntheticCsiFeed
from agents.core.observations import AgentObservation
from agents.core.ports import FetchedObservation, LocalMesh

ZONES = ("main_bedroom", "second_bedroom", "living_room", "kitchen", "laundry")


@pytest.fixture
def feed() -> SyntheticCsiFeed:
    return SyntheticCsiFeed(ZONES)


@pytest.fixture
def roster() -> StaticRoster:
    return StaticRoster()


@pytest.fixture
def mesh() -> LocalMesh:
    return LocalMesh()


class StubMesh(LocalMesh):
    """A LocalMesh that can claim its handoffs were verified.

    A test double, and labelled as one. It exists so a test about classification
    or about the profile gate does not have to stand up two HTTP servers to say
    "assume this arrived verified". Anything testing the *verification* itself
    uses the real transport - see `tests/test_wire.py`, which is the one that
    proves the property rather than assuming it.
    """

    def __init__(self, *, verified: bool = False) -> None:
        super().__init__()
        self.verified = verified

    def fetch(self, slug: str) -> FetchedObservation | None:
        observation: AgentObservation | None = self.observation(slug)
        if observation is None:
            return None
        return FetchedObservation(observation=observation, envelope_verified=self.verified)


@pytest.fixture
def verified_mesh() -> StubMesh:
    return StubMesh(verified=True)
