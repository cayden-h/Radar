"""Shared fixtures: a signing agent, a trust store, and a verifier."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.verification import TrustProfile
from hawkeye_backend.verification import (
    ClaimEnvelope,
    ClaimVerifier,
    KnownAgent,
    PossessionProof,
    SignedClaim,
    TrustStore,
    VerifierPolicy,
)
from hawkeye_backend.verification.b64 import b64u_encode, key_thumbprint
from hawkeye_backend.verification.canonical import canonicalize
from hawkeye_backend.verification.envelope import Severity

MASTER = "ans://v1.0.0.master.hawkeye.example"
TARGET = "https://master.hawkeye.example/v1/claims"
INCIDENT = "inc-2026-09-19-0001"

# The challenge master issued for the fan-out these fixtures answer. Server
# supplied in production; a constant here so a test that is probing some other
# property does not have to think about it.
NONCE = "chal-0001"


class Agent:
    """A sensing agent that can sign claims and proofs."""

    def __init__(self, ansname: str, profile: TrustProfile, version: str = "1.0.0") -> None:
        self.ansname = ansname
        self.profile = profile
        self.version = version
        self._key = Ed25519PrivateKey.generate()

    @property
    def public_key(self):
        return self._key.public_key()

    @property
    def thumbprint(self) -> str:
        return key_thumbprint(self.public_key)

    def known(self) -> KnownAgent:
        return KnownAgent(
            ansname=self.ansname,
            public_key=self.public_key,
            profile=self.profile,
            certificate_version=self.version,
        )

    def envelope(self, **overrides) -> ClaimEnvelope:
        base = dict(
            schema_version="1.0",
            claim_id="clm-0001",
            issuer=self.ansname,
            audience=MASTER,
            incident_id=INCIDENT,
            zone_scope="main_bedroom",
            field="people.respiration",
            value="absent",
            severity_ceiling=Severity.DISPATCHABLE,
            proof_key_thumbprint=self.thumbprint,
            issued_at=utc_now(),
            expires_at=utc_now() + timedelta(minutes=5),
        )
        base.update(overrides)
        return ClaimEnvelope(**base)

    def sign_claim(self, env: ClaimEnvelope) -> SignedClaim:
        sig = self._key.sign(canonicalize(env.model_dump(mode="json")))
        return SignedClaim(envelope=env, signature=b64u_encode(sig))

    def sign_proof(
        self, env: ClaimEnvelope, *, proof_id="prf-0001", target=TARGET, nonce=NONCE, **overrides
    ):
        digest = b64u_encode(hashlib.sha256(canonicalize(env.model_dump(mode="json"))).digest())
        body = dict(
            method="POST",
            target=target,
            proof_id=proof_id,
            nonce=nonce,
            issued_at=utc_now(),
            content_digest=digest,
            public_key=b64u_encode(self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)),
        )
        body.update(overrides)
        # Sign exactly what the verifier canonicalizes: the model's own JSON
        # dump minus the signature. Building the dict by hand here produced a
        # different datetime serialization than pydantic's, which is precisely
        # the class of bug battery probe #13 exists to catch - so the signer
        # goes through the model rather than around it.
        draft = PossessionProof(**body, signature="")
        unsigned = draft.model_dump(mode="json")
        unsigned.pop("signature", None)
        sig = self._key.sign(canonicalize(unsigned))
        return draft.model_copy(update={"signature": b64u_encode(sig)})


@pytest.fixture
def sensor() -> Agent:
    """A FIDUCIARY sensing agent. The well-behaved one."""
    return Agent("ans://v1.0.0.people.hawkeye.example", TrustProfile.FIDUCIARY)


@pytest.fixture
def trust(sensor: Agent) -> TrustStore:
    return TrustStore([sensor.known()])


@pytest.fixture
def verifier(trust: TrustStore) -> ClaimVerifier:
    return ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust)
