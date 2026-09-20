"""The shutter: a grant crosses a hop, and a piece of plastic moves or does not.

Every other agent in this package answers a question. This one takes an order,
and that inversion is why it is the agent worth testing hardest: the seven
refusals below are the submission. A system that opens a camera shield for a
valid grant is unremarkable. One that refuses a well-formed, correctly signed
grant from the wrong issuer - and leaves the lens covered - is the thing being
judged.

Nothing here touches hardware. The GPIO write sits behind a backend the tests
substitute, so the whole gate is provable on a laptop with no servo attached,
which is what `TASKS.md` T14 asks for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.models.common import (
    MEASURED_SOURCES,
    Source,
    SourceClass,
    classify_source,
    utc_now,
)
from hawkeye_backend.models.verification import TrustProfile, VerificationDecision
from hawkeye_backend.verification import ClaimVerifier, TrustStore, VerifierPolicy

from hawkeye_backend.verification.trust import KnownAgent

from agents.core.identity import VERSION, identity
from agents.core.runtime import build_app
from agents.core.signing import ClaimSigner
from agents.shutter.agent import ShutterAgent
from agents.shutter.selftest import sweep
from agents.shutter.pigpio_backend import (
    MAX_PULSE_US,
    MIN_PULSE_US,
    PigpioShutter,
    pulse_width_us,
)
from agents.shutter import (
    CLOSED_ANGLE,
    OPEN_ANGLE,
    GrantEnvelope,
    GrantRefused,
    Refusal,
    Shutter,
    StubShutter,
    sign_grant,
)
from agents.shutter.challenge import ChallengeBook


# ------------------------------------------------------------------ the nonce
#
# `shutter` issues the nonce, not `master`. Everywhere else in the mesh master
# asks and sensing agents answer, so master holds the nonce; here master is the
# one asking for something to happen, so the verifier holds it. The invariant
# the pull-only rule was protecting is "the verifier issues the challenge", and
# it survives the inversion intact. See `shutter/CLAUDE.md`.


def test_a_nonce_is_spent_by_the_first_grant_that_uses_it() -> None:
    """Single use. The second presentation of the same nonce is not a nonce."""
    book = ChallengeBook()
    nonce = book.issue()

    assert book.spend(nonce) is True
    assert book.spend(nonce) is False


def test_a_nonce_nobody_issued_is_not_spendable() -> None:
    """"The verifier did not ask for one" and "this is not one" are the same refusal."""
    assert ChallengeBook().spend("shut-obviously-made-up") is False


def test_a_nonce_expires() -> None:
    """Ten seconds. A challenge that outlives the situation is a replay window."""
    issued = datetime(2026, 9, 19, 3, 0, 0, tzinfo=UTC)
    book = ChallengeBook(ttl=timedelta(seconds=10))
    nonce = book.issue(now=issued)

    assert book.spend(nonce, now=issued + timedelta(seconds=9)) is True

    again = book.issue(now=issued)
    assert book.spend(again, now=issued + timedelta(seconds=11)) is False


# ------------------------------------------------------------------ the harness


@pytest.fixture
def master_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def trust(master_key: Ed25519PrivateKey) -> TrustStore:
    """A store holding exactly one agent: `master`, at the key it published.

    The key comes from master's own trust card in the real path. Here it comes
    from the fixture, and the distinction the tests care about is that it is
    *looked up by ANSName* rather than configured as "the key that is allowed",
    which is what makes `unregistered_issuer` a real check.
    """
    return TrustStore(
        [
            KnownAgent(
                ansname=identity("master").ansname,
                public_key=master_key.public_key(),
                profile=TrustProfile.FIDUCIARY,
                certificate_version=VERSION,
            )
        ]
    )


@pytest.fixture
def shutter(trust: TrustStore) -> Shutter:
    """A shutter with a stub servo. No hardware, and the gate is the same gate."""
    return Shutter(trust=trust, backend=StubShutter())


def grant_bytes(
    key: Ed25519PrivateKey,
    *,
    nonce: str,
    issuer: str | None = None,
    action: str = "open",
    reason: str = "intr-0001",
    incident_id: str | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> bytes:
    """What `master` puts on the wire. Bytes, because bytes are what is verified."""
    now = now or utc_now()
    return sign_grant(
        key,
        GrantEnvelope(
            nonce=nonce,
            issuer=issuer or identity("master").ansname,
            action=action,
            reason=reason,
            incident_id=incident_id,
            issued_at=now,
            expires_at=expires_at or (now + timedelta(seconds=5)),
        ),
    )


# --------------------------------------------------------------- the happy path


def test_a_verified_grant_moves_the_shield(shutter: Shutter, master_key) -> None:
    """The gate is a gate and not a brick.

    Every other test in this file asserts the shield did not move. This one
    exists so that those tests mean something: a shutter that refused
    everything would pass all seven refusals and be useless.
    """
    nonce = shutter.challenge()

    result = shutter.open(grant_bytes(master_key, nonce=nonce))

    assert result.position == "open"
    assert shutter.backend.angle == OPEN_ANGLE


# ------------------------------------------------------------- the seven refusals
#
# Each one leaves the servo exactly where it was, and each one says why. A
# refusal is not an error: it is an observation, it is signed, and it goes into
# the sealed record. That is the demo beat - the lens stays covered and the
# agent explains itself.


def test_a_grant_signed_by_the_wrong_key_leaves_the_lens_covered(shutter: Shutter) -> None:
    """Right name, wrong key. The impostor's own signature verifies perfectly.

    This is the shape that matters most: the grant is well-formed and its
    signature is internally valid. It is refused because the key is not the one
    `master`'s published trust card carries, which is the whole argument for
    anchoring identity outside the application.
    """
    impostor = Ed25519PrivateKey.generate()
    nonce = shutter.challenge()

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(impostor, nonce=nonce))

    assert refused.value.refusal is Refusal.UNREGISTERED_ISSUER
    assert shutter.backend.angle == CLOSED_ANGLE
    assert shutter.backend.history == []


def test_a_lookalike_ansname_leaves_the_lens_covered(shutter: Shutter, master_key) -> None:
    """A name one character off, signed by a key that is genuinely its own.

    Caught at the name, before any cryptography runs, because this is a naming
    attack rather than a signing one. `master` and `rnaster` are different
    agents and the only thing that says so is the registry.
    """
    nonce = shutter.challenge()
    lookalike = identity("master").ansname.replace("master", "rnaster")

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce=nonce, issuer=lookalike))

    assert refused.value.refusal is Refusal.LOOKALIKE_ANSNAME
    assert shutter.backend.angle == CLOSED_ANGLE


def test_a_nonce_the_shutter_never_issued_leaves_the_lens_covered(
    shutter: Shutter, master_key
) -> None:
    """A perfectly signed grant answering a question nobody asked."""
    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce="shut-never-issued-this"))

    assert refused.value.refusal is Refusal.STALE_NONCE
    assert shutter.backend.angle == CLOSED_ANGLE


def test_a_nonce_cannot_be_spent_twice(shutter: Shutter, master_key) -> None:
    """The second grant is a different grant. The nonce is still gone."""
    nonce = shutter.challenge()
    shutter.open(grant_bytes(master_key, nonce=nonce, reason="intr-0001"))

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce=nonce, reason="intr-0002"))

    assert refused.value.refusal is Refusal.STALE_NONCE
    assert shutter.backend.history == [OPEN_ANGLE]


def test_an_expired_nonce_leaves_the_lens_covered(trust: TrustStore, master_key) -> None:
    """Ten seconds. The round trip it covers is measured in milliseconds."""
    shutter = Shutter(trust=trust, backend=StubShutter())
    issued = datetime(2026, 9, 19, 3, 0, 0, tzinfo=UTC)
    nonce = shutter.challenge(now=issued)
    late = issued + timedelta(seconds=11)

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce=nonce, now=late), now=late)

    assert refused.value.refusal is Refusal.STALE_NONCE
    assert shutter.backend.angle == CLOSED_ANGLE


def test_a_byte_identical_replay_leaves_the_lens_covered(shutter: Shutter, master_key) -> None:
    """The same bytes, twice. Refused as a replay, not as a stale nonce.

    Both refusals are correct here and the specific one is the useful one: the
    record should say someone captured a grant and sent it again, rather than
    the generic finding that would swallow it.
    """
    nonce = shutter.challenge()
    raw = grant_bytes(master_key, nonce=nonce)
    shutter.open(raw)

    with pytest.raises(GrantRefused) as refused:
        shutter.open(raw)

    assert refused.value.refusal is Refusal.REPLAYED_GRANT
    assert shutter.backend.history == [OPEN_ANGLE]


def test_an_expired_grant_leaves_the_lens_covered(shutter: Shutter, master_key) -> None:
    """Fresh nonce, dead grant. A grant that outlives its situation is a replay."""
    issued = datetime(2026, 9, 19, 3, 0, 0, tzinfo=UTC)
    nonce = shutter.challenge(now=issued)
    raw = grant_bytes(
        master_key, nonce=nonce, now=issued, expires_at=issued + timedelta(seconds=2)
    )

    with pytest.raises(GrantRefused) as refused:
        shutter.open(raw, now=issued + timedelta(seconds=3))

    assert refused.value.refusal is Refusal.EXPIRED_GRANT
    assert shutter.backend.angle == CLOSED_ANGLE


def test_an_unknown_action_leaves_the_lens_covered(shutter: Shutter, master_key) -> None:
    """There is no third action, and an unrecognised one does not fall through to a default."""
    nonce = shutter.challenge()

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce=nonce, action="ajar"))

    assert refused.value.refusal is Refusal.UNKNOWN_ACTION
    assert shutter.backend.angle == CLOSED_ANGLE


def test_an_untrusted_profile_leaves_the_lens_covered(master_key) -> None:
    """A real `master`, a valid signature, and a Trust Index verdict of UNTRUSTED.

    Discovery suppression, not revocation. `shutter` declining to act on this
    one command is a local decision; only the RA revokes a certificate, and
    nothing here pretends otherwise.
    """
    untrusted = TrustStore(
        [
            KnownAgent(
                ansname=identity("master").ansname,
                public_key=master_key.public_key(),
                profile=TrustProfile.UNTRUSTED,
                certificate_version=VERSION,
            )
        ]
    )
    shutter = Shutter(trust=untrusted, backend=StubShutter())
    nonce = shutter.challenge()

    with pytest.raises(GrantRefused) as refused:
        shutter.open(grant_bytes(master_key, nonce=nonce))

    assert refused.value.refusal is Refusal.UNTRUSTED_PROFILE
    assert shutter.backend.angle == CLOSED_ANGLE


# ------------------------------------------------------------------- the wire
#
# Everything above calls the gate directly. These two stand the agent up as a
# real ASGI app and push a grant through the JSON-RPC layer, because the trap
# this whole design is built around only exists on the wire.


@pytest.fixture
def client(trust: TrustStore) -> TestClient:
    """The agent as a real ASGI app.

    With a signer, always. An agent with no signer serves no `/a2a` at all by
    design, and for this one that rule bites harder than for the others: a
    refusal is an observation that has to be signed before it can go into the
    sealed record, so an unsigned shutter could refuse but could not prove it.
    """
    agent = ShutterAgent(trust=trust, backend=StubShutter())
    signer = ClaimSigner(identity("shutter"), Ed25519PrivateKey.generate())
    return TestClient(build_app(agent, signer=signer))


def rpc(client: TestClient, method: str, **params) -> dict:
    body = {"jsonrpc": "2.0", "id": "t-1", "method": method, "params": params}
    return client.post("/a2a", json=body).json()


def test_the_signed_bytes_survive_the_json_layer(client: TestClient, master_key) -> None:
    """The trap this design is built around.

    A grant crosses as an opaque JSON **string**, never a nested object. If any
    layer parsed and re-serialized it, the signature would no longer verify over
    what arrives and the failure would look exactly like tampering - which is to
    say, like the one thing this agent exists to detect.
    """
    nonce = rpc(client, "shutter.challenge")["result"]["nonce"]
    raw = grant_bytes(master_key, nonce=nonce)

    result = rpc(client, "shutter.open", grant=raw.decode())["result"]

    assert result["position"] == "open", "re-serialization would break every signature"


def test_a_refusal_crosses_the_wire_as_a_refusal_not_an_error(client: TestClient) -> None:
    """A refusal is an observation, and observations are results.

    Returning a JSON-RPC error here would be the wrong shape twice over: it
    would make a successful defence look like a malfunction, and it would leave
    the reason somewhere a sealed record cannot reach.
    """
    nonce = rpc(client, "shutter.challenge")["result"]["nonce"]
    raw = grant_bytes(Ed25519PrivateKey.generate(), nonce=nonce)

    body = rpc(client, "shutter.open", grant=raw.decode())

    assert "error" not in body
    assert body["result"]["position"] == "closed"
    assert body["result"]["refusal"] == Refusal.UNREGISTERED_ISSUER


# --------------------------------------------------------------- the honesty rule
#
# Root CLAUDE.md: a limit is carried in the data itself, not only in a comment,
# and a scoped claim must not be presentable as an unscoped one by accident.
# There are two of those here and they are different limits: a servo with no
# position feedback, and a servo that does not exist.


def test_a_stub_backed_shutter_says_so_in_the_claim(trust: TrustStore) -> None:
    """A shield made of a number must never present as a shield made of plastic.

    This is the half-flipped state `docs/swapping-in-real-parts.md` warns about:
    a shutter reporting `open` on a machine with no servo attached looks
    identical, in every field that matters, to one reporting `open` on the Pi.
    The provenance is what keeps them apart, and it is computed rather than
    asserted, so this agent could not claim otherwise if it tried.
    """
    agent = ShutterAgent(trust=trust, backend=StubShutter())

    position = agent.tick().assertions[0]

    assert position.field == "shutter.position"
    assert position.provenance.simulated is True


def test_the_position_is_never_claimed_as_measured(trust: TrustStore) -> None:
    """The SG92R is open-loop. A commanded angle is not a measured one.

    A shield that jammed would attest open while covering the lens, and the only
    thing that catches that is the frame itself being dark. So the claim must
    not be readable as a measurement even on the Pi, with the real pin driven.
    Asserted against the class rather than an instance, because constructing a
    `PigpioShutter` needs a servo and this property must hold without one.
    """
    assert PigpioShutter.source is Source.SERVO_GPIO
    assert classify_source(Source.SERVO_GPIO) is SourceClass.DERIVED
    assert Source.SERVO_GPIO not in MEASURED_SOURCES

    basis = ShutterAgent(trust=trust, backend=StubShutter()).tick().assertions[0].basis
    assert "commanded" in basis


# ---------------------------------------------------------------- the real pin
#
# The driver itself needs a servo and a daemon, so it is not tested here. Its
# one piece of arithmetic is, because a pulse width outside the SG92R's range
# buzzes and draws current without moving - which is the stall condition that
# browns out the Pi, and it presents as the whole capture path dying for no
# visible reason rather than as anything mentioning a servo.


def test_the_closed_and_open_angles_land_inside_the_servos_pulse_range() -> None:
    for angle in (CLOSED_ANGLE, OPEN_ANGLE):
        assert MIN_PULSE_US <= pulse_width_us(angle) <= MAX_PULSE_US


def test_an_angle_outside_the_servos_travel_is_refused_rather_than_clamped() -> None:
    """Clamping would turn a caller's bug into a servo quietly at the wrong place."""
    with pytest.raises(ValueError, match="outside"):
        pulse_width_us(270)


