"""Claim-envelope verification: the defence `agents/master` runs on every claim.

Why this package exists, stated once so it is not re-litigated:

`fraud.webmesh.ai` publishes a battery of thirteen attacks. It **cannot be
pointed at us** - verified 2026-09-19 against its MCP endpoint, where
`run_battery` and all thirteen attack tools take no target parameter and the
target is hardwired to `supplier.webmesh.ai`. See `docs/fraud-13.md`.

That does not make the battery irrelevant. It is a reference implementation of a
threat model, and every structural property it probes has a direct analogue here:

    A spending mandate is to money what a verified sensing claim is to an
    armed response.

Both are a scoped, signed, audience-bound, time-bound authorization that permits
an irreversible act. So we implement the thirteen shapes ourselves, against our
own envelope, and `tests/test_battery.py` is the local battery.

The battery is thirteen ways of asking one question:

    Does this implementation treat a valid signature as authorization?

Ten of the thirteen pass only if the answer is no. `verifier.py` is written so
the answer is no.

Wire-level design follows ANS-6 Method B (`ans/CARD.md`) rather than inventing a
scheme, because the track owner's own verifier will eventually read this.
"""

from hawkeye_backend.verification.envelope import ClaimEnvelope, PossessionProof, SignedClaim
from hawkeye_backend.verification.errors import RejectionCode, VerificationRejected
from hawkeye_backend.verification.replay import ReplayCache
from hawkeye_backend.verification.trust import KnownAgent, TrustStore
from hawkeye_backend.verification.verifier import ClaimVerifier, VerifierPolicy

__all__ = [
    "ClaimEnvelope",
    "ClaimVerifier",
    "KnownAgent",
    "PossessionProof",
    "RejectionCode",
    "ReplayCache",
    "SignedClaim",
    "TrustStore",
    "VerificationRejected",
    "VerifierPolicy",
]
