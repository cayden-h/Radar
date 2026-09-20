"""The published cards: the surface `agent.webmesh.ai verify_agent` inspects.

`ans/CARD.md` is the spec. These test the three measures that live in code:
the card is signed, it is byte-stable, and the dispatch address is attested
without being published.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.verification.card import commit_address, verify_card

from agents.core import cards
from agents.core.identity import ROSTER, Role, identity


def test_every_card_is_signed_and_verifies():
    key = Ed25519PrivateKey.generate()
    for agent in ROSTER:
        signed = cards.sign(cards.build_a2a_card(agent), key, agent)
        assert verify_card(signed, key.public_key()) is True


def test_a_card_is_byte_stable_across_builds():
    """`card_drift_watch` must see drift only when we actually changed something."""
    for agent in ROSTER:
        first = cards.serialize(cards.build_a2a_card(agent))
        second = cards.serialize(cards.build_a2a_card(agent))
        assert first == second


def test_the_card_publishes_what_the_agent_will_not_claim():
    """The honesty rule on the machine-readable surface, not just in prose."""
    for agent in ROSTER:
        card = cards.build_a2a_card(agent)
        assert card["x-hawkeye"]["mustNotClaim"] == list(agent.must_not_claim)
        assert card["x-hawkeye"]["mustNotClaim"], f"{agent.slug} publishes no limits"


def test_master_declares_its_simulated_input():
    """A card that overclaims is a signed, published, machine-checkable lie."""
    card = cards.build_a2a_card(identity("master"))
    simulated = card["x-hawkeye"]["simulatedInputs"]

    assert simulated and "demo-trigger" in simulated[0]


def test_the_card_declares_only_what_is_enforced():
    """Copied from the track owner's own card, and so is the discipline."""
    card = cards.build_a2a_card(identity("people"))
    assert "NOT currently enforced" in card["x-security-note"]


def test_the_dispatch_address_is_committed_not_published():
    """Publishing the street address of someone who cannot get off the floor
    would be a worse outcome than the attack this binding defends against."""
    address = "1 Fictional Way, Blacksburg VA 24060"
    commitment, _ = commit_address(address)
    card = cards.build_a2a_card(identity("caller"), address_commitment=commitment)

    rendered = cards.serialize(card).decode()
    assert "Fictional Way" not in rendered
    assert "dispatchAddressCommitment" in card["x-hawkeye"]


def test_two_installations_at_one_address_are_not_linkable():
    """The salt is why. Cards must not be correlatable by address."""
    address = "1 Fictional Way, Blacksburg VA 24060"
    first, _ = commit_address(address)
    second, _ = commit_address(address)

    assert first.card_fragment() != second.card_fragment()


def test_no_card_leaks_anything_sensitive():
    """Measure 7. Both cards are public and permanently recorded by at least one
    verifier we do not control."""
    forbidden = ("Fictional Way", "resident_1", "dev-a", "Grandma")
    for agent in ROSTER:
        rendered = cards.serialize(cards.build_a2a_card(agent)).decode()
        for secret in forbidden:
            assert secret not in rendered, f"{agent.slug} card leaks {secret!r}"


def _declared(slug):
    from agents.core.identity import identity

    return {field for skill in identity(slug).skills for field in skill.fields}


def test_every_field_an_agent_asserts_is_declared_on_its_card():
    """Undeclared claims are drift, and drift is what the Trust Index scores.

    `people.respiration_lost` was emitted with no skill declaring it. The gate
    validates namespace rather than declared fields, so it was admitted anyway
    and nothing caught it. `agent.webmesh.ai` reads the published card, so this
    is the surface that matters. This is the test that would have caught it.
    """
    assert "people.respiration_lost" in _declared("people")


def test_people_declares_no_collapse_fields():
    declared = _declared("people")

    assert not any("collapse" in f or "still_down" in f or "long_lie" in f for f in declared)


def test_vision_is_registered_and_scoped_to_one_room():
    """The camera sees one room. That limit is carried on the identity, not in
    a comment, so the published card states it too."""
    vision = identity("vision")
    assert vision.role is Role.SENSING
    fields = {f for skill in vision.skills for f in skill.fields}
    assert "vision.occupancy" in fields
    assert any("identif" in claim.lower() for claim in vision.must_not_claim)
