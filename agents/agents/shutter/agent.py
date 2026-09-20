"""`agents/shutter`: the running process, and the control surface it serves.

The agent is thin on purpose. All of the interesting behaviour is in `Shutter`,
which is callable with no event loop, no clock and no transport, and is where
every refusal is proved. This file is the part that makes it reachable.

Two A2A methods, and they are a pair:

    shutter.challenge  ->  a single-use nonce, ten-second TTL
    shutter.open       ->  a grant, verified, and a position attested

**A refusal comes back as a result, not a JSON-RPC error.** Returning an error
would be the wrong shape twice over: it would make a successful defence look
like a malfunction to anything watching, and it would leave the reason in a
transport frame that the sealed record never sees.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from hawkeye_backend.models.common import Provenance
from hawkeye_backend.verification.envelope import Severity
from hawkeye_backend.verification import TrustStore
from pydantic import BaseModel, Field, ValidationError

from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion
from agents.core.signing import ClaimSigner
from agents.core.transport import CLAIM_TARGET_PATH, STEADY_STATE
from agents.shutter.backend import ShutterBackend
from agents.shutter.refusal import GrantRefused, Refusal
from agents.shutter.shutter import Shutter

logger = logging.getLogger(__name__)

#: Stands in for the nonce of a grant that never parsed. Distinct from any
#: nonce this shutter could issue, so a refusal bound to nothing is legible
#: as bound to nothing rather than silently unbound.
UNPARSEABLE_NONCE = "shut-unparseable"

METHOD_CHALLENGE = "shutter.challenge"
METHOD_OPEN = "shutter.open"

#: Maximum grant we will even look at, before parsing. A size bound ahead of a
#: parser, for the same reason `ClaimVerifier` has one.
MAX_GRANT_BYTES = 8 * 1024


class OpenParams(BaseModel):
    """What `master` sends. One field, and it is a **string**."""

    grant: str = Field(
        min_length=1,
        description=(
            "The grant, as an opaque JSON string. A nested object here would be "
            "re-serialized by the JSON layer and the signature would no longer verify "
            "over what arrives."
        ),
    )


class ShutterAgent(Agent):
    """One GPIO pin, always running, answering two questions about one shield."""

    # Slower than a sensing agent. `shutter` has nothing to observe between
    # grants - its state changes when it is told to change, not when the world
    # does - but it ticks anyway, because every agent runs continuously and an
    # agent that only existed during an incident would be a process nobody
    # could verify was up beforehand.
    interval_s = 2.0

    def __init__(
        self,
        *,
        trust: TrustStore,
        backend: ShutterBackend | None = None,
        issuer: str | None = None,
    ) -> None:
        super().__init__(identity("shutter"))
        self.shutter = Shutter(trust=trust, backend=backend, issuer=issuer)
        #: The last refusal, so the tick reports it rather than only the log.
        self.last_refusal: Refusal | None = None

    # ------------------------------------------------------------------ the job

    def tick(self) -> AgentObservation:
        """Say where the shield is. Commanded, and labelled commanded."""
        position = self.shutter.position
        return self.observe(
            assertions=(
                Assertion(
                    field="shutter.position",
                    value=position,
                    zone_scope="living_room",
                    severity_ceiling=Severity.CORROBORATING,
                    confidence=1.0,
                    basis=(
                        "The angle last commanded on GPIO. The SG92R is open-loop, so this "
                        "is what the servo was told, not what it did."
                    ),
                    provenance=Provenance(
                        source=self.shutter.backend.source,
                        producer=self.identity.name,
                        ansname=self.identity.ansname,
                    ),
                ),
            ),
            note=None if self.last_refusal is None else f"last refusal: {self.last_refusal}",
        )

    # -------------------------------------------------------- the control surface

    def a2a_methods(
        self, signer: ClaimSigner
    ) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        """The two methods `master` calls, on the same `/a2a` everything else uses."""
        return {
            METHOD_CHALLENGE: self._challenge,
            METHOD_OPEN: lambda params: self._open(params, signer),
        }

    def _challenge(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"nonce": self.shutter.challenge()}

    def _open(self, params: dict[str, Any], signer: ClaimSigner) -> dict[str, Any]:
        try:
            parsed = OpenParams.model_validate(params)
        except ValidationError as exc:
            return self._refused(
                signer,
                GrantRefused(
                    Refusal.MALFORMED_GRANT,
                    f"params do not parse: {exc.error_count()} error(s)",
                ),
            )

        raw = parsed.grant.encode()
        if len(raw) > MAX_GRANT_BYTES:
            return self._refused(
                signer,
                GrantRefused(
                    Refusal.MALFORMED_GRANT,
                    f"grant exceeds the {MAX_GRANT_BYTES} byte bound; refused before parsing",
                ),
            )

        try:
            attestation = self.shutter.open(raw)
        except GrantRefused as refused:
            logger.warning(
                "shutter refused a grant: %s (%s). The lens is still covered.",
                refused.refusal,
                refused.detail,
            )
            return self._refused(signer, refused)
        except ValidationError as exc:
            return self._refused(
                signer,
                GrantRefused(
                    Refusal.MALFORMED_GRANT, f"not a grant: {exc.error_count()} schema error(s)"
                ),
            )

        self.last_refusal = None
        return {
            "position": attestation.position,
            "commanded_angle": attestation.commanded_angle,
            "attestation": attestation.to_json(),
        }

    def _refused(self, signer: ClaimSigner, refused: GrantRefused) -> dict[str, Any]:
        """What a refusal looks like on the wire.

        A result rather than a JSON-RPC error, and a **signed** one. The signed
        half is what makes this evidence: bound to the nonce of the grant it
        refused, addressed to the agent that presented it, and verifiable months
        later against the key our card published.
        """
        self.last_refusal = refused.refusal
        pair = signer.sign(
            Assertion(
                field="shutter.refusal",
                value=str(refused.refusal),
                zone_scope="living_room",
                severity_ceiling=Severity.CORROBORATING,
                confidence=1.0,
                basis=(
                    f"{refused.detail}. The shield did not move; the commanded angle is "
                    f"{self.shutter.backend.angle} degrees, unchanged."
                ),
                provenance=Provenance(
                    source=self.shutter.backend.source,
                    producer=self.identity.name,
                    ansname=self.identity.ansname,
                ),
            ),
            audience=refused.issuer or identity("master").ansname,
            incident_id=refused.incident_id or STEADY_STATE,
            # The nonce of the grant being refused, which this shutter issued
            # itself. A grant that did not parse carries none, and the sentinel
            # says so rather than inventing a binding that was never there.
            nonce=refused.nonce or UNPARSEABLE_NONCE,
            target=f"{self.identity.base_url}{CLAIM_TARGET_PATH}",
        )
        return {
            "position": self.shutter.position,
            "commanded_angle": self.shutter.backend.angle,
            "refusal": str(refused.refusal),
            "detail": refused.detail,
            "observation": {
                "claim": pair.raw_claim.decode(),
                "proof": pair.raw_proof.decode(),
            },
        }
