"""The wire, end to end, over real HTTP. The test that proves rather than assumes.

Every other test in this suite exercises domain logic and takes verification as
given. This one stands up `agents/people` as an actual ASGI app, has `master`
fetch from it over A2A, and verifies every claim against the key `people`
publishes in its own trust card.

That is the whole submission in one file: a claim crossing a hop, verified
against a domain-anchored identity, and refused when anything about it is wrong.

The impostor tests are the important half. A system that accepts good claims is
unremarkable; one that refuses a well-formed claim from the wrong agent is the
thing being judged.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.models.incident import IncidentType
from hawkeye_backend.verification import ClaimVerifier, TrustStore, VerifierPolicy
from hawkeye_backend.verification.trust import KnownAgent

from agents.caller import CallerAgent
from agents.core import cards
from agents.core.identity import identity
from agents.core.keys import load_or_create
from agents.core.runtime import build_app
from agents.core.signing import ClaimSigner
from agents.core.transport import CLAIM_TARGET_PATH, A2AObservationSource, Peer
from agents.master import MasterAgent
from agents.people import PeopleAgent

MASTER = identity("master")
PEOPLE = identity("people")
TARGET = f"{MASTER.base_url}{CLAIM_TARGET_PATH}"


# ----------------------------------------------------------------- the harness


@pytest.fixture(scope="module")
def people_key(tmp_path_factory) -> Ed25519PrivateKey:
    """A real key on disk, created once, stable across restarts within the test.

    `tmp_path` rather than the shared key directory, so a test run never mints
    an identity a later real deployment would be stale against.
    """
    return load_or_create("people", root=tmp_path_factory.mktemp("keys"))


@pytest.fixture(scope="module")
def people_app(people_key):
    """agents/people, running, signing, and serving /a2a.

    Module-scoped because warming the rolling baseline costs 130 simulated
    seconds and none of these tests mutate the agent's state - they only fetch
    from it. Verification is stateless per claim, so sharing the producer across
    them tests exactly the same thing.
    """
    from agents.core.dev import StaticRoster, SyntheticCsiFeed

    from .conftest import ZONES

    feed = SyntheticCsiFeed(ZONES)
    agent = PeopleAgent(feed, StaticRoster())
    feed.occupy("main_bedroom", bpm=15.0)
    for _ in range(130):
        feed.advance(1)
        agent.run_once()
    return build_app(agent, signer=ClaimSigner(PEOPLE, people_key))


def source_over(app, store: TrustStore, *, ansname: str = PEOPLE.ansname) -> A2AObservationSource:
    """A master-side source that talks to `app` in-process over ASGI.

    Real HTTP semantics, real JSON serialization, real bytes - which is the
    point, because the failure this transport is designed around is a signature
    breaking when something re-serializes a claim in the middle.
    """
    peers = {"people": Peer(slug="people", base_url="http://people.test", ansname=ansname)}
    verifier = ClaimVerifier(
        policy=VerifierPolicy(audience=MASTER.ansname, target=TARGET),
        trust=store,
    )
    src = A2AObservationSource(peers, verifier, audience=MASTER.ansname, target=TARGET)
    # TestClient is a sync httpx.Client over an ASGI app, which is what this
    # needs: httpx's own ASGITransport is async-only, and the source is
    # deliberately synchronous so `tick` stays a plain function.
    src._client = TestClient(app, base_url="http://people.test")
    return src


def store_with(key: Ed25519PrivateKey, *, ansname: str = PEOPLE.ansname) -> TrustStore:
    store = TrustStore()
    store.register(
        KnownAgent(
            ansname=ansname,
            public_key=key.public_key(),
            profile=PEOPLE.profile,
            certificate_version="0.1.0",
        )
    )
    return store


# ------------------------------------------------------------- the happy path


def test_a_claim_crosses_the_hop_and_verifies(people_app, people_key):
    """The whole point, in one assertion: signed there, verified here."""
    source = source_over(people_app, store_with(people_key))
    fetched = source.fetch("people")

    assert fetched is not None
    assert fetched.envelope_verified is True
    assert fetched.rejected == ()
    assert any(a.field == "people.personhood" for a in fetched.observation.assertions)


def test_the_signed_bytes_survive_the_json_layer(people_app, people_key):
    """The trap this transport is built around.

    Claims cross as opaque JSON strings rather than nested objects. If anything
    parsed and re-serialized them, every signature would fail and it would look
    exactly like tampering.
    """
    source = source_over(people_app, store_with(people_key))
    fetched = source.fetch("people")

    assert fetched.envelope_verified is True, "re-serialization would break every signature"


def test_master_speaks_only_once_the_wire_verifies(people_app, people_key):
    """`envelope_verified` going true is the single observable that this works."""
    source = source_over(people_app, store_with(people_key))
    master = MasterAgent(source)
    master.run_once()

    assert master.admitted, "claims reached the gate"
    assert any(c.spoken for c in master.admitted), "and at least one may be spoken"

    lines = CallerAgent(source, master).opening_report(IncidentType.FIRE, "1 Fictional Way")
    assert not any("will not repeat anything I cannot verify" in line.text for line in lines)


# ----------------------------------------------------------------- the refusals


def test_a_claim_signed_by_the_wrong_key_is_discarded(people_app):
    """An impostor at the right ANSName, holding a key nobody registered.

    This is the Infinite Impostor in its simplest form: everything about the
    claim is well formed, and the only defect is that the signer is not who the
    registry says it is.
    """
    source = source_over(people_app, store_with(Ed25519PrivateKey.generate()))
    fetched = source.fetch("people")

    assert fetched.envelope_verified is False
    assert fetched.observation.assertions == ()
    assert fetched.rejected
    assert all(r.check == "claim_signature" for r in fetched.rejected)


def test_an_unregistered_agent_is_refused_entirely(people_app, people_key):
    """An empty trust store is not an empty guest list. Unknown means refused."""
    source = source_over(people_app, TrustStore())
    fetched = source.fetch("people")

    assert fetched.envelope_verified is False
    assert all(r.check == "known_issuer" for r in fetched.rejected)


def test_a_lookalike_ansname_is_caught(people_app, people_key):
    """`people.batradar-secure.club` answering for `people.batradar.club`.

    The demo's refusal beat. Caught twice on purpose: the trust store does not
    hold the lookalike name, and the transport separately refuses a peer that
    answers under a name master did not register it with.
    """
    lookalike = "ans://v0.1.0.people.batradar-secure.club"
    source = source_over(people_app, store_with(people_key, ansname=lookalike), ansname=lookalike)
    fetched = source.fetch("people")

    assert fetched.envelope_verified is False
    assert any(r.check == "peer_identity" for r in fetched.rejected)


def test_master_records_the_transport_discard_in_the_feed(people_app):
    """A claim refused at the wire must still be visible as a discard.

    Otherwise the most interesting class of discard - a failed signature, which
    is an attack rather than a policy - is the one class that never appears.
    """
    source = source_over(people_app, store_with(Ed25519PrivateKey.generate()))
    master = MasterAgent(source)
    master.run_once()

    assert master.discarded, "the refusal reached the verification feed"
    assert any(d.checks and not d.checks[0].passed for d in master.discarded)


def test_nothing_is_spoken_when_the_source_cannot_be_verified(people_app):
    """The rule, under the condition it exists for."""
    source = source_over(people_app, store_with(Ed25519PrivateKey.generate()))
    master = MasterAgent(source)
    master.run_once()

    assert all(not c.spoken for c in master.admitted)
    lines = CallerAgent(source, master).opening_report(IncidentType.FIRE, "1 Fictional Way")
    assert any("will not repeat anything I cannot verify" in line.text for line in lines)


# ------------------------------------------------------------ the challenge


def test_every_fetch_issues_a_fresh_challenge(people_app, people_key):
    """Two fetches, two nonces, and no claim usable against the other.

    This is what makes the mesh pull-only: an agent cannot prepare a usable
    claim in advance, because it cannot guess the challenge it will be asked.
    """
    source = source_over(people_app, store_with(people_key))
    first = source.fetch("people")
    second = source.fetch("people")

    assert first.envelope_verified and second.envelope_verified
    firsts = {a.provenance.detail for a in first.observation.assertions}
    seconds = {a.provenance.detail for a in second.observation.assertions}
    assert firsts.isdisjoint(seconds), "claim ids are fresh per challenge, so nothing is replayed"


def test_a_replayed_claim_is_refused(people_app, people_key):
    """The same proof presented twice. Battery #1, over the real wire.

    The replay cache lives on the verifier, so a claim captured off the wire and
    resubmitted is spent even if everything about it still verifies.
    """
    source = source_over(people_app, store_with(people_key))
    fetched = source.fetch("people")
    assert fetched.envelope_verified

    # Reach past the source and resubmit one claim's exact bytes.
    response = source._client.post(
        CLAIM_TARGET_PATH,
        json={
            "jsonrpc": "2.0",
            "id": "replay",
            "method": "hawkeye.observe",
            "params": {
                "audience": MASTER.ansname,
                "nonce": "chal-replay",
                "incident_id": "steady-state",
                "target": TARGET,
            },
        },
    )
    wire = response.json()["result"]["claims"][0]
    from hawkeye_backend.verification import VerificationRejected

    source._verifier.verify(
        wire["claim"].encode(), wire["proof"].encode(), expected_nonce="chal-replay"
    )
    with pytest.raises(VerificationRejected) as exc:
        source._verifier.verify(
            wire["claim"].encode(), wire["proof"].encode(), expected_nonce="chal-replay"
        )
    assert exc.value.check == "proof_replay"


# --------------------------------------------------------------- the card path


def test_the_trust_store_can_be_built_from_a_published_card(people_key):
    """Discovery: acceptance ties to the same document the judge's verifier reads.

    A hardcoded key list would verify signatures perfectly and prove nothing
    about identity, because the keys would be trusted for having been typed in.
    """
    from agents.core.discovery import _agent_from_card

    card = cards.build_trust_card(
        PEOPLE,
        public_key_b64=ClaimSigner(PEOPLE, people_key).public_key_b64,
        kid="k",
        agent_id="a",
    )
    known = _agent_from_card(card, profile=PEOPLE.profile)

    assert known.ansname == PEOPLE.ansname
    assert known.thumbprint == ClaimSigner(PEOPLE, people_key).thumbprint
