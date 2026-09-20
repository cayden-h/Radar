"""The gate. A grant goes in, and a piece of plastic moves or does not.

The structural rule this file exists to hold: **there is no code path from a
failed verification to a `set_angle` call.** Not as a convention someone
maintains, but because `_drive` takes a `VerifiedGrant`, and a `VerifiedGrant`
cannot be constructed anywhere but inside `verify`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.verification import TrustProfile
from hawkeye_backend.verification import TrustStore
from hawkeye_backend.verification.b64 import b64u_decode
from hawkeye_backend.verification.canonical import canonicalize

from agents.core.identity import identity
from agents.shutter.backend import CLOSED_ANGLE, OPEN_ANGLE, ShutterBackend, StubShutter
from agents.shutter.challenge import ChallengeBook
from agents.shutter.grant import ACTIONS, SignedGrant
from agents.shutter.refusal import GrantRefused, Refusal

#: Nothing outside this module holds it, which is what makes `VerifiedGrant`
#: unforgeable by construction rather than by agreement.
_VERIFIED = object()


@dataclass(frozen=True)
class VerifiedGrant:
    """A grant that passed every check. The only key that fits the GPIO lock."""

    nonce: str
    issuer: str
    action: str
    reason: str
    incident_id: str | None

    def __post_init__(self) -> None:
        if getattr(self, "_token", None) is not _VERIFIED:
            raise TypeError(
                "VerifiedGrant is constructed by the verifier and nowhere else. If you "
                "are here, something is trying to reach the servo around the gate."
            )

    _token: object = None


@dataclass(frozen=True)
class Attestation:
    """What `shutter` says after moving, and what `vision` will not act without.

    It carries the position, the timestamp, the nonce of the grant that caused
    it, and the servo's **commanded** angle. It does not carry a claim that the
    shield is physically where the servo says it is: the SG92R is open-loop and
    we have no position feedback. Say so in the field rather than implying
    otherwise - a shield that jammed would attest open while covering the lens,
    and the only thing that catches that is the frame itself being dark.
    """

    position: str
    commanded_angle: int
    nonce: str
    at: datetime

    #: Named in the data, not only in the docs, so a consumer cannot read this
    #: as a measurement by accident.
    position_basis: str = "commanded"

    def to_json(self) -> str:
        """The attestation as the opaque string it crosses the wire as."""
        return json.dumps(
            {
                "position": self.position,
                "commanded_angle": self.commanded_angle,
                "position_basis": self.position_basis,
                "nonce": self.nonce,
                "at": self.at.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )


class Shutter:
    """One GPIO pin, one trust store, and seven ways to say no."""

    def __init__(
        self,
        *,
        trust: TrustStore,
        backend: ShutterBackend | None = None,
        issuer: str | None = None,
        challenges: ChallengeBook | None = None,
    ) -> None:
        self.backend = backend or StubShutter()
        self._trust = trust
        # The one agent this shutter takes orders from, by name. Any other name
        # is a lookalike, whatever it signs with.
        self._issuer = issuer or identity("master").ansname
        self._challenges = challenges or ChallengeBook()
        # Digests of grants already honoured. Digests rather than the grants
        # themselves, because the only question asked of this set is whether
        # these exact bytes have been here before.
        self._honoured: set[str] = set()

    @property
    def position(self) -> str:
        """Where the shield is, from the angle last commanded. Never measured."""
        return "open" if self.backend.angle == OPEN_ANGLE else "closed"

    def challenge(self, *, now: datetime | None = None) -> str:
        """Issue the nonce a grant must carry. The verifier asks, always."""
        return self._challenges.issue(now=now)

    def open(self, raw_grant: bytes, *, now: datetime | None = None) -> Attestation:
        """Verify a grant and act on it."""
        now = now or utc_now()
        grant = self._verify(raw_grant, now=now)
        # Recorded only once the grant is about to be acted on. A refused
        # grant is not 'honoured', and recording it here would let a single
        # malformed replay mask the later arrival of the real thing.
        self._honoured.add(hashlib.sha256(raw_grant).hexdigest())
        return self._drive(grant, now=now)

    # ----------------------------------------------------------- the gate

    def _verify(self, raw_grant: bytes, *, now: datetime) -> VerifiedGrant:
        """Every check, in the order the checks have to run in.

        The ordering is not cosmetic. The nonce is spent by *any* presentation,
        so the replay check has to happen before it - otherwise a byte-identical
        replay reports `stale_nonce` and the more specific finding is lost. And
        the name is checked before the signature, so that "some other agent
        entirely" and "master's name over the wrong key" stay distinguishable in
        the record.
        """
        digest = hashlib.sha256(raw_grant).hexdigest()
        if digest in self._honoured:
            raise GrantRefused(
                Refusal.REPLAYED_GRANT,
                "these exact bytes have already moved this shutter once",
            )

        signed = SignedGrant.model_validate_json(raw_grant)
        env = signed.envelope

        def refuse(refusal: Refusal, detail: str) -> GrantRefused:
            """Every refusal past this point is bound to the grant that caused it."""
            return GrantRefused(
                refusal,
                detail,
                nonce=env.nonce,
                issuer=env.issuer,
                incident_id=env.incident_id,
            )

        # The ANSName is checked against the one agent this shutter takes orders
        # from, by name, before any cryptography runs. A lookalike is a naming
        # attack and it is caught at the name.
        if env.issuer != self._issuer:
            raise refuse(
                Refusal.LOOKALIKE_ANSNAME,
                f"{env.issuer!r} is not {self._issuer!r}; this shutter takes orders from one agent",
            )

        agent = self._trust.lookup(env.issuer)
        if agent is None:
            raise refuse(
                Refusal.UNREGISTERED_ISSUER,
                f"{env.issuer!r} is not in the trust store, or its discovery is suppressed",
            )

        # Authorization, and it runs before the signature work rather than
        # after. An UNTRUSTED verdict means this agent should not be acted on at
        # all, so whether its signature is good is not a question worth asking.
        if agent.profile is TrustProfile.UNTRUSTED:
            raise refuse(
                Refusal.UNTRUSTED_PROFILE,
                f"{env.issuer!r} has a recommendedProfile of UNTRUSTED; suppressed, not revoked",
            )

        # Verified against the key `master` publishes in its own trust card, not
        # against a configured list of keys that are allowed. That is the
        # difference between an identity and an allowlist.
        try:
            agent.public_key.verify(
                b64u_decode(signed.signature),
                canonicalize(env.model_dump(mode="json")),
            )
        except InvalidSignature as exc:
            raise refuse(
                Refusal.UNREGISTERED_ISSUER,
                "signature does not verify under the key master's trust card carries",
            ) from exc

        # Spent by this presentation whether or not everything after it passes.
        # A nonce released back into the pool by a failed attempt is an oracle.
        if not self._challenges.spend(env.nonce, now=now):
            raise refuse(
                Refusal.STALE_NONCE,
                "nonce was never issued, is already spent, or has expired",
            )

        if env.expires_at <= now:
            raise refuse(
                Refusal.EXPIRED_GRANT,
                f"grant expired at {env.expires_at.isoformat()}",
            )

        if env.action not in ACTIONS:
            raise refuse(
                Refusal.UNKNOWN_ACTION,
                f"{env.action!r} is not one of {sorted(ACTIONS)}",
            )

        return VerifiedGrant(
            nonce=env.nonce,
            issuer=env.issuer,
            action=env.action,
            reason=env.reason,
            incident_id=env.incident_id,
            _token=_VERIFIED,
        )

    # ------------------------------------------------- the only way to the pin

    def _drive(self, grant: VerifiedGrant, *, now: datetime) -> Attestation:
        angle = OPEN_ANGLE if grant.action == "open" else CLOSED_ANGLE
        self.backend.set_angle(angle)
        return Attestation(
            position=grant.action if grant.action == "close" else "open",
            commanded_angle=angle,
            nonce=grant.nonce,
            at=now,
        )
