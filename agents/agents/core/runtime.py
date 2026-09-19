"""The HTTP surface every agent serves, and the process that runs it.

Identical across the nine, because none of what it does is an agent's job. What
differs between agents is `tick`, and that is the only thing that should differ.

**The hard requirement this file exists for:** the agents must be hosted on the
internet and reachable. The track owner said it directly; localhost does not
count. Host them before they are finished - nine empty agents reachable tonight
beats nine complete agents on a laptop Sunday morning, because the deploy path
is where the hours disappear.

Surfaces:

    /.well-known/agent-card.json      the A2A card, bytes from disk
    /.well-known/agent.json           the same bytes, the alias the spec allows
    /.well-known/ans/trust-card.json  the ANS card, bytes from disk
    /healthz                          liveness, and honest about tick failures
    /v1/observation                   this agent's latest observation

Cards are served as **bytes read from disk**, with a strong ETag over their own
fingerprint. Not re-serialized, not re-assembled, not templated. `ans/CARD.md`
measure 2, and the reason is that `card_drift_watch` cannot tell a card we
changed from a card someone else changed.

`/v1/observation` is a read-only convenience for the app's verification feed and
for a judge poking at a running agent. **It is not the inter-agent channel.**
When agents start reading each other, they do it over a verified transport and
the thing they exchange is a signed claim, not this. See `agents.core.ports`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from agents.core.base import Agent
from agents.core.cards import A2A_CARD_ALIAS, A2A_CARD_PATH, TRUST_CARD_PATH
from agents.core.identity import AgentIdentity

logger = logging.getLogger(__name__)

#: Where `scripts/build_cards.py` writes. One directory per agent.
CARD_ROOT = Path(__file__).resolve().parent.parent.parent / "build" / "cards"


class _CardBytes:
    """A card read once at startup and served verbatim thereafter.

    Read once rather than per request for the same reason the card is a build
    artifact: a file that is re-read can change under us mid-run, and an agent
    whose card changes without a version bump is indistinguishable from a
    compromised one to any monitor watching.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.body: bytes | None = None
        self.etag: str | None = None
        if path.is_file():
            self.body = path.read_bytes()
            # The ETag is over the served bytes, which is the thing a verifier
            # re-fetches and hashes. Anything else would be an ETag for a
            # document we are not serving.
            from hashlib import sha256

            self.etag = '"' + sha256(self.body).hexdigest()[:32] + '"'
        else:
            logger.warning(
                "no card at %s; run scripts/build_cards.py. The agent will serve 503 for "
                "this path rather than assembling one, because an assembled card drifts.",
                path,
            )

    def response(self) -> Response:
        if self.body is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "card_not_built",
                    "detail": (
                        "This agent has no published card. Cards are build artifacts; run "
                        "scripts/build_cards.py. Serving an assembled card would create "
                        "drift a monitor would correctly report against us."
                    ),
                },
            )
        return Response(
            content=self.body,
            media_type="application/json",
            headers={"ETag": self.etag or "", "Cache-Control": "public, max-age=300"},
        )


def build_app(agent: Agent, *, card_dir: Path | None = None) -> FastAPI:
    """Wrap an agent in the surface all nine share."""
    identity: AgentIdentity = agent.identity
    cards = card_dir or (CARD_ROOT / identity.slug)
    a2a = _CardBytes(cards / "agent-card.json")
    trust = _CardBytes(cards / "trust-card.json")

    app = FastAPI(
        title=identity.name,
        summary=identity.summary,
        version="0.1.0",
        docs_url="/docs",
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await agent.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await agent.stop()

    @app.get(A2A_CARD_PATH, include_in_schema=False)
    @app.get(A2A_CARD_ALIAS, include_in_schema=False)
    async def _a2a_card() -> Response:
        return a2a.response()

    @app.get(TRUST_CARD_PATH, include_in_schema=False)
    async def _trust_card() -> Response:
        return trust.response()

    @app.get("/healthz")
    async def _health() -> dict[str, object]:
        """Liveness, and honest about it.

        `healthy` false while `running` true is the state sensor/CLAUDE.md warns
        about twice: a component that reports healthy while producing nothing.
        Separating the two is what makes that visible instead of silent.
        """
        return agent.health()

    @app.get("/v1/observation")
    async def _observation() -> Response:
        latest = agent.latest
        if latest is None:
            return JSONResponse(
                status_code=503,
                content={"error": "no_observation", "detail": "Agent has not completed a tick yet."},
            )
        return JSONResponse(content=latest.model_dump(mode="json"))

    @app.get("/v1/identity")
    async def _identity() -> dict[str, object]:
        """What this agent is, from the same object the card was built from.

        Exists so a divergence between the running agent and its published card
        is one diff away rather than an inference.
        """
        return {
            "agent": identity.name,
            "ansname": identity.ansname,
            "tier": identity.tier,
            "role": identity.role.value,
            "question": identity.question,
            "recommended_profile_expected": identity.profile.value,
            "consumes": [f"agents/{s}" for s in identity.consumes],
            "simulated_inputs": list(identity.simulated_inputs),
            "must_not_claim": list(identity.must_not_claim),
        }

    return app
