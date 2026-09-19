"""base64url without padding, and key thumbprints. Shared by every other module."""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    """Strict decode. Rejects padding errors rather than guessing.

    Battery #9 (`corrupt_jws_attack`) flips the last two bytes of a signature and
    requires a clean rejection rather than a thrown exception, so every caller
    wraps this and converts failure into a refusal.
    """
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def key_thumbprint(key: Ed25519PublicKey) -> str:
    """Stable identifier for a public key. The `jkt` analogue."""
    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return b64u_encode(hashlib.sha256(raw).digest())
