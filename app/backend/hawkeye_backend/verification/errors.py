"""Rejection taxonomy, named to line up with the battery's expected verdicts.

`fraud.webmesh.ai` expects `MANDATE_REJECTED`, `DPOP_REJECTED`, or
`MANDATE_PARSE_ERROR`. Ours are the same three shapes with our nouns, so a
reader holding the battery output next to `tests/test_battery.py` can match them
up without a translation table.
"""

from __future__ import annotations

from enum import StrEnum


class RejectionCode(StrEnum):
    """Why a claim was refused.

    Every rejection is specific. "Untrusted" is a verdict; "audience names a
    different master" is a reason, and the reason is what `agents/replay` seals
    and what the iOS app renders in the verification stream.
    """

    # Envelope could not be read at all. Battery analogue: MANDATE_PARSE_ERROR.
    CLAIM_PARSE_ERROR = "CLAIM_PARSE_ERROR"

    # Envelope read, but refused. Battery analogue: MANDATE_REJECTED.
    CLAIM_REJECTED = "CLAIM_REJECTED"

    # Proof-of-possession refused. Battery analogue: DPOP_REJECTED.
    PROOF_REJECTED = "PROOF_REJECTED"


class VerificationRejected(Exception):
    """A claim was refused, with a stated reason.

    Carries the check that failed so the refusal is legible rather than a bare
    denial. `agents/caller` never sees a rejected claim; `agents/replay` seals
    every one of them.
    """

    def __init__(self, code: RejectionCode, check: str, detail: str) -> None:
        self.code = code
        self.check = check
        self.detail = detail
        super().__init__(f"{code.value}: {check}: {detail}")
