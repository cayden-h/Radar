"""agents/replay: append-only, hash-chained, and honest about the seal."""

from __future__ import annotations

from agents.replay import ReplayAgent


def test_the_chain_verifies_when_untouched():
    replay = ReplayAgent()
    replay.open_incident("i-1", "00-abc-def-01")
    replay.record(kind="claim", actor="agents/people", summary="breathing at 8 BPM")
    replay.record(kind="utterance", actor="agents/caller", summary="told the operator")

    intact, detail = replay.verify_chain()
    assert intact is True
    assert "chain intact" in detail


def test_altering_an_entry_is_detected():
    """What an investigator runs. Swatting investigations are entirely post-hoc."""
    replay = ReplayAgent()
    replay.open_incident("i-1", "00-abc-def-01")
    replay.record(kind="claim", actor="agents/people", summary="breathing at 8 BPM")

    tampered = replay.entries[1]
    object.__setattr__(tampered, "summary", "not breathing")

    intact, detail = replay.verify_chain()
    assert intact is False
    assert "altered since it was written" in detail


def test_a_discard_is_recorded_with_the_same_weight_as_an_acceptance():
    """"It tells you what it discarded" is the sentence that carries the submission."""
    from hawkeye_backend.models.verification import (
        Claim,
        SourceAgent,
        TrustProfile,
        VerificationDecision,
        VerificationResult,
    )

    replay = ReplayAgent()
    replay.record_verification(
        VerificationResult(
            verification_id="v-1",
            claim=Claim(claim_id="c-1", statement="armed", field="people.personhood", value="x"),
            agent=SourceAgent(
                name="agents/people",
                ansname="ans://v0.1.0.people.hawkeye.evil",
                recommended_profile=TrustProfile.UNTRUSTED,
            ),
            decision=VerificationDecision.DISCARDED,
            reason="certificate fingerprint differs from the one registered",
            will_be_spoken=False,
        )
    )

    entry = replay.entries[0]
    assert entry.kind == "discard"
    assert entry.detail["decision"] == "DISCARDED"
    assert replay.verify_chain()[0] is True


def test_the_seal_does_not_claim_a_receipt_it_does_not_have():
    """The chain is tamper-evident to whoever holds it. The log is what makes it
    verifiable by someone who does not, and that hop is not wired."""
    replay = ReplayAgent()
    replay.open_incident("i-1", "00-abc-def-01")

    seal = replay.seal()
    assert seal["transparency_receipt"] is None
    assert seal["algorithm"] == "sha256-chain"
