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


# --------------------------------------------------------------- the two decisions
#
# Decision A opens on motion alone. Decision B closes on the camera's own
# verdict. They are independent: neither reads the other's input.

from agents.core.observations import AgentObservation, Assertion
from agents.core.ports import FetchedObservation
from agents.master.agent import MasterAgent
from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.verification.envelope import Severity


class _Mesh:
    """An ObservationSource whose verification status the test controls."""

    def __init__(self) -> None:
        self._obs: dict[str, FetchedObservation] = {}

    def put(self, slug: str, obs: AgentObservation, *, verified: bool = True) -> None:
        self._obs[slug] = FetchedObservation(observation=obs, envelope_verified=verified)

    def drop(self, slug: str) -> None:
        self._obs.pop(slug, None)

    def fetch(self, slug: str) -> FetchedObservation | None:
        return self._obs.get(slug)


def _obs(slug: str, field: str, value: str, *, source: Source) -> AgentObservation:
    """An observation from `slug`, built without a roster lookup.

    `presence` does not join the roster until the rename lands, and the gate
    does no identity lookup of its own, so the fixture spells the names out.
    """
    name = f"agents/{slug}"
    ansname = f"ans://v{VERSION}.{slug}.batradar.club"
    return AgentObservation(
        agent=name,
        ansname=ansname,
        assertions=(
            Assertion(
                field=field,
                value=value,
                zone_scope=ROOM,
                severity_ceiling=Severity.ACTIONABLE,
                confidence=0.9,
                basis="test fixture",
                provenance=Provenance(
                    source=source,
                    producer=name,
                    ansname=ansname,
                    detail="test",
                ),
            ),
        ),
    )


def _motion() -> AgentObservation:
    return _obs("presence", "presence.motion", "true", source=Source.NEXMON_CSI)


def _vision(value: str) -> AgentObservation:
    return _obs("vision", "vision.occupancy", value, source=Source.CAMERA_UVC)


def _wired() -> tuple[MasterAgent, Shutter, _Mesh]:
    key = Ed25519PrivateKey.generate()
    shutter = _trusting_shutter(key)
    mesh = _Mesh()
    master = MasterAgent(mesh, shutter_client=_client(shutter, key))
    return master, shutter, mesh


def test_motion_alone_opens_the_lens() -> None:
    """Decision A, while armed. No roster in this path at all."""
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())

    master.tick()

    assert shutter.position == "open"


def test_no_person_closes_the_lens() -> None:
    """Decision B. The camera says the motion was not a person."""
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()

    mesh.put("vision", _vision("no_person"))
    master.tick()

    assert shutter.position == "closed"


def test_person_present_keeps_the_lens_open() -> None:
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()

    mesh.put("vision", _vision("person_present"))
    master.tick()

    assert shutter.position == "open"


def test_silent_vision_keeps_the_lens_open() -> None:
    """Closing on silence lets an attacker blind the camera by killing one
    agent. Open-on-failure is the safe direction, because opening has already
    been paid for by a verified grant."""
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()

    mesh.drop("vision")
    for _ in range(5):
        master.tick()

    assert shutter.position == "open"


def test_unverified_no_person_does_not_close_the_lens() -> None:
    """An unverified claim cannot retire a verified grant's effect."""
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()

    mesh.put("vision", _vision("no_person"), verified=False)
    master.tick()

    assert shutter.position == "open"


def test_a_long_vision_silence_raises_a_notice_for_the_resident() -> None:
    """There is no silence timeout, because a timeout is what an attacker who
    can kill vision wants. The condition is made loud instead."""
    master, _, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()
    mesh.drop("vision")

    for _ in range(MasterAgent.VISION_SILENT_NOTICE_TICKS + 2):
        obs = master.tick()

    assert obs.value("master.vision_silent") == "true"


# --------------------------------------------------------- the recording mark
#
# intruder's roster arithmetic runs downstream of vision, after recording has
# already started on motion alone. It cannot start a recording that is already
# running - what it can do is mark the segments already being written as
# corresponding to a confirmed-unaccounted presence, for replay to surface.


