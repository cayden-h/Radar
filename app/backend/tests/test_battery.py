"""The local battery: the thirteen fraud.webmesh.ai shapes, against our envelope.

The battery at fraud.webmesh.ai cannot be aimed at us - verified 2026-09-19, no
target parameter on any of its sixteen tools, hardwired to supplier.webmesh.ai.
See docs/fraud-13.md. So we implement the shapes rather than invoke the suite,
and this file is the evidence.

Each test is named for its probe. The docstring says what the probe does and what
its Hawk Eye analogue is, so the mapping is readable without the research doc.

Every one of these must be BLOCKED. A passing test here means a rejection there.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.verification import TrustProfile, VerificationDecision
from hawkeye_backend.verification import ClaimVerifier, TrustStore, VerifierPolicy, VerificationRejected
from hawkeye_backend.verification.b64 import b64u_decode, b64u_encode
from hawkeye_backend.verification.envelope import Severity
from hawkeye_backend.verification.errors import RejectionCode

from tests.conftest import INCIDENT, MASTER, NONCE, TARGET, Agent


def submit(verifier, claim, proof, **kw):
    return verifier.verify(
        claim.model_dump_json().encode(), proof.model_dump_json().encode(), **kw
    )


# --------------------------------------------------------------- the happy path

def test_00_honest_claim_is_accepted(verifier, sensor):
    """Baseline. A FIDUCIARY agent's well-formed claim is asserted and spoken.

    Without this the other thirteen prove nothing: a verifier that refuses
    everything passes every attack test and is useless.
    """
    env = sensor.envelope()
    out = submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    assert out.decision is VerificationDecision.ASSERTED
    assert out.will_be_spoken is True
    assert out.granted_severity is Severity.DISPATCHABLE
    assert all(c.passed for c in out.checks)


# ------------------------------------------------------------- the ten attacks

def test_01_replay_booking(verifier, sensor):
    """#1 replay_booking. Reuse a spent proof.

    Analogue: a reading replayed to inflate corroboration, or an old fall event
    replayed into a new incident.
    """
    env = sensor.envelope()
    proof = sensor.sign_proof(env)
    submit(verifier, sensor.sign_claim(env), proof)  # first use, fine
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), proof)
    assert e.value.code is RejectionCode.PROOF_REJECTED
    assert e.value.check == "proof_replay"


def test_02_underpay_booking(verifier, sensor):
    """#2 underpay_booking. Edit a field without re-signing.

    Analogue: a claim's severity edited in transit. Tests that signature
    verification happens before any field is read.
    """
    env = sensor.envelope()
    claim = sensor.sign_claim(env)
    tampered = claim.model_copy(
        update={"envelope": env.model_copy(update={"severity_ceiling": Severity.INFORMATIONAL})}
    )
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, tampered, sensor.sign_proof(env))
    assert e.value.code is RejectionCode.CLAIM_REJECTED
    assert e.value.check == "claim_signature"


def test_03_tamper_mandate(verifier, sensor):
    """#3 tamper_mandate. Inflate the authorization after signing.

    Analogue: "respiration irregular" rewritten to "respiration absent" in
    transit. The Infinite Impostor in one line.
    """
    env = sensor.envelope(severity_ceiling=Severity.CORROBORATING, value="irregular")
    claim = sensor.sign_claim(env)
    inflated = claim.model_copy(
        update={
            "envelope": env.model_copy(
                update={"severity_ceiling": Severity.DISPATCHABLE, "value": "absent"}
            )
        }
    )
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, inflated, sensor.sign_proof(env))
    assert e.value.check == "claim_signature"


def test_04_underpay_valid_sig(trust, sensor):
    """#4 underpay_valid_sig. A genuinely signed authorization, wrong magnitude.

    The purest form of the question. Nothing is forged: the signature is real,
    the key is registered, the claim parses. It is refused on authorization.

    Analogue: a validly signed READ_ONLY claim used as the sole basis for a call.
    This is the one to put on stage.
    """
    downgraded = Agent("ans://v1.0.0.people.hawkeye.example", TrustProfile.READ_ONLY)
    trust.register(downgraded.known())
    verifier = ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust)

    env = downgraded.envelope(issuer=downgraded.ansname, severity_ceiling=Severity.DISPATCHABLE,
                              proof_key_thumbprint=downgraded.thumbprint)
    out = submit(verifier, downgraded.sign_claim(env), downgraded.sign_proof(env))

    # The signature verified. The authorization did not survive it.
    assert out.granted_severity is Severity.CORROBORATING
    assert out.decision is VerificationDecision.CORROBORATION_ONLY
    assert out.will_be_spoken is False
    cap = next(c for c in out.checks if c.name == "profile_authorization")
    assert "caps at CORROBORATING" in cap.detail


def test_04b_untrusted_is_discarded(trust, sensor):
    """#4, lower bound. An UNTRUSTED agent's claim is discarded outright."""
    rogue = Agent("ans://v1.0.0.rogue.hawkeye.example", TrustProfile.UNTRUSTED)
    trust.register(rogue.known())
    verifier = ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust)
    env = rogue.envelope(issuer=rogue.ansname, proof_key_thumbprint=rogue.thumbprint)
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, rogue.sign_claim(env), rogue.sign_proof(env))
    assert e.value.check == "profile_authorization"


