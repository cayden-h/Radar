"""Building master's trust store from the agents' own published cards.

This is the difference between a mesh that is **discovered** and one that is
**configured**. A hardcoded list of public keys would verify signatures
perfectly well and would prove nothing about identity: the keys would be trusted
because we typed them in.

Fetching them from each agent's published trust card ties acceptance to the same
document `agent.webmesh.ai verify_agent` reads, the same document whose hash is
sealed at registration, and the same document `card_drift_watch` monitors. One
artifact, three consumers, and no private channel by which we could trust
something the public surface does not say.

It also gives drift detection almost for free: master records the card
fingerprint it fetched, and a card that changes without a re-registration is
exactly the signature of a compromised agent.

**What is not here yet:** the trust card's `keys[].x5c` chain, because no
certificates exist until `ans/` has a registration. Until then the raw public
key in `keys[].x`is what gets loaded, and that is Bronze at best. The loader is
written so adding chain validation is a check inside `_agent_from_card`, not a
restructuring.
"""

from __future__ import annotations

import logging

import httpx
from hawkeye_backend.models.verification import TrustProfile
from hawkeye_backend.verification.b64 import b64u_decode
from hawkeye_backend.verification.trust import KnownAgent, TrustStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agents.core.cards import TRUST_CARD_PATH
from agents.core.identity import BY_SLUG
from agents.core.transport import Peer

logger = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """A peer's card could not be fetched or does not say what it must."""


def _agent_from_card(card: dict, *, profile: TrustProfile) -> KnownAgent:
    """One trust card to one entry in the store. Fail closed on anything missing."""
    ansname = card.get("ansName")
    keys = card.get("keys") or []
    if not ansname or not keys:
        raise DiscoveryError("trust card carries no ansName or no keys")
    entry = keys[0]
    if entry.get("kty") != "OKP" or entry.get("crv") != "Ed25519":
        raise DiscoveryError(f"unsupported key type {entry.get('kty')}/{entry.get('crv')}")
    raw = entry.get("x")
    if not raw:
        raise DiscoveryError("trust card key has no public component")
    # TODO(ans): validate entry["x5c"] against the ANS private CA once
    # registration exists, and refuse a card whose chain does not resolve. Until
    # then this is Bronze: one trust channel, the card itself.
    return KnownAgent(
        ansname=ansname,
        public_key=Ed25519PublicKey.from_public_bytes(b64u_decode(raw)),
        profile=profile,
        certificate_version=str(card.get("version", "unknown")),
    )


def discover(
    peers: dict[str, Peer],
    *,
    timeout_s: float = 3.0,
    client: httpx.Client | None = None,
) -> tuple[TrustStore, dict[str, str]]:
    """Fetch every peer's trust card and build the store.

    Returns the store and the fingerprint master saw per agent, so a later
    refresh can notice drift rather than silently accepting a new key.

    A peer whose card cannot be fetched is **left out of the store**, which
    means its claims are refused as coming from an unregistered agent. That is
    the correct failure: an agent we cannot verify the identity of is not an
    agent we accept claims from, and a reachable-but-unverifiable agent is
    exactly what an impostor looks like.
    """
    owned = client or httpx.Client(timeout=timeout_s)
    store = TrustStore()
    fingerprints: dict[str, str] = {}
    try:
        for slug, peer in peers.items():
            identity = BY_SLUG.get(slug)
            if identity is None:
                logger.warning("skipping %s: not one of the five registered agents", slug)
                continue
            try:
                response = owned.get(f"{peer.base_url}{TRUST_CARD_PATH}")
                response.raise_for_status()
                card = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("no trust card for %s: %s. Its claims will be refused.", slug, exc)
                continue
            try:
                # TODO(ans): the profile is the roster's expectation, not a live
                # Trust Index lookup. Replace with a query against the Trust
                # Index, cached with a short TTL - a network call inside the
                # verification path is a hop that can be starved, which is the
                # same argument ans/CLAUDE.md makes for stapling the receipt.
                known = _agent_from_card(card, profile=identity.profile)
            except DiscoveryError as exc:
                logger.warning("%s published an unusable trust card: %s", slug, exc)
                continue
            if known.ansname != peer.ansname:
                # The card says it is somebody else. Refuse rather than trust
                # the card over our own expectation: this is the lookalike
                # hostname case, and the whole point is that the name is
                # anchored rather than self-asserted.
                logger.warning(
                    "%s published a card for %s; master expects %s. Refused.",
                    slug,
                    known.ansname,
                    peer.ansname,
                )
                continue
            store.register(known)
            fingerprints[slug] = known.thumbprint
            logger.info("registered %s as %s", slug, known.ansname)
    finally:
        if client is None:
            owned.close()
    return store, fingerprints
