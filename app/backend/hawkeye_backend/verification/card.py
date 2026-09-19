"""Agent card signing, drift detection, and the dispatch-address commitment.

`agent.webmesh.ai verify_agent(agent_host, environment)` takes an arbitrary
hostname and reports a compatibility verdict built from DNS, DNSSEC,
Transparency Log proof, and **the published agent card**. That is what will
actually be pointed at us, so the card is the surface under test. Full spec and
checklist: `ans/CARD.md`.

Three properties are enforced here rather than by convention:

1. The card is signed, with the JWS shape the reference cards use.
2. The card is byte-stable, so `card_drift_watch` sees drift only when we
   actually changed something.
3. The dispatch address is committed to, not published.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from hawkeye_backend.verification.b64 import b64u_decode, b64u_encode
from hawkeye_backend.verification.canonical import canonicalize


def card_signing_input(card: dict[str, Any], protected: dict[str, Any]) -> bytes:
    """What gets signed: canonical protected header, then canonical card.

    The card is canonicalized **with `signatures` removed**, matching the
    reference cards at webmesh.ai. Canonicalization is shared with the claim
    envelope, so there is one JCS implementation in this codebase and battery
    probe #13 has nothing to find.
    """
    body = {k: v for k, v in card.items() if k != "signatures"}
    return b64u_encode(canonicalize(protected)).encode("ascii") + b"." + b64u_encode(canonicalize(body)).encode("ascii")


def sign_card(card: dict[str, Any], key: Ed25519PrivateKey, *, trust_card_url: str, kid: str) -> dict[str, Any]:
    """Return the card with a `signatures` array, shaped like the live ones.

    Header mirrors `fraud.webmesh.ai` exactly: EdDSA, `agent-card+jws`, `jku`
    pointing at our own trust card, `kid` matching the key published there.
    """
    protected = {"alg": "EdDSA", "jku": trust_card_url, "kid": kid, "typ": "agent-card+jws"}
    signature = key.sign(card_signing_input(card, protected))
    signed = {k: v for k, v in card.items() if k != "signatures"}
    signed["signatures"] = [
        {
            "protected": b64u_encode(canonicalize(protected)),
            "signature": b64u_encode(signature),
            "header": {"kid": kid},
        }
    ]
    return signed


def verify_card(card: dict[str, Any], key: Ed25519PublicKey) -> bool:
    """Check a card's signature. Never throws; a malformed card is just invalid."""
    try:
        sigs = card.get("signatures") or []
        if not sigs:
            return False
        entry = sigs[0]
        import json

        protected = json.loads(b64u_decode(entry["protected"]))
        key.verify(b64u_decode(entry["signature"]), card_signing_input(card, protected))
    except Exception:  # noqa: BLE001 - any failure is "not a valid card"
        return False
    return True


def card_fingerprint(card: dict[str, Any]) -> str:
    """Stable hash of a card, for drift detection.

    This is what `card_drift_watch` computes. Hashing the canonical form rather
    than the served bytes means reformatting is not drift, but a changed value
    is. Run it against ourselves on a timer: if a card changes and we did not
    ship a version, something is wrong and we would rather find it than have
    `verify_agent` find it on Sunday morning.
    """
    return "sha256:" + b64u_encode(hashlib.sha256(canonicalize(card)).digest())


# --------------------------------------------------------- dispatch address

@dataclass(frozen=True)
class AddressCommitment:
    """A commitment to the dispatch address, safe to publish.

    The `payTo_binding_check` analogue, and the most important binding in the
    project. An agent that can change where a response is sent is a swatting
    tool no matter how well the claims upstream verify.

    The complication is that the card is world-readable, and publishing the
    street address of someone who cannot get off the floor is a worse outcome
    than the attack. So the card carries a commitment; the salt and the
    plaintext are sealed at registration and never served.

    The property falls out: the address cannot change without re-registration,
    and nobody reading the card learns where anyone lives.
    """

    commitment: str
    scheme: str = "SHA-256 over salt || JCS(canonical_address)"

    def card_fragment(self) -> dict[str, Any]:
        return {"dispatchAddressCommitment": self.commitment, "commitmentScheme": self.scheme}


def commit_address(canonical_address: str, salt: bytes | None = None) -> tuple[AddressCommitment, bytes]:
    """Commit to an address. Returns the public commitment and the secret salt."""
    salt = salt or secrets.token_bytes(32)
    digest = hashlib.sha256(salt + canonicalize(canonical_address)).digest()
    return AddressCommitment(commitment="sha256:" + b64u_encode(digest)), salt


def address_matches(commitment: AddressCommitment, canonical_address: str, salt: bytes) -> bool:
    """Check an address against a commitment, in constant time.

    `agents/caller` calls this over the address it is about to speak, and
    refuses the call if it does not match. No sensing claim, no operator
    question, and no resident typing into the app can move it.
    """
    expected, _ = commit_address(canonical_address, salt)
    return secrets.compare_digest(expected.commitment, commitment.commitment)