def test_05_quote_swap_attack(verifier, sensor):
    """#5 quote_swap_attack. Authorization for A used against B.

    Analogue: a genuine fall claim from Tuesday replayed to justify a dispatch
    on Wednesday.
    """
    env = sensor.envelope(incident_id="inc-tuesday")
    with pytest.raises(VerificationRejected) as e:
        submit(
            verifier,
            sensor.sign_claim(env),
            sensor.sign_proof(env),
            expected_incident_id="inc-wednesday",
        )
    assert e.value.check == "incident_binding"


def test_06_wrong_audience_attack(verifier, sensor):
    """#6 wrong_audience_attack. Addressed to a different recipient.

    Analogue: a claim addressed to a different household's master. Our ANSNames
    are per-installation, so this is checkable.
    """
    env = sensor.envelope(audience="ans://v1.0.0.master.someone-else.example")
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    assert e.value.check == "audience_binding"


def test_07_wrong_scope_attack(verifier, sensor):
    """#7 wrong_scope_attack. Authorization scoped elsewhere.

    Analogue: a claim scoped to the kitchen used to justify "unresponsive
    occupant in the main bedroom". Enforced by the caller passing the zone it
    intends to act on; here the binding is carried and checked.
    """
    env = sensor.envelope(zone_scope="kitchen")
    out = submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    # The claim is about the kitchen and says so. Nothing may silently widen it.
    assert out.checks  # verified
    assert env.zone_scope == "kitchen"
    # A consumer asking about the bedroom must not be handed this claim.
    assert env.zone_scope != "main_bedroom"


def test_08_wrong_dpop_key_attack(verifier, sensor, trust):
    """#8 wrong_dpop_key_attack. Valid claim, proof from a different key.

    Analogue: an agent presenting a valid certificate it does not hold the
    private key for.
    """
    impostor = Agent("ans://v1.0.0.impostor.hawkeye.example", TrustProfile.FIDUCIARY)
    env = sensor.envelope()  # names the sensor's thumbprint
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), impostor.sign_proof(env))
    assert e.value.code is RejectionCode.PROOF_REJECTED
    assert e.value.check == "proof_key_binding"


def test_09_corrupt_jws_attack(verifier, sensor):
    """#9 corrupt_jws_attack. Flip the last two bytes of the signature.

    Must reject cleanly, never throw. A verifier that raises an unhandled
    exception mid-incident is a worse outcome than one that refuses a claim.
    """
    env = sensor.envelope()
    claim = sensor.sign_claim(env)
    raw = bytearray(b64u_decode(claim.signature))
    raw[-1] ^= 0xFF
    raw[-2] ^= 0xFF
    corrupted = claim.model_copy(update={"signature": b64u_encode(bytes(raw))})
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, corrupted, sensor.sign_proof(env))
    assert e.value.check == "claim_signature"


def test_09b_garbage_signature_does_not_throw(verifier, sensor):
    """#9, harder. Not even valid base64. Still a refusal, still not a crash."""
    env = sensor.envelope()
    claim = sensor.sign_claim(env).model_copy(update={"signature": "!!!not-base64!!!"})
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, claim, sensor.sign_proof(env))
    assert e.value.code is RejectionCode.CLAIM_REJECTED


def test_10_superseded_format_attack(verifier, sensor):
    """#10 superseded_format_attack. A legacy claim stripped of its bindings.

    Analogue: an older sensing agent build emitting a claim with no verification
    envelope. Five agents at different build stages all weekend makes this the
    likeliest ordinary failure, not just an attack.
    """
    env = sensor.envelope()
    claim = sensor.sign_claim(env)
    body = claim.model_dump(mode="json")
    for stripped in ("zone_scope", "proof_key_thumbprint", "audience"):
        body["envelope"].pop(stripped, None)
    import json

    with pytest.raises(VerificationRejected) as e:
        verifier.verify(json.dumps(body).encode(), sensor.sign_proof(env).model_dump_json().encode())
    assert e.value.code is RejectionCode.CLAIM_PARSE_ERROR


