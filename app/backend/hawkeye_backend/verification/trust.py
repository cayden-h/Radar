"""The trust store: which keys belong to which registered agent, and its profile.

Fail closed, always. Battery #11 (`unknown_key_mandate`) signs with a fresh key
absent from the authority's trust card and expects rejection. An unknown key is a
refusal, never an unknown-therefore-allow.

In production this is populated from each agent's ANS Trust Card (`keys[].x5c`,
see `ans/CARD.md`) and refreshed as cards are re-fetched. The shape here is
deliberately the shape a Trust Card gives you, so the live loader is a parser and
nothing above it changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from hawkeye_backend.models.verification import TrustProfile
from hawkeye_backend.verification.b64 import key_thumbprint


@dataclass(frozen=True)
class KnownAgent:
    """One registered agent, as the trust store knows it."""

    ansname: str
    public_key: Ed25519PublicKey
    profile: TrustProfile
    certificate_version: str
    """Version-bound certificate fingerprint recorded at registration.

    Code change means a new version means a new certificate. A claim presented
    under a version the store does not hold is drift, and drift is refused.
    """

    @property
    def thumbprint(self) -> str:
        return key_thumbprint(self.public_key)


class TrustStore:
    """Registered agents, keyed by ANSName. Unknown means refused."""

    def __init__(self, agents: list[KnownAgent] | None = None) -> None:
        self._agents: dict[str, KnownAgent] = {a.ansname: a for a in (agents or [])}
        self._suppressed: set[str] = set()

    def register(self, agent: KnownAgent) -> None:
        self._agents[agent.ansname] = agent

    def lookup(self, ansname: str) -> KnownAgent | None:
        """The agent, or None. None is a rejection at the call site, never a default."""
        if ansname in self._suppressed:
            return None
        return self._agents.get(ansname)

    def suppress(self, ansname: str, reason: str) -> None:
        """Stop accepting an agent's claims, reversibly.

        Mirrors ANS-5: the monitor reports, the RA revokes, and suppression
        precedes revocation. `master` suppresses and logs; it never tries to
        revoke a certificate mid-incident. See `ans/CLAUDE.md`.
        """
        self._suppressed.add(ansname)
        self.last_suppression_reason = reason

    def unsuppress(self, ansname: str) -> None:
        self._suppressed.discard(ansname)

    @property
    def suppressed(self) -> frozenset[str]:
        return frozenset(self._suppressed)
