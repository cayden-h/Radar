"""The agent that moves a piece of plastic.

One GPIO pin, one TowerPro SG92R, one opaque shield in front of a camera lens.
It will rotate that shield out of the way for exactly one reason: a grant from
`master` that it can verify. Spec and reasoning: `shutter/CLAUDE.md`.

**This is the smallest agent in the project and the most important one for the
pitch.** Everything else in Hawk Eye is software claiming things about software.
This one is a physical object that moves, on stage, because a signature checked
out - and, more to the point, one that stays put when a signature does not.
"""

from __future__ import annotations

from agents.shutter.backend import CLOSED_ANGLE, OPEN_ANGLE, ShutterBackend, StubShutter
from agents.shutter.challenge import ChallengeBook
from agents.shutter.grant import GrantEnvelope, SignedGrant, sign_grant
from agents.shutter.refusal import GrantRefused, Refusal
from agents.shutter.shutter import Attestation, Shutter, VerifiedGrant

__all__ = [
    "CLOSED_ANGLE",
    "OPEN_ANGLE",
    "Attestation",
    "ChallengeBook",
    "GrantEnvelope",
    "GrantRefused",
    "Refusal",
    "Shutter",
    "ShutterBackend",
    "SignedGrant",
    "StubShutter",
    "VerifiedGrant",
    "sign_grant",
]
