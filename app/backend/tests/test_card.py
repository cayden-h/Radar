"""Agent card hardening: signing, drift, and the dispatch-address commitment.

These cover the surface `agent.webmesh.ai verify_agent` actually inspects, plus
the two bonus structural checks `fraud.webmesh.ai` runs alongside its thirteen:
`card_drift_watch` and `payTo_binding_check`.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hawkeye_backend.verification.card import (
    address_matches,
    card_fingerprint,
    commit_address,
    sign_card,
    verify_card,
)

TRUST_CARD = "https://biometrics.hawkeye.example/.well-known/ans/trust-card.json"
KID = "ocmJWjyVDuMUiyZMa6pOGrgx_dZhSnSDsz35hmN-k9k"

CARD = {
    "name": "Hawk Eye Biometrics",
    "url": "https://biometrics.hawkeye.example",
    "version": "1.0.0",
    "protocolVersion": "1.0",
    "securitySchemes": {"ansIdentityCert": {"type": "mutualTLS"}},
    "x-security-note": "mTLS is enforced on this agent. The card accurately describes what is enforced.",
}


def test_card_signature_round_trips():
    key = Ed25519PrivateKey.generate()
    signed = sign_card(CARD, key, trust_card_url=TRUST_CARD, kid=KID)
    assert verify_card(signed, key.public_key()) is True
    assert signed["signatures"][0]["header"]["kid"] == KID


def test_tampered_card_fails_verification():
    """The whole point of signing it. Change a field, the signature dies."""
    key = Ed25519PrivateKey.generate()
    signed = sign_card(CARD, key, trust_card_url=TRUST_CARD, kid=KID)
    signed["url"] = "https://attacker.example"
    assert verify_card(signed, key.public_key()) is False


def test_card_from_another_key_fails():
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    signed = sign_card(CARD, key, trust_card_url=TRUST_CARD, kid=KID)
    assert verify_card(signed, other.public_key()) is False


def test_unsigned_card_is_not_valid():
    assert verify_card(dict(CARD), Ed25519PrivateKey.generate().public_key()) is False


def test_malformed_signature_does_not_throw():
    """A card is untrusted input too. Invalid means False, never an exception."""
    key = Ed25519PrivateKey.generate()
    signed = sign_card(CARD, key, trust_card_url=TRUST_CARD, kid=KID)
    signed["signatures"][0]["protected"] = "!!!not-base64!!!"
    assert verify_card(signed, key.public_key()) is False


def test_fingerprint_is_stable_across_key_order():
    """card_drift_watch analogue. Reformatting is not drift."""
    a = {"name": "x", "version": "1.0.0", "url": "https://a.example"}
    b = {"url": "https://a.example", "name": "x", "version": "1.0.0"}
    assert card_fingerprint(a) == card_fingerprint(b)


def test_fingerprint_changes_when_content_changes():
    a = dict(CARD)
    b = dict(CARD, version="1.0.1")
    assert card_fingerprint(a) != card_fingerprint(b)


def test_dispatch_address_commitment_matches():
    """payTo_binding_check analogue, the positive case."""
    commitment, salt = commit_address("221B Baker Street, London")
    assert address_matches(commitment, "221B Baker Street, London", salt) is True


def test_dispatch_address_cannot_be_swapped():
    """The attack this exists to stop: redirecting the response."""
    commitment, salt = commit_address("221B Baker Street, London")
    assert address_matches(commitment, "10 Downing Street, London", salt) is False


def test_commitment_does_not_leak_the_address():
    """The card is world-readable. The address must not be recoverable from it."""
    address = "221B Baker Street, London"
    commitment, _ = commit_address(address)
    fragment = commitment.card_fragment()
    serialized = str(fragment)
    assert "Baker" not in serialized
    assert "221B" not in serialized
    assert fragment["dispatchAddressCommitment"].startswith("sha256:")


def test_same_address_different_salt_gives_different_commitment():
    """Two installations at the same address must not be linkable by their cards."""
    a, _ = commit_address("221B Baker Street, London")
    b, _ = commit_address("221B Baker Street, London")
    assert a.commitment != b.commitment
