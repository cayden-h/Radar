"""The grant: what `master` signs, and the only thing that moves the shield.

A grant is not a claim. A claim says what is true and `hawkeye_backend`'s
`ClaimEnvelope` carries it; a grant says *do this*, and the difference matters
enough to have its own envelope. A claim that fails verification is discarded
and the world is unchanged. A grant that fails verification is an attempt to
uncover a camera in someone's living room.

Everything here mirrors the rules the claim envelope already lives by, because
they are the same attacks pointed at a different target:

- **The bytes that are signed are the bytes that are verified.** A grant crosses
  the wire as an opaque JSON string, never a nested object. Any layer that
  parses and re-serializes breaks every signature, and the failure looks exactly
  like tampering.
- **Canonicalize through the model**, not by hand. Hand-built dicts serialize
  datetimes differently from pydantic and produce a mismatch indistinguishable
  from an attack. That is battery probe #13.
- **`extra="forbid"`**, so a grant carrying smuggled members is a parse failure
  rather than a field somebody later reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.verification.b64 import b64u_encode
from hawkeye_backend.verification.canonical import canonicalize
from pydantic import BaseModel, ConfigDict, Field

#: Envelope schema this grant speaks. `shutter` refuses what it does not
#: understand rather than reading it charitably.
SCHEMA_VERSION = "1.0"

#: The two things a shield can be told to do. There is no third value, and an
#: unknown one is a refusal rather than a default.
Action = Literal["open", "close"]

#: The same two, as a set, for the check that runs on the wire value. The
#: envelope types `action` as a plain string on purpose: a pydantic Literal
#: would reject an unknown action at parse time as "malformed", and the record
#: should say `unknown_action`, which is a different and more interesting fact.
ACTIONS: frozenset[str] = frozenset({"open", "close"})


class GrantEnvelope(BaseModel):
    """What `master` signs. Every field here is covered by the signature."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION

    nonce: str = Field(
        min_length=1,
        description=(
            "The challenge `shutter` just issued. Required and non-empty: 'the verifier "
            "did not ask for one' and 'the presenter omitted it' must not share a wire "
            "representation."
        ),
    )

    issuer: str = Field(
        description=(
            "`master`'s ANSName. Checked against the trust card `shutter` fetched, never "
            "against a configured list of keys that are allowed."
        )
    )

    action: str = Field(description="`open` or `close`. Anything else is a refusal.")

    reason: str = Field(
        description=(
            "What justified this grant: a motion claim id for `open`, a vision verdict "
            "id for `close`. **Recorded, not trusted** - it goes into the sealed record "
            "so an investigator can follow the chain backwards, and nothing here reads "
            "it as authorization."
        )
    )

    incident_id: str | None = Field(
        default=None,
        description=(
            "Null when the shutter moves on motion or on a vision verdict, which is the "
            "normal case. Set when a human raised the incident first, or closed the lens "
            "from the app."
        ),
    )

    issued_at: datetime
    expires_at: datetime = Field(
        description=(
            "Seconds, not minutes. A grant that outlives the situation that produced it "
            "is a replay waiting to happen."
        )
    )


class SignedGrant(BaseModel):
    """A grant and the signature over its canonical form."""

    model_config = ConfigDict(extra="forbid")

    envelope: GrantEnvelope
    algorithm: str = "Ed25519"
    signature: str


def sign_grant(key: Ed25519PrivateKey, envelope: GrantEnvelope) -> bytes:
    """`master`'s half. Returns the exact bytes to put on the wire."""
    signature = b64u_encode(key.sign(canonicalize(envelope.model_dump(mode="json"))))
    return SignedGrant(envelope=envelope, signature=signature).model_dump_json().encode()
