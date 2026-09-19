"""The one canonical hash used by every tamper-evident chain in this service.

There were two implementations of this before: `store.py::_hash_entry` for the
read-time replay assembly, and `agents/replay::_hash` for the agent's own chain.
Two canonical forms that must agree by convention will eventually disagree by
accident, and a chain that disagrees with itself looks exactly like a chain that
was tampered with. So there is one function, and both callers use it.

Canonical means `sort_keys=True` with a fixed separator: two processes
serializing the same entry differently must not produce different hashes.
"""

from __future__ import annotations

import hashlib
import json

#: The first link. A fixed constant means two independent recordings of the same
#: incident produce comparable roots rather than merely self-consistent ones.
GENESIS = "0" * 64


def canonical(payload: object) -> str:
    """The exact bytes a hash is taken over. Exposed so a verifier can print them."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def entry_hash(body: dict[str, object], prev_hash: str | None) -> str:
    """SHA-256 over the canonical JSON of `{"prev": ..., "entry": ...}`.

    `prev_hash` is `None` for the first entry rather than GENESIS, because that
    is the shape `store.build_replay` already emits and the iOS app already
    decodes. GENESIS is what `agents/replay` uses for the same position; the two
    are reconciled at the boundary, not here.
    """
    return hashlib.sha256(
        canonical({"prev": prev_hash, "entry": body}).encode("utf-8")
    ).hexdigest()
