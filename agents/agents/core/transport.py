"""The wire: A2A JSON-RPC, pull-only, with a server-issued challenge.

Settled 2026-09-19. Two decisions shape everything here.

## Pull, not push

`master` asks; sensing agents answer. Nothing is pushed.

The reason is not simplicity, it is binding strength. **With pull, master
controls the nonce**, so a claim is bound to a specific question asked at a
specific moment. With push the producer picks its own nonce and master can only
check it has not seen it before, which is strictly weaker: a compromised sensing
agent could prepare a batch of plausible claims in advance and fire them at an
incident. Under pull it cannot, because it cannot guess the challenge.

It also collapses two code paths into one. The steady-state tick and the
operator fan-out are the same mechanism, so the beat that matters in the demo is
exercised continuously rather than only during a call. The cost is up to one
second of detection latency, which is nothing against a
`people.respiration_lost` clock measured in minutes.

## A2A JSON-RPC, because that is what we published

Our cards declare `preferredTransport: JSONRPC` at `https://<host>/a2a`, and
`agent.webmesh.ai verify_agent` sends a **live A2A message** and reports the
credential we actually required. An agent whose card advertises an endpoint that
is not there fails the judge's own verifier on the surface we called our best
demo beat.

MCP is deliberately not here. All the webmesh.ai agents speak both, and ours
should eventually, but it is a second adapter over these same handlers and it
buys presentation rather than capability. Roadmap, not this weekend.

## The trap this file exists to avoid

`ClaimVerifier` verifies **bytes**. If the transport parses a claim into a dict
and re-serializes it anywhere in between, every signature breaks and the failure
looks exactly like tampering.

So claims cross the wire as **opaque JSON strings inside the JSON-RPC result**,
never as nested objects. The bytes that were signed are the bytes that are
verified. Verify first, parse second, never the reverse.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter
from hawkeye_backend.models.common import utc_now
from hawkeye_backend.verification import ClaimVerifier, VerificationRejected
from hawkeye_backend.verification.envelope import SignedClaim
from pydantic import BaseModel, Field, ValidationError

from agents.core.base import Agent
from agents.core.observations import AgentObservation, Assertion, Unknown
from agents.core.ports import FetchedObservation, TransportRejection
from agents.core.signing import ClaimSigner

logger = logging.getLogger(__name__)

#: The A2A method sensing agents answer. One method, because there is one
#: question: what do you have right now, for this challenge.
METHOD_OBSERVE = "hawkeye.observe"

#: Where claims are submitted, as the possession proof's `htu` binds it. A proof
#: bound to a different endpoint is refused, so this string is part of the
#: protocol and not a deployment detail.
CLAIM_TARGET_PATH = "/a2a"

#: Incident id used for steady-state fan-outs, when no incident is open.
#:
#: The claim is still uniquely bound, by the challenge rather than by this. A
#: sentinel here would be dangerous on its own - every steady-state claim
#: replayable into every other - which is precisely why the nonce was added to
#: the proof rather than leaning on this field.
STEADY_STATE = "steady-state"


def new_challenge() -> str:
    """A fresh nonce. 128 bits, because it must be unguessable, not merely unique."""
    return f"chal-{secrets.token_urlsafe(16)}"


# ------------------------------------------------------------------- the wire


class ObserveParams(BaseModel):
    """What master sends when it asks."""

    audience: str = Field(
        description="master's ANSName. A claim addressed elsewhere is refused."
    )
    nonce: str = Field(min_length=1, description="The challenge this fan-out issues.")
    incident_id: str = Field(default=STEADY_STATE)
    target: str = Field(description="Endpoint the possession proof must bind to.")


class SignedPairWire(BaseModel):
    """One claim on the wire. Both members are opaque JSON **strings**.

    Strings, not objects, and that is the whole point: a nested object would be
    re-serialized by the JSON layer and the signature would no longer verify
    over what arrives.
    """

    claim: str
    proof: str


class ObserveResult(BaseModel):
    """What a sensing agent answers with."""

    agent: str
    ansname: str
    observed_at: str
    healthy: bool
    note: str | None = None
    claims: list[SignedPairWire] = Field(default_factory=list)
    unknowns: list[dict[str, str]] = Field(default_factory=list)


# ------------------------------------------------------------- the server side


def a2a_router(
    agent: Agent,
    signer: ClaimSigner,
    *,
    extra: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
) -> APIRouter:
    """The `/a2a` endpoint every agent serves.

    Signs the agent's *current* observation against the challenge in the
    request. It does not compute anything on demand: the agent is already
    running continuously and `tick` has already happened, so this reports rather
    than triggers. An endpoint that ran the sensing logic on request would make
    an agent's output a function of who is asking, which is the opposite of what
    continuous operation is for.
    """
    router = APIRouter()
    extra = dict(extra or {})

    @router.post(CLAIM_TARGET_PATH)
    async def a2a(request: dict[str, Any]) -> dict[str, Any]:
        rpc_id = request.get("id")

        def error(code: int, message: str) -> dict[str, Any]:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": code, "message": message},
            }

        method = request.get("method")

        # An agent's own methods, on the same endpoint as `hawkeye.observe`,
        # because there is one `/a2a` per agent and it is the one the card
        # publishes. Only `shutter` has any: it is the one agent that takes an
        # order rather than answering a question.
        handler = extra.get(method) if isinstance(method, str) else None
        if handler is not None:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": handler(request.get("params") or {}),
            }

        if method != METHOD_OBSERVE:
            return error(-32601, f"unknown method {method!r}")
        try:
            params = ObserveParams.model_validate(request.get("params") or {})
        except ValidationError as exc:
            return error(-32602, f"invalid params: {exc.error_count()} error(s)")

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": observe(agent, signer, params).model_dump(),
        }

    return router


def observe(agent: Agent, signer: ClaimSigner, params: ObserveParams) -> ObserveResult:
    """The agent's current observation, signed against this challenge.

    Shared by `/a2a` and `/mcp`, and that sharing is the point: the MCP adapter
    is a second envelope over this one function, not a second implementation.
    Two implementations of "what do you have right now" could disagree, and an
    agent that answers differently depending on which door you knocked on is
    exactly the thing this project exists to make impossible.
    """
    observation = agent.latest
    if observation is None:
        # Not an error. The agent is up and has not completed a tick, which
        # is a fact master should record rather than a failure to retry.
        return ObserveResult(
            agent=agent.identity.name,
            ansname=agent.identity.ansname,
            observed_at=utc_now().isoformat(),
            healthy=False,
            note="no observation yet",
        )

    pairs = [
        signer.sign(
            assertion,
            audience=params.audience,
            incident_id=params.incident_id,
            nonce=params.nonce,
            target=params.target,
        )
        for assertion in observation.assertions
    ]
    return ObserveResult(
        agent=observation.agent,
        ansname=observation.ansname,
        observed_at=observation.observed_at.isoformat(),
        healthy=observation.healthy,
        note=observation.note,
        claims=[
            SignedPairWire(
                claim=p.raw_claim.decode("utf-8"), proof=p.raw_proof.decode("utf-8")
            )
            for p in pairs
        ],
        # Unknowns are not claims and are not signed. They assert
        # nothing, so there is nothing to authorize; they travel as
        # attributed context and master records them as gaps.
        unknowns=[
            {"field": u.field, "zone_scope": u.zone_scope, "reason": u.reason}
            for u in observation.unknowns
        ],
    )


# ------------------------------------------------------------- the client side


@dataclass(frozen=True)
class Peer:
    """One agent master can ask, and the ANSName it must answer under."""

    slug: str
    base_url: str
    ansname: str


class A2AObservationSource:
    """Master's side. Issues a challenge, verifies every claim, returns what survived.

    Implements `ObservationSource`. Verification happens **here**, before
    anything reaches master's own gate, so nothing downstream ever sees a field
    that did not survive a signature check.
    """

    def __init__(
        self,
        peers: dict[str, Peer],
        verifier: ClaimVerifier,
        *,
        audience: str,
        target: str,
        timeout_s: float = 3.0,
    ) -> None:
        self._peers = peers
        self._verifier = verifier
        self._audience = audience
        self._target = target
        self._timeout = timeout_s
        self._client = httpx.Client(timeout=timeout_s)
        self.incident_id: str = STEADY_STATE
        self.dispatched_incidents: frozenset[str] = frozenset()

    def close(self) -> None:
        self._client.close()

    def fetch(self, slug: str) -> FetchedObservation | None:
        peer = self._peers.get(slug)
        if peer is None:
            return None

        # A fresh challenge per fetch. Never reused, never derived from
        # anything the producer can see in advance.
        nonce = new_challenge()
        try:
            response = self._client.post(
                f"{peer.base_url}{CLAIM_TARGET_PATH}",
                json={
                    "jsonrpc": "2.0",
                    "id": nonce,
                    "method": METHOD_OBSERVE,
                    "params": {
                        "audience": self._audience,
                        "nonce": nonce,
                        "incident_id": self.incident_id,
                        "target": self._target,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Unreachable is a fact, not an exception to propagate. master
            # records it as an unknown and says so; a mesh that raises mid
            # incident is worse than one that reports a gap.
            logger.warning("%s unreachable: %s", peer.slug, exc)
            return None

        if "error" in payload:
            logger.warning("%s returned an error: %s", peer.slug, payload["error"])
            return None
        try:
            result = ObserveResult.model_validate(payload.get("result") or {})
        except ValidationError:
            logger.exception(
                "%s sent a result this master cannot validate; dropped", peer.slug
            )
            return None

        return self._verify(peer, result, nonce)

    # ------------------------------------------------------------- verification

    def _verify(
        self, peer: Peer, result: ObserveResult, nonce: str
    ) -> FetchedObservation:
        assertions: list[Assertion] = []
        rejected: list[TransportRejection] = []

        for wire in result.claims:
            raw_claim = wire.claim.encode("utf-8")
            raw_proof = wire.proof.encode("utf-8")
            try:
                self._verifier.verify(
                    raw_claim,
                    raw_proof,
                    dispatched_incidents=self.dispatched_incidents,
                    expected_nonce=nonce,
                )
            except VerificationRejected as rejection:
                # Discarded, and recorded. This is the path the submission turns
                # on, so it is never a silent drop.
                rejected.append(
                    TransportRejection(
                        issuer=result.ansname,
                        field=_peek_field(raw_claim),
                        check=rejection.check,
                        reason=str(rejection),
                    )
                )
                continue
            assertions.append(_to_assertion(raw_claim, peer, result))

        # An agent answering under an ANSName that is not the one master has for
        # it is the lookalike-hostname attack, and it is caught here as well as
        # in the trust store: the store refuses the unknown name, and this
        # refuses a known name presented by the wrong peer.
        if result.ansname != peer.ansname:
            rejected.append(
                TransportRejection(
                    issuer=result.ansname,
                    field="*",
                    check="peer_identity",
                    reason=(
                        f"{peer.slug} answered as {result.ansname!r}; master has it registered "
                        f"as {peer.ansname!r}. Every claim from this fetch is discarded."
                    ),
                )
            )
            assertions = []

        observation = AgentObservation(
            agent=result.agent,
            ansname=result.ansname,
            assertions=tuple(assertions),
            unknowns=tuple(
                Unknown(
                    field=u.get("field", "?"),
                    zone_scope=u.get("zone_scope", "site"),
                    reason=u.get("reason", ""),
                )
                for u in result.unknowns
            ),
            healthy=result.healthy and not rejected,
            note=result.note,
        )
        return FetchedObservation(
            observation=observation,
            # Verified only if every claim that arrived survived. A partial
            # result is not a verified one: an agent that sent one good claim
            # and one forged claim is not an agent to speak on behalf of.
            envelope_verified=bool(assertions) and not rejected,
            rejected=tuple(rejected),
        )


def _peek_field(raw_claim: bytes) -> str:
    """The field name from a claim that failed verification, best effort.

    Parsed only *after* the claim was rejected, and used only to label a
    discard in the feed. Nothing downstream acts on it, which is what makes
    reading it here safe: the rule is that nothing unverified is ever *trusted*,
    not that it is never looked at when explaining a refusal.
    """
    try:
        return SignedClaim.model_validate_json(raw_claim).envelope.field
    except ValidationError:
        return "?"


def _to_assertion(raw_claim: bytes, peer: Peer, result: ObserveResult) -> Assertion:
    """Rebuild the assertion from a claim that has already verified.

    Parsed after verification, never before. The envelope carries the asserted
    field, value, zone and ceiling; confidence, basis, provenance and presence
    id are producer context rather than authorization, so they are reconstructed
    here from what the envelope proves plus what the peer reported.
    """
    from hawkeye_backend.models.common import Provenance, Source

    envelope = SignedClaim.model_validate_json(raw_claim).envelope
    return Assertion(
        field=envelope.field,
        value=envelope.value,
        zone_scope=envelope.zone_scope,
        severity_ceiling=envelope.severity_ceiling,
        confidence=1.0,
        basis=(
            f"Signed by {envelope.issuer} and verified against the key it registered, "
            f"answering this master's challenge."
        ),
        provenance=Provenance(
            source=Source.AGENT_INFERENCE,
            producer=result.agent,
            ansname=envelope.issuer,
            detail=f"claim {envelope.claim_id}, expires {envelope.expires_at.isoformat()}",
        ),
    )