def test_the_control_methods_share_an_endpoint_with_hawkeye_observe(trust: TrustStore) -> None:
    """One `/a2a`, three methods, and `master` needs all of them.

    `shutter` is the only agent that both answers a question and takes an order,
    so it is the only one whose A2A endpoint carries more than `hawkeye.observe`.
    They have to be the same endpoint: it is the one our card publishes and the
    one `agent.webmesh.ai verify_agent` sends its live message to. Two routers
    both claiming `POST /a2a` would silently resolve to whichever registered
    first, and the loser's methods would come back as `unknown method`.
    """
    agent = ShutterAgent(trust=trust, backend=StubShutter())
    signer = ClaimSigner(identity("shutter"), Ed25519PrivateKey.generate())
    client = TestClient(build_app(agent, signer=signer))
    agent.run_once()

    assert "nonce" in rpc(client, "shutter.challenge")["result"]

    observed = rpc(
        client,
        "hawkeye.observe",
        audience=identity("master").ansname,
        nonce="chal-abc",
        target=f"{identity('shutter').base_url}/a2a",
    )

    assert "error" not in observed, observed
    assert observed["result"]["claims"], "master cannot read the shield position"


def test_a_refusal_comes_back_signed(trust: TrustStore) -> None:
    """A refusal is an observation, and observations are signed.

    This is what makes the refusal evidence rather than an assertion. An
    unsigned "I refused" in a log proves nothing to anyone who was not already
    trusting us; a signed one, bound to the nonce of the grant it refused, is
    something an investigator can check months later against the key our card
    published. The sealed record is the whole point of the refusal path.
    """
    agent = ShutterAgent(trust=trust, backend=StubShutter())
    key = Ed25519PrivateKey.generate()
    client = TestClient(build_app(agent, signer=ClaimSigner(identity("shutter"), key)))

    nonce = rpc(client, "shutter.challenge")["result"]["nonce"]
    raw = grant_bytes(Ed25519PrivateKey.generate(), nonce=nonce)
    result = rpc(client, "shutter.open", grant=raw.decode())["result"]

    assert result["refusal"] == Refusal.UNREGISTERED_ISSUER

    verifier = ClaimVerifier(
        policy=VerifierPolicy(
            audience=identity("master").ansname,
            target=f"{identity('shutter').base_url}/a2a",
        ),
        trust=TrustStore(
            [
                KnownAgent(
                    ansname=identity("shutter").ansname,
                    public_key=key.public_key(),
                    profile=TrustProfile.TRANSACTIONAL,
                    certificate_version=VERSION,
                )
            ]
        ),
    )
    outcome = verifier.verify(
        result["observation"]["claim"].encode(),
        result["observation"]["proof"].encode(),
        expected_nonce=nonce,
    )

    # ATTRIBUTED rather than ASSERTED, and that is the roster working. `shutter`
    # is TRANSACTIONAL: it asserts one physical fact about one piece of plastic,
    # so what it says is relayed as a reported observation rather than as
    # something the system stands behind. An ASSERTED refusal would mean this
    # agent's word carried further than a shield position should.
    assert outcome.decision is VerificationDecision.ATTRIBUTED
    assert "shutter" in outcome.reason


# ------------------------------------------------------------------ the selftest
#
# T21's done-when names a command that moves a real servo. The movement needs
# hardware; the sequence does not, and the sequence is the part that can be
# wrong in a way that wastes a bring-up session.


def test_the_selftest_returns_the_shield_to_closed() -> None:
    """It must not leave the lens uncovered when it finishes.

    A bring-up script that ends with the shield open is a bring-up script that
    leaves a camera watching a room, and it would be easy not to notice on a
    bench with no shield glued on yet.
    """
    backend = StubShutter()

    sweep(backend)

    assert backend.history[-1] == CLOSED_ANGLE
    assert OPEN_ANGLE in backend.history, "a selftest that never opens tests nothing"
