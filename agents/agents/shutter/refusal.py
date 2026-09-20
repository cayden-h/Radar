"""The seven ways `shutter` says no, and what saying no looks like.

**A refusal is not an error.** It is an observation, it is signed, and it goes
into the sealed record beside everything else that happened. That distinction
is the demo: an exception that scrolls past in a log proves nothing to a judge,
and a signed refusal naming its reason is evidence a detective could read back
six months later.

Every one of these leaves the servo where it was. That is enforced by the shape
of the code rather than by discipline - the refusal is raised inside the
verifier, and the verifier is the only thing that can construct the value the
GPIO write accepts.
"""

from __future__ import annotations

from enum import StrEnum


class Refusal(StrEnum):
    """Why the shield did not move. One of these, always, never a bare failure."""

    UNREGISTERED_ISSUER = "unregistered_issuer"
    """The signing key is not the one `master`'s published trust card carries."""

    LOOKALIKE_ANSNAME = "lookalike_ansname"
    """An ANSName that resolves to something other than the registered `master`."""

    STALE_NONCE = "stale_nonce"
    """The nonce was never issued, was already spent, or has expired."""

    REPLAYED_GRANT = "replayed_grant"
    """A grant byte-identical to one already honoured."""

    EXPIRED_GRANT = "expired_grant"
    """`expires_at` is in the past."""

    UNKNOWN_ACTION = "unknown_action"
    """Anything other than `open` or `close`. An unknown action is not a default."""

    UNTRUSTED_PROFILE = "untrusted_profile"
    """`master`'s Trust Index `recommendedProfile` came back UNTRUSTED.

    Discovery suppression, not revocation. Only the RA revokes certificates, and
    `shutter` declining to act on an agent is a local decision about this one
    command rather than a statement about that agent's registration.
    """

    MALFORMED_GRANT = "malformed_grant"
    """Not a grant at all: unparseable, oversized, or carrying smuggled members.

    Not one of the seven in `shutter/CLAUDE.md`, because it is the floor rather
    than an attack with a name. It is here so that "we could not read it" never
    borrows the wire representation of a check that actually ran.
    """


class GrantRefused(Exception):
    """Raised by the verifier. The lens is still covered when you catch this.

    It carries whatever of the grant the verifier had managed to read before it
    refused, so the signed refusal can be **bound to the grant it refused** -
    addressed to the agent that presented it, answering that agent's nonce.
    An unbound refusal is a much weaker artifact: it says a refusal happened
    somewhere, rather than that this grant was refused.

    All three are `None` for a grant that did not parse, and that is honest
    rather than a gap. There was nothing to bind to.
    """

    def __init__(
        self,
        refusal: Refusal,
        detail: str,
        *,
        nonce: str | None = None,
        issuer: str | None = None,
        incident_id: str | None = None,
    ) -> None:
        super().__init__(f"{refusal}: {detail}")
        self.refusal = refusal
        self.detail = detail
        self.nonce = nonce
        self.issuer = issuer
        self.incident_id = incident_id
