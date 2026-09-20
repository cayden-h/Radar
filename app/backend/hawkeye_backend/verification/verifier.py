"""The pipeline. Verify the envelope, check the bindings, then authorize.

Order follows ANS-6 section 7.4: cheapest and least stateful first, trust last.
The single rule the whole file exists to enforce:

    A valid signature is not authorization.

Ten of the thirteen battery shapes pass only if that is true. Step 5 is where
signature verification finishes; steps 6 through 10 are the ones that refuse a
genuinely, correctly signed claim that is being used for something it does not
authorize. Battery #4, `underpay_valid_sig`, is the pure case.

A note on why the order is not cosmetic. `remember()` on the replay cache runs
last, after every other check. Recording earlier lets anyone holding a
self-signed key flood a bounded cache and fail-close authentication for every
legitimate caller, which on this system is a denial of service against a 911
call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.verification import (
    PROFILE_DECISION,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
)
from hawkeye_backend.verification.b64 import b64u_decode, b64u_encode, key_thumbprint
from hawkeye_backend.verification.canonical import canonicalize
from hawkeye_backend.verification.envelope import (
    SEVERITY_ORDER,
    ClaimEnvelope,
    PossessionProof,
    Severity,
    SignedClaim,
)
from hawkeye_backend.verification.errors import RejectionCode, VerificationRejected
from hawkeye_backend.verification.replay import ReplayCache, ReplayCacheSaturated
from hawkeye_backend.verification.trust import TrustStore

# The largest envelope we will parse. Bound before parsing, per ANS-6 7.4 step 1.
MAX_ENVELOPE_BYTES = 8 * 1024

# Freshness window for a possession proof. ANS-6 default.
DEFAULT_SKEW = timedelta(seconds=120)

# Schema versions this verifier understands. Anything else is refused rather
# than interpreted charitably. Battery #10.
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})

# What each profile's claims are permitted to trigger. The authorization half.
# A FIDUCIARY agent may dispatch; a READ_ONLY agent may corroborate and never
# more, whatever its claim's own ceiling says.
PROFILE_SEVERITY_CAP: dict[TrustProfile, Severity] = {
    TrustProfile.FIDUCIARY: Severity.DISPATCHABLE,
    TrustProfile.TRANSACTIONAL: Severity.ACTIONABLE,
    TrustProfile.READ_ONLY: Severity.CORROBORATING,
    TrustProfile.UNTRUSTED: Severity.INFORMATIONAL,
}


@dataclass(frozen=True)
class VerifierPolicy:
    """Who this verifier is, and what it will accept."""

    audience: str
    """Our own ANSName. A claim addressed elsewhere is refused. Battery #6."""

    target: str
    """The submission endpoint proofs must bind to. Battery's `htu`."""

    skew: timedelta = DEFAULT_SKEW


@dataclass
class VerificationOutcome:
    """What the verifier decided, and every check it ran getting there."""

    decision: VerificationDecision
    reason: str
    checks: list[VerificationCheck] = field(default_factory=list)
    granted_severity: Severity = Severity.INFORMATIONAL
    will_be_spoken: bool = False