def _intruder(value: str, *, zone: str | None = ROOM) -> AgentObservation:
    """An `intruder.unexpected_presence` claim, with the zone it names when
    the clean (unambiguous) case applies."""
    name = "agents/intruder"
    ansname = f"ans://v{VERSION}.intruder.batradar.club"
    assertions = [
        Assertion(
            field="intruder.unexpected_presence",
            value=value,
            severity_ceiling=Severity.ACTIONABLE,
            confidence=0.8,
            basis="test fixture",
            provenance=Provenance(
                source=Source.AGENT_INFERENCE,
                producer=name,
                ansname=ansname,
                detail="test",
            ),
        )
    ]
    if zone is not None:
        assertions.append(
            Assertion(
                field="intruder.intruder_zone",
                value=zone,
                zone_scope=zone,
                severity_ceiling=Severity.ACTIONABLE,
                confidence=0.8,
                basis="test fixture",
                provenance=Provenance(
                    source=Source.AGENT_INFERENCE,
                    producer=name,
                    ansname=ansname,
                    detail="test",
                ),
            )
        )
    return AgentObservation(agent=name, ansname=ansname, assertions=tuple(assertions))


def test_a_confirmed_intruder_marks_the_open_recording() -> None:
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()
    mesh.put("vision", _vision("person_present"))
    master.tick()
    assert shutter.position == "open"

    mesh.put("intruder", _intruder("true"))
    obs = master.tick()

    assert obs.value("master.recording_marked") == "true"


def test_an_accounted_for_person_does_not_mark_the_recording() -> None:
    master, _, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()
    mesh.put("vision", _vision("person_present"))
    master.tick()

    mesh.put("intruder", _intruder("false"))
    obs = master.tick()

    assert obs.value("master.recording_marked") is None


def test_an_unverified_intruder_claim_does_not_mark_the_recording() -> None:
    """capped severity, the same rule that keeps an unverified vision claim
    from retiring a grant. A claim that never arrived over a verified
    transport must not mark a sealed record either."""
    master, _, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()
    mesh.put("vision", _vision("person_present"))
    master.tick()

    mesh.put("intruder", _intruder("true"), verified=False)
    obs = master.tick()

    assert obs.value("master.recording_marked") is None


def test_a_confirmed_intruder_does_not_mark_a_room_with_no_open_recording() -> None:
    """intruder names a room master never opened a lens in. Nothing there to
    mark, and nothing gets marked."""
    master, _, mesh = _wired()

    mesh.put("intruder", _intruder("true"))
    obs = master.tick()

    assert obs.value("master.recording_marked") is None


# ------------------------------------------------------------- security mode
#
# Motion has always opened the shutter unconditionally. Adding a human
# arm/disarm switch means a disarmed house sees the same motion and does
# nothing with it - the safe default, since automation should never be the
# thing that decides to start watching.


def test_disarmed_by_default() -> None:
    master, _, _ = _wired()
    assert master.security_mode is False


def test_motion_does_not_open_the_lens_while_disarmed() -> None:
    master, shutter, mesh = _wired()
    mesh.put("presence", _motion())

    master.tick()

    assert shutter.position == "closed"


def test_arming_lets_motion_open_the_lens() -> None:
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())

    master.tick()

    assert shutter.position == "open"


def test_disarming_does_not_close_an_already_open_lens() -> None:
    """Disarming turns off future opens. It is not a substitute for the
    resident's own close-from-the-app control, and must not fight it."""
    master, shutter, mesh = _wired()
    master.set_security_mode(True)
    mesh.put("presence", _motion())
    master.tick()
    assert shutter.position == "open"

    master.set_security_mode(False)
    master.tick()

    assert shutter.position == "open"


def test_security_mode_is_reported_on_the_observation() -> None:
    master, _, _ = _wired()

    disarmed = master.tick()
    assert disarmed.value("master.security_mode") == "false"

    master.set_security_mode(True)
    armed = master.tick()
    assert armed.value("master.security_mode") == "true"