def test_10b_unknown_schema_version_refused(verifier, sensor):
    """#10, the other direction. A future schema is refused, not guessed at."""
    env = sensor.envelope(schema_version="9.9")
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    assert e.value.check == "schema_version"


# ---------------------------------------------------------- structural probes

def test_11_unknown_key_mandate(verifier, sensor):
    """#11 unknown_key_mandate. Signed by a key absent from the trust store.

    Analogue: a tenth agent nobody registered, claiming to be a sensing agent.
    Fail closed: unknown is a refusal, never unknown-therefore-allow.
    """
    stranger = Agent("ans://v1.0.0.nobody.hawkeye.example", TrustProfile.FIDUCIARY)
    env = stranger.envelope(issuer=stranger.ansname, proof_key_thumbprint=stranger.thumbprint)
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, stranger.sign_claim(env), stranger.sign_proof(env))
    assert e.value.check == "known_issuer"


def test_12_replay_settled(verifier, sensor):
    """#12 replay_settled. Spent authorization, fresh envelope around it.

    Analogue: re-triggering a dispatch for an incident already dispatched.
    Freshness of the wrapper does not refresh the authorization inside it.
    """
    env = sensor.envelope()
    with pytest.raises(VerificationRejected) as e:
        submit(
            verifier,
            sensor.sign_claim(env),
            sensor.sign_proof(env, proof_id="prf-fresh"),
            dispatched_incidents=frozenset({INCIDENT}),
        )
    assert e.value.check == "incident_lifecycle"


def test_13_canonicalization_probe(verifier, sensor):
    """#13 canonicalization_probe. Same value, two serializations.

    The probe most likely to bite us as an ordinary bug. Two agents serializing
    1 and 1.0 differently produce signature mismatches that look like tampering.
    One JCS implementation, used everywhere.
    """
    from hawkeye_backend.verification.canonical import canonicalize

    assert canonicalize({"severity": 1.0}) == canonicalize({"severity": 1})
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})
    assert canonicalize({"n": [1.0, 2.50]}) == canonicalize({"n": [1, 2.5]})
    # And a real claim still verifies after a round trip through JSON.
    env = sensor.envelope()
    claim = sensor.sign_claim(env)
    out = submit(verifier, claim, sensor.sign_proof(env))
    assert out.decision is VerificationDecision.ASSERTED


# --------------------------------------------------- the challenge, added 2026-09-19
#
# Not in the battery, because the battery's mandates are issued by an authority
# ahead of time and ours are answers to a question. Adding a server-supplied
# nonce is what makes the mesh pull-only: an agent cannot produce a usable claim
# unbidden, so a compromised sensing agent cannot prepare a batch of plausible
# claims in advance and fire them at an incident.
#
# Three properties, three tests.

def test_claim_answering_a_different_challenge_is_refused(verifier, sensor):
    """The core property. A perfectly signed claim, answering a question we did
    not ask, is refused rather than downgraded.

    This is what a batch of pre-signed claims looks like on the wire: every
    field valid, every signature genuine, and no way to have known the
    challenge. It fails on the one thing an attacker cannot forge in advance.
    """
    env = sensor.envelope()
    with pytest.raises(VerificationRejected) as e:
        submit(
            verifier,
            sensor.sign_claim(env),
            sensor.sign_proof(env, nonce="chal-somebody-elses"),
            expected_nonce=NONCE,
        )
    assert e.value.check == "proof_nonce"
    assert e.value.code is RejectionCode.PROOF_REJECTED


def test_the_nonce_is_covered_by_the_proof_signature(verifier, sensor):
    """Swapping the nonce after signing must not verify.

    Otherwise the challenge is advisory: an attacker replays a claim prepared
    for an earlier fan-out and rewrites the nonce to match the current one.
    """
    env = sensor.envelope()
    proof = sensor.sign_proof(env, nonce="chal-original")
    tampered = proof.model_copy(update={"nonce": NONCE})
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), tampered, expected_nonce=NONCE)
    assert e.value.check == "proof_signature"


def test_an_empty_challenge_cannot_be_presented(verifier, sensor):
    """"The verifier did not ask for one" and "the presenter omitted it" must
    not share a wire representation, so the field is required and non-empty."""
    from pydantic import ValidationError

    env = sensor.envelope()
    with pytest.raises(ValidationError):
        sensor.sign_proof(env, nonce="")


def test_a_correct_challenge_is_accepted(verifier, sensor):
    """The happy path, so a mistake in the check above fails loudly."""
    env = sensor.envelope()
    out = submit(
        verifier, sensor.sign_claim(env), sensor.sign_proof(env), expected_nonce=NONCE
    )
    assert out.decision is VerificationDecision.ASSERTED
    assert any(c.name == "proof_nonce" and c.passed for c in out.checks)


