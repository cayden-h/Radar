"""Turning an assertion into a signed, bound claim on the wire.

This is the producing half of the pair `hawkeye_backend.verification` already
implements the consuming half of. Until 2026-09-19 it existed only as a test
fixture, which meant no shipped code could actually produce a claim.

An `Assertion` says *what is true*. A signed claim says what is true, **to
whom, about which incident, answering which challenge, valid until when, and
presented by whom**. Those bindings are not decoration: each one is a lock, and
the fraud battery is thirteen ways of trying to pick one.

Two rules here are load-bearing and both are easy to get wrong:

1. **Sign what the verifier canonicalizes**, by going through the pydantic model
   rather than building the dict by hand. Hand-building produced a different
   datetime serialization than pydantic's, which is exactly the class of bug
   battery probe #13 (`canonicalization_probe`) exists to catch, and it presents
   as a signature mismatch that looks identical to tampering.
2. **The bytes that get signed are the bytes that get sent.** `SignedPair`
   carries `bytes`, not objects, and the transport moves them verbatim. Parsing
   and re-serializing anywhere in between breaks every signature.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from hawkeye_backend.models.common import utc_now
from hawkeye_backend.verification.b64 import b64u_encode, key_thumbprint
from hawkeye_backend.verification.canonical import canonicalize
from hawkeye_backend.verification.envelope import ClaimEnvelope, PossessionProof, SignedClaim

from agents.core.identity import AgentIdentity
from agents.core.observations import Assertion

#: Envelope schema this producer speaks. The verifier refuses anything it does
#: not understand rather than reading it charitably, so bumping this is a
#: coordinated change across the mesh and not a local one.
SCHEMA_VERSION = "1.0"

#: How long a claim is good for. Short on purpose: a claim is an answer to a
#: question asked seconds ago, and interior state is exactly the kind of fact
#: that stops being true. Long enough to survive a slow hop, short enough that a
#: captured claim is worthless almost immediately.
DEFAULT_TTL = timedelta(seconds=90)


@dataclass(frozen=True)
class SignedPair:
    """One claim and its possession proof, as the exact bytes to put on the wire."""

    raw_claim: bytes
    raw_proof: bytes
    claim_id: str
    field: str


class ClaimSigner:
    """Signs one agent's assertions under that agent's own key.

    The key is the agent's identity in the only sense that matters on the wire.
    It is loaded at startup, never in the repository, and its public half is
    published in the agent's trust card so `master` can find it without being
    told where.
    """

    def __init__(self, identity: AgentIdentity, key: Ed25519PrivateKey) -> None:
        self._identity = identity
        self._key = key

    @property
    def public_key_b64(self) -> str:
        """Raw Ed25519 public key, base64url. What goes in the trust card."""
        return b64u_encode(self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))

    @property
    def thumbprint(self) -> str:
        return key_thumbprint(self._key.public_key())

    def sign(
        self,
        assertion: Assertion,
        *,
        audience: str,
        incident_id: str,
        nonce: str,
        target: str,
        ttl: timedelta = DEFAULT_TTL,
    ) -> SignedPair:
        """Bind an assertion to one question and sign it.

        `nonce` is the challenge the verifier issued for this fan-out, and it is
        the reason an agent cannot usefully sign anything in advance.
        """
        now = utc_now()
        envelope = ClaimEnvelope(
            schema_version=SCHEMA_VERSION,
            claim_id=f"clm-{uuid.uuid4().hex[:16]}",
            issuer=self._identity.ansname,
            audience=audience,
            incident_id=incident_id,
            zone_scope=assertion.zone_scope,
            field=assertion.field,
            value=assertion.value,
            severity_ceiling=assertion.severity_ceiling,
            # The envelope names the key that must present it. The proof below
            # is signed by that key, and the verifier checks the binding before
            # it does any signature work, so a swapped key fails closed rather
            # than verifying under the attacker's own key.
            proof_key_thumbprint=self.thumbprint,
            issued_at=now,
            expires_at=now + ttl,
        )
        body = envelope.model_dump(mode="json")
        canonical = canonicalize(body)
        claim = SignedClaim(
            envelope=envelope,
            signature=b64u_encode(self._key.sign(canonical)),
        )

        draft = PossessionProof(
            method="POST",
            target=target,
            # Single use. A fresh id per claim, so two claims in one fan-out
            # cannot be collapsed into one replayable proof.
            proof_id=f"prf-{uuid.uuid4().hex[:16]}",
            nonce=nonce,
            issued_at=now,
            # Content binding: the proof covers this exact envelope, so a valid
            # proof cannot be lifted onto a different claim.
            content_digest=b64u_encode(hashlib.sha256(canonical).digest()),
            public_key=self.public_key_b64,
            signature="",
        )
        unsigned = draft.model_dump(mode="json")
        unsigned.pop("signature", None)
        proof = draft.model_copy(
            update={"signature": b64u_encode(self._key.sign(canonicalize(unsigned)))}
        )

        return SignedPair(
            raw_claim=claim.model_dump_json().encode(),
            raw_proof=proof.model_dump_json().encode(),
            claim_id=envelope.claim_id,
            field=assertion.field,
        )
