"""What master does with a claim before anything downstream sees it.

This agent holds the only full picture, which makes it the place where
verification must be strictest. Every claim it accepts carries the identity of
the agent that made it, that agent's Trust Index score at that instant, and a
verification result. **Anything unverifiable is discarded and logged as
discarded**, and the log is not an afterthought:

    "The agent that speaks to 911 only repeats claims it can cryptographically
    verify, and it tells you what it discarded."

The discard log is what makes that sentence checkable rather than assertable.

## The verification order

From `agents/CLAUDE.md`, derived from the fraud battery, which is thirteen ways
of asking one question: **does this implementation treat a valid signature as
authorization?**

1. Verify the envelope. mTLS, then JWS over the canonical payload. Nothing
   downstream ever sees an unverified field. Verify first, parse second.
2. Check bindings. Audience, zone scope, incident id, nonce.
3. Check schema version. Refuse what is not understood rather than reading it
   charitably.
4. **Then, and only then, apply the profile gate.** What this agent's
   `recommendedProfile` permits this claim to trigger.
5. Log what was discarded, with the reason.

**Steps 1 through 3 belong to the transport and are not wired yet.** They are
implemented, in `hawkeye_backend.verification.ClaimVerifier`, with all thirteen
battery shapes as passing tests; what is missing is a wire carrying signed
claims to run them on. So `TrustGate` takes an optional `envelope_verified`
flag, defaulting to false, and the consequence of false is spelled out in the
result rather than hidden: the claim may inform master's own picture, and
**`agents/caller` may not speak it.**

That is the correct failure mode and it is the project's own rule applied to
itself. Every claim caller speaks has a verified source or it does not get
spoken, and right now nothing has one.

Step 4 is fully implemented here, because it needs no transport. It is also the
interesting half: steps 1 to 3 are authentication, step 4 is authorization, and
the battery exists because implementations conflate them. `underpay_valid_sig`
is the pure case - a genuinely authority-signed claim, correctly signed by the
right key, presented for a magnitude it does not authorize, which must still be
refused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from hawkeye_backend.models.verification import (
    PROFILE_DECISION,
    Claim,
    SourceAgent,
    TrustProfile,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)
from hawkeye_backend.verification.envelope import SEVERITY_ORDER, Severity
from hawkeye_backend.verification.verifier import PROFILE_SEVERITY_CAP

from agents.core.identity import BY_SLUG, AgentIdentity
from agents.core.observations import AgentObservation, Assertion


@dataclass(frozen=True)
class AdmittedClaim:
    """One assertion, and everything master decided about it.

    Carries the original assertion so the classifier reasons over the same
    object the verification feed renders, rather than over a copy that could
    drift from it.
    """

    assertion: Assertion
    result: VerificationResult

    granted: Severity = Severity.INFORMATIONAL
    """The severity this claim is actually permitted to trigger.

    Not the ceiling it asked for. A ceiling is what the producer thinks its
    claim is worth; this is what the producer's trust profile allows. The lower
    of the two wins, always.
    """

    @property
    def spoken(self) -> bool:
        return self.result.will_be_spoken


class TrustGate:
    """Applies the profile gate and records the verdict for every claim.

    Constructed with the profiles master currently believes each agent holds.
    In production those come from a live Trust Index lookup at the instant of
    verification - not from startup, because an agent trusted ninety seconds ago
    may not be trusted now, and an operator asking a question now is asking
    because the answer may have changed.
    """

    def __init__(
        self,
        *,
        profiles: dict[str, TrustProfile] | None = None,
    ) -> None:
        # Default to each agent's expected profile from the roster. That is a
        # development convenience and is exactly what must NOT ship: a profile
        # master assumes is a profile an attacker does not have to earn.
        # TODO(ans): replace with a live Trust Index lookup per claim.
        self._profiles = profiles or {a.slug: a.profile for a in BY_SLUG.values()}
        self.discarded: list[VerificationResult] = []
        self.accepted: list[AdmittedClaim] = []

    # ------------------------------------------------------------------ the gate

    def admit(
        self,
        observation: AgentObservation,
        *,
        incident_id: str | None = None,
        envelope_verified: bool = False,
    ) -> list[AdmittedClaim]:
        """Run every assertion in an observation through the gate.

        `envelope_verified` is **per fetch**, supplied by the transport that
        just verified (or failed to verify) this agent's claims. It is not a
        process-wide setting, because trust is a property of an agent at an
        instant: one that answered a verified challenge a minute ago may fail
        the next because its certificate drifted.
        """
        slug = observation.agent.removeprefix("agents/")
        identity = BY_SLUG.get(slug)
        admitted: list[AdmittedClaim] = []
        for assertion in observation.assertions:
            claim = self._admit_one(
                assertion, identity, slug, observation, incident_id, envelope_verified
            )
            if claim is not None:
                admitted.append(claim)
        return admitted

    def record_transport_rejection(
        self, rejection: object, *, incident_id: str | None = None
    ) -> VerificationResult:
        """Log a claim the transport refused before it ever reached this gate.

        Claims thrown away at the wire never become assertions, so without this
        they would be the one class of discard invisible in the feed - and they
        are the most interesting class, because a claim that fails a signature
        check is an attack in a way that a capped severity is not.
        """
        result = VerificationResult(
            verification_id=f"v-{uuid.uuid4().hex[:12]}",
            incident_id=incident_id,
            claim=Claim(
                claim_id=f"c-{uuid.uuid4().hex[:12]}",
                statement=getattr(rejection, "reason", ""),
                field=getattr(rejection, "field", "?"),
                value="",
            ),
            agent=SourceAgent(
                name="unverified",
                ansname=getattr(rejection, "issuer", "unknown"),
                recommended_profile=TrustProfile.UNTRUSTED,
            ),
            decision=VerificationDecision.DISCARDED,
            reason=getattr(rejection, "reason", "refused at the transport"),
            checks=[
                VerificationCheck(
                    name=getattr(rejection, "check", "envelope_verified"),
                    passed=False,
                    detail=getattr(rejection, "reason", ""),
                )
            ],
            will_be_spoken=False,
        )
        self.discarded.append(result)
        return result

    def _admit_one(
        self,
        assertion: Assertion,
        identity: AgentIdentity | None,
        slug: str,
        observation: AgentObservation,
        incident_id: str | None,
        envelope_verified: bool,
    ) -> AdmittedClaim | None:
        checks: list[VerificationCheck] = []

        # An agent master has never heard of is refused outright. Unknown is a
        # refusal, never an unknown-therefore-allow; that is battery #11, and it
        # is the difference between a registry and a guest list.
        if identity is None:
            result = self._result(
                assertion,
                slug,
                ansname=observation.ansname,
                profile=TrustProfile.UNTRUSTED,
                decision=VerificationDecision.DISCARDED,
                reason=f"{observation.agent!r} is not one of the five registered agents.",
                checks=[
                    VerificationCheck(
                        name="known_issuer",
                        passed=False,
                        detail="Not in the roster. Unknown is a refusal, not a default-allow.",
                    )
                ],
                incident_id=incident_id,
                spoken=False,
            )
            self.discarded.append(result)
            return None
        checks.append(
            VerificationCheck(
                name="known_issuer",
                passed=True,
                detail=f"{identity.name} registered as {identity.ansname}.",
            )
        )

        # The issuer must be the agent whose field this is. `agents/replay`
        # asserting `people.respiration` is either a bug or an agent reaching
        # outside its own scope, and neither should reach a dispatcher.
        namespace = assertion.field.split(".", 1)[0]
        if namespace != slug:
            result = self._result(
                assertion,
                slug,
                ansname=observation.ansname,
                profile=self._profiles.get(slug, TrustProfile.UNTRUSTED),
                decision=VerificationDecision.DISCARDED,
                reason=(
                    f"{identity.name} asserted {assertion.field!r}, which belongs to "
                    f"agents/{namespace}. An agent may only speak for itself."
                ),
                checks=checks
                + [
                    VerificationCheck(
                        name="field_scope",
                        passed=False,
                        detail=f"{assertion.field!r} is outside {identity.name}'s namespace.",
                    )
                ],
                incident_id=incident_id,
                spoken=False,
            )
            self.discarded.append(result)
            return None
        checks.append(
            VerificationCheck(
                name="field_scope",
                passed=True,
                detail=f"{assertion.field!r} is within {identity.name}'s own namespace.",
            )
        )

        # Step 1 of the verification order, and the one that is not wired.
        # Recorded as a failed check rather than omitted, because a check that
        # is absent from the list and a check that passed look the same to
        # anyone reading the feed, and they are not the same at all.
        checks.append(
            VerificationCheck(
                name="envelope_verified",
                passed=envelope_verified,
                detail=(
                    "JWS signature verified over the canonical envelope, bound to this "
                    "master, to this incident, and to the challenge this master issued."
                    if envelope_verified
                    else (
                        "NOT VERIFIED: this observation did not arrive over a verified "
                        "transport, so no signature was checked. No claim from it may be "
                        "spoken to an operator."
                    )
                ),
            )
        )

        profile = self._profiles.get(slug, TrustProfile.UNTRUSTED)
        decision = PROFILE_DECISION[profile]

        if profile is TrustProfile.UNTRUSTED:
            # Suppression, not revocation. master stops accepting this agent's
            # claims and logs the discard; it does not try to revoke anything
            # mid-incident, because only the RA revokes.
            result = self._result(
                assertion,
                slug,
                ansname=observation.ansname,
                profile=profile,
                decision=VerificationDecision.DISCARDED,
                reason=(
                    f"{identity.name} is UNTRUSTED. Discarded and logged. This is "
                    "discovery suppression, not revocation: only the RA revokes."
                ),
                checks=checks
                + [
                    VerificationCheck(
                        name="profile_gate",
                        passed=False,
                        detail="UNTRUSTED claims are discarded whatever their content.",
                    )
                ],
                incident_id=incident_id,
                spoken=False,
            )
            self.discarded.append(result)
            return None

        # The authorization half. A ceiling is not a floor: the claim asked for
        # at most `severity_ceiling`, the profile permits at most the cap, and
        # the lower wins. This is where a correctly signed claim gets refused
        # for the thing it is being used for rather than for how it was signed.
        cap = PROFILE_SEVERITY_CAP[profile]
        granted = (
            assertion.severity_ceiling
            if SEVERITY_ORDER[assertion.severity_ceiling] <= SEVERITY_ORDER[cap]
            else cap
        )
        capped = granted is not assertion.severity_ceiling
        checks.append(
            VerificationCheck(
                name="profile_gate",
                passed=True,
                detail=(
                    f"{profile.value} permits at most {cap.value}; claim asked for "
                    f"{assertion.severity_ceiling.value}; granted {granted.value}."
                    + (" Capped." if capped else "")
                ),
            )
        )

        # Speakable only when the source was actually verified. The rule is not
        # relaxed because the claim is urgent or because the source is FIDUCIARY;
        # urgency is exactly when an impostor would want it relaxed.
        spoken = envelope_verified and decision in (
            VerificationDecision.ASSERTED,
            VerificationDecision.ATTRIBUTED,
        )

        result = self._result(
            assertion,
            slug,
            ansname=observation.ansname,
            profile=profile,
            decision=decision,
            reason=(
                f"{identity.name} holds {profile.value}; claim relayed as {decision.value} "
                f"at {granted.value}."
                + (
                    ""
                    if spoken
                    else " Not speakable: the source was not cryptographically verified."
                )
            ),
            checks=checks,
            incident_id=incident_id,
            spoken=spoken,
        )
        claim = AdmittedClaim(assertion=assertion, result=result, granted=granted)
        self.accepted.append(claim)
        return claim

    # ---------------------------------------------------------------- reporting

    def _result(
        self,
        assertion: Assertion,
        slug: str,
        *,
        ansname: str,
        profile: TrustProfile,
        decision: VerificationDecision,
        reason: str,
        checks: list[VerificationCheck],
        incident_id: str | None,
        spoken: bool,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=f"v-{uuid.uuid4().hex[:12]}",
            incident_id=incident_id,
            claim=Claim(
                claim_id=f"c-{uuid.uuid4().hex[:12]}",
                statement=assertion.basis,
                field=assertion.field,
                value=assertion.value,
                presence_id=assertion.presence_id,
            ),
            agent=SourceAgent(
                name=f"agents/{slug}",
                ansname=ansname,
                # TODO(ans): the certificate version and Trust Index score both
                # belong here, read live at the instant of verification. A
                # fingerprint that drifted mid-run is how code drift becomes
                # detectable, and it is the strongest single use of ANS
                # available to us.
                certificate_version=None,
                trust_index=None,
                recommended_profile=profile,
            ),
            decision=decision,
            reason=reason,
            checks=checks,
            will_be_spoken=spoken,
        )

    def speakable(self) -> list[AdmittedClaim]:
        """Only what agents/caller is permitted to repeat out loud."""
        return [c for c in self.accepted if c.spoken]
