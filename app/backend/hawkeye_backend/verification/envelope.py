"""The claim envelope, and the proof of possession that accompanies it.

Modelled on the RFC 9421 spending mandate the battery attacks, because the
analogy is exact: a scoped, signed, audience-bound, time-bound authorization
permitting an irreversible act. Field-by-field mapping, also in `docs/fraud-13.md`:

| Mandate field | Here                 | Why it exists                                  |
|---------------|----------------------|------------------------------------------------|
| `max_amount`  | `severity_ceiling`   | The most this claim may ever trigger           |
| audience      | `audience`           | *This* master, not any coordinator that listens |
| scope         | `zone_scope`         | A kitchen claim cannot justify a bedroom dispatch |
| `quote_id`    | `incident_id`        | Bound to this incident, not replayable into another |
| `jkt`         | `proof_key_thumbprint` | Only the holder of that key may present it   |
| nonce         | `claim_id` / `jti`   | Counted once, never twice                      |

Note what is *not* here: the dispatch address. It is bound at registration and
sealed, never carried in a claim. An agent that can change where a response is
sent is a swatting tool no matter how well the claim verifies. See `ans/CARD.md`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from hawkeye_backend.models.common import Source, utc_now


class Severity(StrEnum):
    """What a claim is allowed to trigger. The `max_amount` analogue.

    Ordered. A claim may trigger at or below its ceiling and never above it,
    which is the property battery #4 (`underpay_valid_sig`) exists to test: a
    genuinely authority-signed authorization presented for the wrong magnitude
    must still be refused.
    """

    INFORMATIONAL = "INFORMATIONAL"
    CORROBORATING = "CORROBORATING"
    ACTIONABLE = "ACTIONABLE"
    DISPATCHABLE = "DISPATCHABLE"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFORMATIONAL: 0,
    Severity.CORROBORATING: 1,
    Severity.ACTIONABLE: 2,
    Severity.DISPATCHABLE: 3,
}


class ClaimEnvelope(BaseModel):
    """The signed part. Every field here is covered by the signature.

    `model_config` forbids extra fields: a `superseded_format` claim carrying
    unknown members, or a legacy claim missing required ones, fails to parse
    rather than being read charitably. Battery #10.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(description="Envelope schema version. Unversioned claims are refused.")
    claim_id: str = Field(description="Unique per claim. Counted once toward corroboration, never twice.")
    issuer: str = Field(description="ANSName of the sensing agent that produced this claim.")
    audience: str = Field(description="ANSName of the master this claim is addressed to.")
    incident_id: str = Field(description="The incident this claim was produced for.")
    zone_scope: str = Field(description="Room-level zone the claim is about, e.g. 'main_bedroom'.")
    field: str = Field(description="Interior-state field asserted, e.g. 'biometrics.respiration'.")
    value: str = Field(description="The asserted value.")
    severity_ceiling: Severity = Field(description="The most this claim may ever trigger.")
    source: Source = Field(
        default=Source.AGENT_INFERENCE,
        description=(
            "What physically produced the reading this claim asserts.\n\n"
            "**Signed, because the honesty rule is worth exactly as much as its "
            "weakest carrier.** `Source` is the field the app renders a "
            "'simulated' badge from, and before this lived in the envelope it "
            "did not survive the wire: the transport rebuilt every arriving "
            "claim with `agent-inference`, so a fixture video and a real camera "
            "reached `master` indistinguishable from one another. A limit that "
            "is dropped in transit is not a limit.\n\n"
            "Inside the signature rather than beside it, so a claim cannot be "
            "relabelled measured in flight. Defaults to `agent-inference`, which "
            "classes as DERIVED: a producer that says nothing about its source "
            "is never read as having measured anything."
        ),
    )
    proof_key_thumbprint: str = Field(description="Thumbprint of the key that must present the proof.")
    issued_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(description="After this, the claim is stale and refused.")


class SignedClaim(BaseModel):
    """An envelope plus the issuer's detached signature over its canonical form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope: ClaimEnvelope
    algorithm: str = Field(default="Ed25519", description="Only Ed25519 is accepted.")
    signature: str = Field(description="base64url, unpadded, over canonicalize(envelope).")


class PossessionProof(BaseModel):
    """Proof the presenter holds the key the envelope names. The DPoP analogue.

    Separate from the claim signature on purpose. The envelope proves *who wrote
    the claim*; this proves *who is presenting it right now*. Battery #8
    (`wrong_dpop_key_attack`) is the case where those two differ.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str = Field(description="The `htm` analogue: how the claim is being submitted.")
    target: str = Field(description="The `htu` analogue: the submission endpoint, normalized.")
    proof_id: str = Field(description="The `jti` analogue. Single use.")
    nonce: str = Field(
        description=(
            "Server-supplied challenge, the DPoP `nonce` analogue. **The verifier issues "
            "this, not the presenter**, and that asymmetry is the whole point of it: a "
            "claim is bound to a specific question this master asked at a specific "
            "moment, rather than to a moment the producer chose for itself.\n\n"
            "It is what makes the mesh pull-only rather than push. An agent cannot "
            "produce a usable claim unbidden, so a compromised sensing agent cannot "
            "prepare a batch of plausible claims in advance and fire them at an incident; "
            "every one has to answer a challenge it could not have predicted.\n\n"
            "Required, never optional. A proof with an empty nonce is refused, because "
            "'the verifier did not ask for one' and 'the presenter omitted it' must not "
            "be the same wire representation."
        ),
        min_length=1,
    )
    issued_at: datetime = Field(default_factory=utc_now)
    content_digest: str = Field(description="base64url SHA-256 over canonicalize(envelope).")
    public_key: str = Field(description="base64url raw Ed25519 public key of the presenter.")
    signature: str = Field(description="base64url over canonicalize(proof minus signature).")