class ClaimVerifier:
    """Verifies one claim at a time against a trust store and a replay cache."""

    def __init__(
        self,
        policy: VerifierPolicy,
        trust: TrustStore,
        replay: ReplayCache | None = None,
    ) -> None:
        self._policy = policy
        self._trust = trust
        # `is None`, not `or`. ReplayCache defines __len__, so an empty cache is
        # falsy, and `replay or ReplayCache()` silently swapped an injected
        # shared cache for a private throwaway one. That is the exact failure
        # ANS-6 7.6 warns about under "shared scope behind load balancers": a
        # proof replays cleanly against any replica holding its own cache.
        self._replay = ReplayCache() if replay is None else replay

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _reject(code: RejectionCode, check: str, detail: str) -> VerificationRejected:
        return VerificationRejected(code, check, detail)

    # ---------------------------------------------------------------- the entry

    def verify(
        self,
        raw_claim: bytes,
        raw_proof: bytes,
        *,
        now: datetime | None = None,
        dispatched_incidents: frozenset[str] = frozenset(),
        expected_incident_id: str | None = None,
        expected_nonce: str | None = None,
    ) -> VerificationOutcome:
        """Verify a claim. Raises VerificationRejected, or returns an outcome.

        `dispatched_incidents` is incident lifecycle state. A claim naming an
        incident that already dispatched is spent, however fresh its proof.
        Battery #12, `replay_settled`.

        `expected_nonce` is the challenge this verifier issued for the fan-out
        the claim is answering. **Pass it always on the live path.** Omitting it
        verifies everything else and leaves the claim unbound to any particular
        question, which is precisely the property the nonce exists to remove;
        it is None only for the battery shapes that predate the challenge and
        for tests that are probing some other property.
        """
        now = now or utc_now()
        checks: list[VerificationCheck] = []

        def passed(name: str, detail: str) -> None:
            checks.append(VerificationCheck(name=name, passed=True, detail=detail))

        def fail(code: RejectionCode, name: str, detail: str) -> VerificationRejected:
            checks.append(VerificationCheck(name=name, passed=False, detail=detail))
            return self._reject(code, name, detail)

        # 1. Size bound, before parsing anything.
        if len(raw_claim) > MAX_ENVELOPE_BYTES or len(raw_proof) > MAX_ENVELOPE_BYTES:
            raise fail(
                RejectionCode.CLAIM_PARSE_ERROR,
                "size_bound",
                f"payload exceeds {MAX_ENVELOPE_BYTES} bytes; refused before parsing",
            )
        passed("size_bound", f"{len(raw_claim)}+{len(raw_proof)} bytes within bound")

        # 2. Strict parse. extra="forbid" on both models means a stripped legacy
        #    claim or one carrying smuggled members fails here. Battery #10.
        try:
            claim = SignedClaim.model_validate_json(raw_claim)
            proof = PossessionProof.model_validate_json(raw_proof)
        except ValidationError as exc:
            raise fail(
                RejectionCode.CLAIM_PARSE_ERROR,
                "strict_parse",
                f"envelope does not match the current schema: {exc.error_count()} error(s)",
            ) from exc
        env = claim.envelope
        passed("strict_parse", "envelope and proof parsed under the closed schema")

        # 3. Schema version. Refuse what we do not understand rather than
        #    reading it charitably. Five agents at different build stages is the
        #    ordinary reason this fires, not an attack.
        if env.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "schema_version",
                f"schema {env.schema_version!r} is not supported by this verifier",
            )
        passed("schema_version", f"schema {env.schema_version}")

        # 4. Algorithm is pinned. One accepted algorithm, no negotiation.
        if claim.algorithm != "Ed25519":
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "algorithm",
                f"algorithm {claim.algorithm!r} is not accepted; only Ed25519",
            )
        passed("algorithm", "Ed25519")

        # 5. Issuer must be a registered agent. Unknown key is a refusal, never
        #    an unknown-therefore-allow. Battery #11.
        agent = self._trust.lookup(env.issuer)
        if agent is None:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "known_issuer",
                f"{env.issuer!r} is not a registered agent, or is currently suppressed",
            )
        passed("known_issuer", f"{env.issuer} registered, cert {agent.certificate_version}")

        # 6. Signature over the canonical envelope. Battery #2, #3, #9.
        #    Nothing below this line reads a field that was not covered.
        if not self._signature_ok(agent.public_key, claim.signature, canonicalize(env.model_dump(mode="json"))):
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "claim_signature",
                "signature does not verify over the canonical envelope",
            )
        passed("claim_signature", "verified over canonicalized envelope")

        # --- Everything below refuses claims whose signature is perfectly good.

        # 7. Proof of possession: self-consistent, bound to this submission, and
        #    presented by the key the envelope names. Battery #8.
        self._verify_proof(proof, env, now, expected_nonce, passed, fail)

        # 8. Bindings. Audience, incident, zone, freshness. Battery #5, #6, #7.
        if env.audience != self._policy.audience:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "audience_binding",
                f"claim is addressed to {env.audience!r}, not to {self._policy.audience!r}",
            )
        passed("audience_binding", f"addressed to {env.audience}")

        if expected_incident_id is not None and env.incident_id != expected_incident_id:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "incident_binding",
                f"claim was issued for incident {env.incident_id!r}, presented against {expected_incident_id!r}",
            )
        passed("incident_binding", f"bound to incident {env.incident_id}")

        if env.incident_id in dispatched_incidents:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "incident_lifecycle",
                f"incident {env.incident_id!r} has already dispatched; the authorization is spent",
            )
        passed("incident_lifecycle", "incident is open")

        if env.expires_at <= now:
            raise fail(
                RejectionCode.CLAIM_REJECTED,
                "claim_freshness",
                f"claim expired at {env.expires_at.isoformat()}",
            )
        passed("claim_freshness", f"valid until {env.expires_at.isoformat()}")

        # 9. Authorization. The profile caps what this agent may trigger,
        #    independently of what the claim asks for and of how valid its
        #    signature is. Battery #4.
        cap = PROFILE_SEVERITY_CAP[agent.profile]
        granted = env.severity_ceiling
        if SEVERITY_ORDER[env.severity_ceiling] > SEVERITY_ORDER[cap]:
            if agent.profile is TrustProfile.UNTRUSTED:
                raise fail(
                    RejectionCode.CLAIM_REJECTED,
                    "profile_authorization",
                    f"{env.issuer} is UNTRUSTED; claim discarded and not relayed",
                )
            # Not a rejection: a downgrade, stated. A READ_ONLY agent asking to
            # dispatch corroborates instead. The claim survives, its authority
            # does not.
            granted = cap
            checks.append(
                VerificationCheck(
                    name="profile_authorization",
                    passed=True,
                    detail=(
                        f"claim requested {env.severity_ceiling.value} but {agent.profile.value} "
                        f"caps at {cap.value}; granted {cap.value}"
                    ),
                )
            )
        else:
            passed(
                "profile_authorization",
                f"{agent.profile.value} permits {env.severity_ceiling.value}",
            )

        # 10. Spend the proof. Last, and only now. ANS-6 7.6.
        try:
            self._replay.remember(proof.proof_id, now)
        except ReplayCacheSaturated as exc:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "replay_cache",
                f"fail-closed: {exc}",
            ) from exc
        passed("replay_record", "proof spent; further presentations will be refused")

        decision = PROFILE_DECISION[agent.profile]
        return VerificationOutcome(
            decision=decision,
            reason=(
                f"verified against {env.issuer} "
                f"(cert {agent.certificate_version}, profile {agent.profile.value}); "
                f"granted {granted.value}"
            ),
            checks=checks,
            granted_severity=granted,
            will_be_spoken=decision
            in (VerificationDecision.ASSERTED, VerificationDecision.ATTRIBUTED),
        )

    # ------------------------------------------------------------------ pieces

    @staticmethod
    def _signature_ok(key: Ed25519PublicKey, signature_b64: str, message: bytes) -> bool:
        """Verify, converting every failure into False.

        Battery #9 flips two bytes of a signature and requires a clean rejection
        rather than a thrown exception. A verifier that throws mid-incident is a
        worse outcome than one that refuses, so malformed base64, wrong-length
        signatures and invalid signatures all land in the same place.
        """
        try:
            key.verify(b64u_decode(signature_b64), message)
        except (InvalidSignature, ValueError, TypeError):
            return False
        return True

    def _verify_proof(
        self,
        proof: PossessionProof,
        env: ClaimEnvelope,
        now: datetime,
        expected_nonce: str | None,
        passed,
        fail,
    ) -> None:
        """Proof of possession. The DPoP analogue, ANS-6 Method B."""
        # Key the presenter claims, and its thumbprint.
        try:
            presenter = Ed25519PublicKey.from_public_bytes(b64u_decode(proof.public_key))
        except (ValueError, TypeError) as exc:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_key_parse",
                "presenter public key is not a valid Ed25519 key",
            ) from exc

        # Key binding, checked *before* any signature work so a swapped key
        # fails closed rather than verifying under the attacker's own key.
        # Battery #8.
        if key_thumbprint(presenter) != env.proof_key_thumbprint:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_key_binding",
                "proof is signed by a different key than the envelope names",
            )
        passed("proof_key_binding", "proof key matches the envelope thumbprint")

        # Proof signature, over the proof minus its own signature.
        body = proof.model_dump(mode="json")
        body.pop("signature", None)
        if not self._signature_ok(presenter, proof.signature, canonicalize(body)):
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_signature",
                "possession proof signature does not verify",
            )
        passed("proof_signature", "verified")

        # Challenge binding. The nonce this verifier issued for the fan-out this
        # claim is answering, and the reason the mesh is pull-only: a claim is
        # bound to a question we asked, not to a moment the producer chose.
        #
        # A mismatch is refused rather than downgraded. An agent answering a
        # challenge we did not issue is either replaying a claim prepared for a
        # different fan-out or was never asked at all, and neither is something
        # a dispatcher should hear.
        if expected_nonce is not None and proof.nonce != expected_nonce:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_nonce",
                (
                    f"proof answers challenge {proof.nonce!r}; this verifier issued "
                    f"{expected_nonce!r}. The claim was not produced for the question asked."
                ),
            )
        passed(
            "proof_nonce",
            f"answers challenge {proof.nonce}"
            if expected_nonce is not None
            else f"carries challenge {proof.nonce}; verifier issued none to check it against",
        )

        # Submission binding. `htm` / `htu`.
        if proof.target != self._policy.target:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_target",
                f"proof binds {proof.target!r}, submitted to {self._policy.target!r}",
            )
        passed("proof_target", proof.target)

        # Content binding: the proof covers this exact envelope, so a valid
        # proof cannot be lifted onto a different claim.
        digest = b64u_encode(hashlib.sha256(canonicalize(env.model_dump(mode="json"))).digest())
        if proof.content_digest != digest:
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_content_digest",
                "proof does not cover the envelope it accompanies",
            )
        passed("proof_content_digest", "proof covers this envelope")

        # Freshness.
        if abs((now - proof.issued_at).total_seconds()) > self._policy.skew.total_seconds():
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_freshness",
                f"proof issued at {proof.issued_at.isoformat()} is outside the acceptance window",
            )
        passed("proof_freshness", "within skew")

        # Replay. Checked here, recorded at the very end. Battery #1.
        if self._replay.seen(proof.proof_id, now):
            raise fail(
                RejectionCode.PROOF_REJECTED,
                "proof_replay",
                f"proof {proof.proof_id!r} has already been spent",
            )
        passed("proof_replay", "proof not previously seen")
