"""Replay cache. Single-use proofs, fail closed, and recorded last.

ANS-6 section 7.6, followed closely because the ordering rule in it is easy to
get backwards and expensive to get wrong:

    Record after trust. The jti is committed only after the full pipeline,
    including the status-token binding, succeeds. Recording earlier lets anyone
    with a self-signed certificate flood the bounded cache and fail-close
    authentication for every legitimate caller.

On this system that failure is a denial of service against a 911 call, so the
ordering is enforced by the API: `remember()` is a separate call the verifier
makes last, and `seen()` never mutates.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timedelta

from hawkeye_backend.models.common import utc_now


class ReplayCacheSaturated(RuntimeError):
    """The cache is full. Fail closed: refuse rather than admit a possible replay."""


class ReplayCache:
    """Bounded, time-windowed store of spent proof ids.

    Stores a digest of each id rather than the id, per RFC 9449 section 11.1, so
    a cache bounded in entry count is also bounded in bytes.
    """

    def __init__(self, max_entries: int = 8192, retention: timedelta | None = None) -> None:
        self._entries: OrderedDict[bytes, datetime] = OrderedDict()
        self._max = max_entries
        # skew + grace. A small grace keeps an id stored slightly past the
        # freshness window so no gap opens between the two checks.
        self._retention = retention or timedelta(seconds=125)

    @staticmethod
    def _digest(proof_id: str) -> bytes:
        return hashlib.sha256(proof_id.encode("utf-8")).digest()

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - self._retention
        while self._entries:
            key, stored_at = next(iter(self._entries.items()))
            if stored_at > cutoff:
                break
            self._entries.popitem(last=False)

    def seen(self, proof_id: str, now: datetime | None = None) -> bool:
        """Has this proof been spent? Never mutates."""
        now = now or utc_now()
        self._evict_expired(now)
        return self._digest(proof_id) in self._entries

    def remember(self, proof_id: str, now: datetime | None = None) -> None:
        """Spend a proof. Called last, only after every other check passed."""
        now = now or utc_now()
        self._evict_expired(now)
        if len(self._entries) >= self._max:
            # Fail closed. Never silently drop an entry to make room, because
            # the dropped entry is exactly the one an attacker wants forgotten.
            raise ReplayCacheSaturated(
                f"replay cache at capacity ({self._max}); refusing rather than admitting a possible replay"
            )
        self._entries[self._digest(proof_id)] = now

    def __len__(self) -> int:
        return len(self._entries)
