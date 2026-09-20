"""The nonces `shutter` issues, and the one place they are spent.

This is the inversion. Everywhere else in the mesh `master` asks and sensing
agents answer, so `master` holds the nonce and a claim is bound to the question
that provoked it. Here `master` is the one asking for something to happen, so
**`shutter` holds the nonce**. The invariant the pull-only rule was protecting
is "the verifier issues the challenge", and it survives the inversion intact.

Two properties, and both are refusals rather than errors:

- **A nonce is spent by the first grant that presents it**, whether or not that
  grant went on to verify. Spending on presentation rather than on success is
  deliberate: a nonce released back into the pool by a failed attempt is an
  oracle, and an attacker who can fail cheaply gets unlimited attempts at one
  challenge.
- **A nonce expires in seconds.** A challenge that outlives the situation that
  provoked it is a replay window, and the situation here is someone walking
  through a door.

Never issued, already spent, and expired all collapse to one answer, because
`shutter` must not tell a caller which of the three it was. That distinction is
an oracle too.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from hawkeye_backend.models.common import utc_now

#: How long a challenge is good for. The round trip it covers is sub-millisecond
#: on localhost and a few tens of milliseconds over the wire; ten seconds is
#: already generous by three orders of magnitude.
DEFAULT_TTL = timedelta(seconds=10)


class ChallengeBook:
    """Nonces issued but not yet spent."""

    def __init__(self, *, ttl: timedelta = DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._open: dict[str, datetime] = {}

    def issue(self, *, now: datetime | None = None) -> str:
        """A fresh nonce. 128 bits, because it must be unguessable, not unique."""
        now = now or utc_now()
        nonce = f"shut-{secrets.token_urlsafe(16)}"
        self._open[nonce] = now + self._ttl
        return nonce

    def spend(self, nonce: str, *, now: datetime | None = None) -> bool:
        """Consume a nonce.

        False if it was never issued, is already spent, or has expired. One
        answer for all three on purpose: which one it was is information a
        caller has no business learning.
        """
        now = now or utc_now()
        expires_at = self._open.pop(nonce, None)
        return expires_at is not None and now < expires_at
