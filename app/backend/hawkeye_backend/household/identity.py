"""Turning an observed network address into something safe to store.

The roster never holds a raw MAC. It holds an HMAC of one under a per-site salt,
so matching still works and a stolen roster is not a plaintext list of which
devices visit which house.

HMAC rather than a bare SHA-256 because the input space is trivially small: the
whole 48-bit MAC space is enumerable, and a known vendor prefix cuts it far
below that. Against an unkeyed digest, recovering every address in a stolen
roster is minutes of work.

**The salt today is `settings.site_id`, which is not a secret.** It is in the
config and it appears in logs. So this raises the cost of reversing a stolen
roster from trivial to "enumerate 2^48 HMACs", and it does not make it hard for
someone who has both the roster and the config. That is worth having and it is
not worth overstating.

What it should be, when someone takes this past the demo: a 256-bit random
secret generated at hub enrollment, stored apart from the roster, and rotated
by re-hashing. Until then this is the honest description rather than the
flattering one.
"""

from __future__ import annotations

import hashlib
import hmac


class MalformedAddress(ValueError):
    """The thing handed over was not a network address.

    Raised rather than hashed. A malformed address hashes to a perfectly valid
    looking digest and produces a device that can never match, which is a roster
    that looks populated and recognises nobody. The producer bug is only
    catchable here, while the real input still exists.
    """


def _normalise(address: str) -> str:
    """One canonical form, because routers report several.

    `A4:83:E7:2C:19:91`, `a4-83-e7-2c-19-91` and `a483e72c1991` are one device,
    and hashing them differently would silently fail to match a remembered guest.
    """
    hex_only = "".join(c for c in address.lower() if c in "0123456789abcdef")
    if len(hex_only) != 12:
        raise MalformedAddress(
            f"expected 12 hex characters of MAC address, got {len(hex_only)} from {address!r}"
        )
    return hex_only


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
    head = normalised[:2]
    return f"{head}:..:{hash_identifier(address, salt)[:4]}"
