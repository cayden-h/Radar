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

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.shutter.grant import GrantEnvelope, sign_grant
from agents.shutter.refusal import GrantRefused
from agents.shutter.shutter import Attestation, Shutter

if TYPE_CHECKING:  # pragma: no cover
    import httpx

logger = logging.getLogger(__name__)

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


class A2AShutterClient:
    """A `ShutterClient` that reaches the real `shutter` over its published `/a2a`.

    The transport `LocalShutterClient` warned about. Everything it does, the
    in-process client also did - challenge, sign, present, handle the refusal -
    but over HTTP to a separately registered agent, which is the architecture
    rather than a stand-in for it.

    **Two round trips, and they cannot be collapsed.** `shutter` issues the
    nonce, because the verifier always holds the nonce; a grant bound to a nonce
    master picked would prove only that master can pick numbers. On a LAN the
    extra trip costs under a millisecond against an 800ms budget.

    A refusal is an outcome, not an error. `shutter` answers one with a *result*
    carrying a signed refusal observation bound to the nonce it refused, never a
    JSON-RPC error, so this returns `None` and the record `shutter` produced is
    the thing that matters. Master's job here is to not move on.
    """

    def __init__(
        self,
        base_url: str,
        *,
        key: Ed25519PrivateKey,
        issuer: str,
        timeout_s: float = 3.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/a2a"
        self._key = key
        self._issuer = issuer
        self._timeout = timeout_s
        #: Every nonce this client has spent, so a test can prove none was reused.
        self.nonces_used: list[str] = []
        #: Why the last request produced no attestation. Read by master's own
        #: reporting, because "the shutter refused" and "the shutter could not be
        #: reached" are different facts and collapsing them would hide the more
        #: interesting one.
        self.last_detail: str | None = None

    def request(self, *, action: str, reason: str) -> Attestation | None:
        import httpx

        try:
            with httpx.Client(timeout=self._timeout) as client:
                nonce = self._challenge(client)
                if nonce is None:
                    return None
                self.nonces_used.append(nonce)

                now = datetime.now(timezone.utc)
                envelope = GrantEnvelope(
                    nonce=nonce,
                    issuer=self._issuer,
                    action=action,
                    # Recorded, not trusted. It goes into the sealed record so an
                    # investigator can follow the chain backwards; nothing
                    # downstream reads it as authorization.
                    reason=reason,
                    issued_at=now,
                    expires_at=now + GRANT_TTL,
                )
                # The grant crosses as the opaque string `sign_grant` produced.
                # Nothing here parses or re-serializes it: `shutter` verifies the
                # signature over exactly these bytes, and any reformatting looks
                # exactly like tampering.
                result = self._call(
                    client,
                    "shutter.open",
                    {"grant": sign_grant(self._key, envelope).decode()},
                )
        except Exception as exc:  # noqa: BLE001 - see below
            # Broad on purpose. This runs inside master's tick, which must not
            # die of a shutter being unplugged: an unreachable shutter is a
            # lens that stayed covered, which is the safe outcome.
            self.last_detail = f"shutter unreachable: {exc}"
            logger.warning("shutter unreachable (%s). The lens is unchanged.", exc)
            return None

        if result is None:
            return None
        if result.get("refused"):
            self.last_detail = (
                f"{result.get('refusal', 'refused')}: {result.get('detail', '')}".strip()
            )
            logger.warning(
                "shutter refused a grant: %s. The lens is still covered.", self.last_detail
            )
            return None

        raw = result.get("attestation")
        if not isinstance(raw, str):
            self.last_detail = "shutter answered without an attestation"
            return None
        self.last_detail = None
        return Attestation.model_validate_json(raw)

    def _challenge(self, client: "httpx.Client") -> str | None:
        result = self._call(client, "shutter.challenge", {})
        if result is None:
            return None
        nonce = result.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            self.last_detail = "shutter would not issue a nonce"
            return None
        return nonce

    def _call(
        self, client: "httpx.Client", method: str, params: dict
    ) -> dict | None:
        response = client.post(
            self._url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            self.last_detail = f"{method} errored: {body['error']}"
            return None
        result = body.get("result")
        return result if isinstance(result, dict) else None
