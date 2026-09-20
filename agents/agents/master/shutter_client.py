"""How master asks the shield to move.

A grant is not a claim. A claim says what is true; a grant says *do this*. A
claim that fails verification is discarded and the world is unchanged, and a
grant that fails verification is an attempt to move a physical object that did
not succeed. `agents/shutter/grant.py` states that distinction and this is the
other end of it.

**The nonce is not cached.** `shutter` issues a challenge and the grant is bound
to it. Asking for a fresh one per grant is what makes a replayed grant
detectable; holding one open across two grants would give an attacker a window
in which a captured grant is still live.

`LocalShutterClient` talks to a `Shutter` in this process. It is the same
category of stand-in as `LocalMesh` and carries the same warning: an in-process
call verifies the signature but not the transport, and the architecture is two
independently registered agents over ANS. It exists so master's decision logic
can be written and tested before that transport is wired, and it must not
survive into the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.shutter.grant import GrantEnvelope, sign_grant
from agents.shutter.refusal import GrantRefused
from agents.shutter.shutter import Attestation, Shutter

#: How long a grant stays valid. Seconds, not minutes, per `grant.py`: a grant
#: that outlives the situation that produced it is a replay waiting to happen.
GRANT_TTL = timedelta(seconds=10)


class ShutterClient(Protocol):
    """Whatever moves the shield on master's behalf."""

    def request(self, *, action: str, reason: str) -> Attestation | None:
        """Ask for a move. `None` when the shutter refused."""
        ...


class LocalShutterClient:
    """In-process `ShutterClient`. Signs real grants against the real gate."""

    def __init__(self, shutter: Shutter, *, key: Ed25519PrivateKey, issuer: str) -> None:
        self._shutter = shutter
        self._key = key
        self._issuer = issuer
        #: Every nonce this client has spent, so a test can prove none was reused.
        self.nonces_used: list[str] = []

    def request(self, *, action: str, reason: str) -> Attestation | None:
        nonce = self._shutter.challenge()
        self.nonces_used.append(nonce)

        now = datetime.now(timezone.utc)
        envelope = GrantEnvelope(
            nonce=nonce,
            issuer=self._issuer,
            action=action,
            # Recorded, not trusted. It goes into the sealed record so an
            # investigator can follow the chain backwards; nothing downstream
            # reads it as authorization.
            reason=reason,
            issued_at=now,
            expires_at=now + GRANT_TTL,
        )

        try:
            return self._shutter.open(sign_grant(self._key, envelope))
        except GrantRefused:
            # A refusal is an outcome, not an error. `shutter` has already
            # produced a signed refusal bound to the nonce, which is the record
            # that matters; master's job here is only to not move on.
            return None
