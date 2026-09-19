"""Turning an observed network address into something safe to store.

The roster never holds a raw MAC. It holds an HMAC of one under a per-site salt,
so matching still works and a stolen roster is not a list of which devices visit
which house.

HMAC rather than a bare SHA-256 because the input space is small enough to
enumerate: the whole 48-bit MAC space is brute-forceable, and vendor prefixes cut
it far below that. A keyed hash makes the salt necessary to test a guess.
"""

from __future__ import annotations

import hashlib
import hmac


def _normalise(address: str) -> str:
    """One canonical form, because routers report several.

    `A4:83:E7:2C:19:91`, `a4-83-e7-2c-19-91` and `a483e72c1991` are one device,
    and hashing them differently would silently fail to match a remembered guest.
    """
    return "".join(c for c in address.lower() if c in "0123456789abcdef")


def hash_identifier(address: str, salt: str) -> str:
    """HMAC-SHA256 of a normalised address under the site salt. 64 hex chars."""
    return hmac.new(salt.encode(), _normalise(address).encode(), hashlib.sha256).hexdigest()


def fingerprint(address: str, salt: str) -> str:
    """A short label so a human can tell two phones in one room apart.

    The real first octet, then four hex of the hash. The octet is a vendor
    prefix rather than a device identity, and four hex is far too few to search,
    so this discloses essentially nothing while still being stable and readable.
    """
    normalised = _normalise(address)
    head = normalised[:2] if len(normalised) >= 2 else "??"
    return f"{head}:..:{hash_identifier(address, salt)[:4]}"