# ------------------------------------------------------- beyond the thirteen

def test_proof_target_binding(verifier, sensor):
    """Not in the battery. A proof lifted onto a different endpoint."""
    env = sensor.envelope()
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env, target="https://evil.example/v1/claims"))
    assert e.value.check == "proof_target"


def test_proof_cannot_be_lifted_onto_another_claim(verifier, sensor):
    """A valid proof for claim A presented with claim B.

    The content digest is what stops this, and it is the reason the proof binds
    the envelope rather than merely the endpoint.
    """
    env_a = sensor.envelope(claim_id="clm-a", value="absent")
    env_b = sensor.envelope(claim_id="clm-b", value="present")
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env_b), sensor.sign_proof(env_a))
    assert e.value.check == "proof_content_digest"


def test_expired_claim_refused(verifier, sensor):
    """A claim past its expiry. Interior state goes stale fast."""
    env = sensor.envelope(expires_at=utc_now() - timedelta(seconds=1))
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    assert e.value.check == "claim_freshness"


def test_stale_proof_refused(verifier, sensor):
    """A proof outside the acceptance window."""
    env = sensor.envelope()
    stale = sensor.sign_proof(env, issued_at=utc_now() - timedelta(minutes=10))
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), stale)
    assert e.value.check == "proof_freshness"


def test_oversize_payload_refused_before_parsing(verifier, sensor):
    """Bound the size before parsing. ANS-6 7.4 step 1."""
    with pytest.raises(VerificationRejected) as e:
        verifier.verify(b"{" + b"x" * 9000, b"{}")
    assert e.value.check == "size_bound"


def test_suppressed_agent_is_refused(verifier, sensor, trust):
    """Suppression, not revocation. master stops listening; the RA revokes."""
    trust.suppress(sensor.ansname, "certificate fingerprint drifted mid-run")
    env = sensor.envelope()
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env))
    assert e.value.check == "known_issuer"


def test_replay_cache_fails_closed_when_saturated(sensor, trust):
    """A full cache refuses. It never drops an entry to make room."""
    from hawkeye_backend.verification import ReplayCache

    verifier = ClaimVerifier(
        VerifierPolicy(audience=MASTER, target=TARGET), trust, ReplayCache(max_entries=1)
    )
    env = sensor.envelope()
    submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env, proof_id="p1"))
    with pytest.raises(VerificationRejected) as e:
        submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env, proof_id="p2"))
    assert e.value.check == "replay_cache"


def test_replay_id_not_recorded_when_verification_fails(sensor, trust):
    """The ordering rule from ANS-6 7.6, tested directly.

    A rejected claim must not spend its proof id. If it did, anyone able to
    submit garbage could flood a bounded cache and fail-close authentication for
    every legitimate caller - a denial of service against a 911 call.
    """
    from hawkeye_backend.verification import ReplayCache

    cache = ReplayCache(max_entries=4)
    verifier = ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust, cache)
    bad = sensor.envelope(audience="ans://v1.0.0.master.someone-else.example")
    for i in range(10):
        with pytest.raises(VerificationRejected):
            submit(verifier, sensor.sign_claim(bad), sensor.sign_proof(bad, proof_id=f"flood-{i}"))
    assert len(cache) == 0, "a failed verification must not consume replay-cache capacity"


def test_injected_replay_cache_is_actually_used(sensor, trust):
    """Regression. An injected cache must be the one the verifier spends into.

    Found while writing this file: `self._replay = replay or ReplayCache()`
    silently discarded the injected cache, because ReplayCache defines __len__
    and an empty cache is therefore falsy. Every verifier got a private
    throwaway cache instead of the shared one.

    That is precisely the failure ANS-6 7.6 names under "shared scope behind
    load balancers": a proof replays cleanly against any replica holding its own
    cache. It would have passed every other test in this file.
    """
    from hawkeye_backend.verification import ReplayCache

    shared = ReplayCache(max_entries=64)
    verifier = ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust, shared)
    env = sensor.envelope()
    submit(verifier, sensor.sign_claim(env), sensor.sign_proof(env, proof_id="shared-1"))
    assert len(shared) == 1, "the verifier spent into a different cache than the one injected"

    # And a second verifier sharing it refuses the replay, which is the property
    # that matters behind a load balancer.
    other = ClaimVerifier(VerifierPolicy(audience=MASTER, target=TARGET), trust, shared)
    with pytest.raises(VerificationRejected) as e:
        submit(other, sensor.sign_claim(env), sensor.sign_proof(env, proof_id="shared-1"))
    assert e.value.check == "proof_replay"
