"""master's shutter decisions.

The refractory lock is the test that protects the physical demo: an oscillating
SG92R stalls over 700mA and browns out the Pi.
"""

from __future__ import annotations

from agents.master.episode import CLEAR_TICKS_TO_RELEASE, ShutterEpisode

ROOM = "living_room"


def test_motion_on_a_closed_shutter_opens_it() -> None:
    episode = ShutterEpisode()
    assert episode.on_motion(ROOM) is True


def test_motion_while_already_open_does_not_re_open() -> None:
    """Re-issuing an open grant for an already-open lens is a wasted servo
    command and a wasted nonce."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    assert episode.on_motion(ROOM) is False


def test_benign_close_locks_out_immediate_re_open() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion(ROOM) is False


def test_lock_releases_after_enough_clear_ticks() -> None:
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is True


def test_motion_during_the_lock_restarts_the_clear_count() -> None:
    """A fan that keeps tripping motion must never accumulate clear ticks
    between gusts and slip past the lock."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False  # still locked, and this resets it
    for _ in range(CLEAR_TICKS_TO_RELEASE - 1):
        episode.on_clear(ROOM)
    assert episode.on_motion(ROOM) is False


def test_the_lock_is_per_room() -> None:
    """A locked living room must not suppress an open for the kitchen."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    assert episode.on_motion("kitchen") is True


def test_motion_flood_is_bounded() -> None:
    """The brownout guard. 500 ticks of unbroken motion must produce a small,
    bounded number of open commands, not one per tick."""
    episode = ShutterEpisode()
    opens = 0
    for _ in range(500):
        if episode.on_motion(ROOM):
            opens += 1
            episode.opened(ROOM)
            episode.closed(ROOM)
    assert opens == 1, f"servo commanded {opens} times under continuous motion"


def test_suppression_reason_is_reportable() -> None:
    """A suppressed open is evidence, not a gap. master puts this string in the
    discard feed so the replay console shows the suppression."""
    episode = ShutterEpisode()
    episode.on_motion(ROOM)
    episode.opened(ROOM)
    episode.closed(ROOM)
    episode.on_clear(ROOM)
    episode.on_motion(ROOM)
    reason = episode.suppression_reason(ROOM)
    assert reason is not None
    assert str(CLEAR_TICKS_TO_RELEASE) in reason


# ----------------------------------------------------------- the grant-issuing path
#
# `master` had never issued a grant: `sign_grant` was called only from
# `test_shutter.py`. These exercise the path from master's side, against the
# real gate, so the refusal is tested from both ends rather than only the one
# that owns the servo.

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.models.verification import TrustProfile

from agents.core.identity import VERSION, identity
from hawkeye_backend.verification import TrustStore
from hawkeye_backend.verification.trust import KnownAgent
from agents.master.shutter_client import GRANT_TTL, LocalShutterClient
from agents.shutter.backend import StubShutter
from agents.shutter.shutter import Shutter


def _trusting_shutter(key: Ed25519PrivateKey) -> Shutter:
    """A real gate on a stub servo, trusting `master` at the given key."""
    store = TrustStore(
        [
            KnownAgent(
                ansname=identity("master").ansname,
                public_key=key.public_key(),
                profile=TrustProfile.FIDUCIARY,
                certificate_version=VERSION,
            )
        ]
    )
    return Shutter(trust=store, backend=StubShutter())


def _client(shutter: Shutter, key: Ed25519PrivateKey) -> LocalShutterClient:
    return LocalShutterClient(shutter, key=key, issuer=identity("master").ansname)


def test_open_grant_moves_the_real_shutter() -> None:
    """End to end against the real gate: master signs, shutter verifies."""
    key = Ed25519PrivateKey.generate()
    shutter = _trusting_shutter(key)

    attestation = _client(shutter, key).request(action="open", reason="motion:c-1")

    assert attestation is not None
    assert attestation.position == "open"


def test_close_grant_moves_it_back() -> None:
    key = Ed25519PrivateKey.generate()
    shutter = _trusting_shutter(key)
    client = _client(shutter, key)
    client.request(action="open", reason="motion:c-1")

    attestation = client.request(action="close", reason="vision:v-9")

    assert attestation is not None
    assert attestation.position == "closed"


def test_a_grant_signed_by_the_wrong_key_is_refused() -> None:
    """The refusal path. This is the submission, so it is tested from master's
    side too and not only from the shutter's."""
    shutter = _trusting_shutter(Ed25519PrivateKey.generate())
    impostor = Ed25519PrivateKey.generate()

    assert _client(shutter, impostor).request(action="open", reason="motion:c-1") is None
    assert shutter.position == "closed"


def test_each_grant_gets_a_fresh_nonce() -> None:
    """A reused nonce is a replay. The client must ask for a new challenge per
    grant rather than caching one."""
    key = Ed25519PrivateKey.generate()
    client = _client(_trusting_shutter(key), key)

    client.request(action="open", reason="motion:c-1")
    client.request(action="close", reason="vision:v-1")

    assert len(client.nonces_used) == 2
    assert len(set(client.nonces_used)) == 2


def test_grant_ttl_is_seconds_not_minutes() -> None:
    """A grant that outlives the situation that produced it is a replay
    waiting to happen."""
    from datetime import timedelta

    assert GRANT_TTL <= timedelta(seconds=30)
