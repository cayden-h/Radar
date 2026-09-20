"""Development fixtures: a synthetic CSI feed and a static roster.

**These are not the demo.** The demo runs on replayed CSI captured at the house,
because real walls and a real fall are the only honest venue for the physical
claims. This file exists so the agent layer can be written, run and tested
before any hardware is brought up - which is deliberate sequencing rather than a
shortcut: the agent layer must never block on the hardware.

Everything produced here carries `ruview-sim` as its source, which `Provenance`
classifies as SIMULATED. An agent reading this feed cannot present its output as
measured, and the app renders a badge off the same computed field.

`docs/swapping-in-real-parts.md` is the switchboard for every mock in the
project, including this one. Read it before wiring anything real in.
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from datetime import UTC, datetime, timedelta

from agents.core.ports import CsiFrame, Resident

#: Frames per second the synthetic feed produces. Chosen to be *above* the
#: beacon-only rate of roughly 10 Hz, because the interesting failure is what
#: happens at 10 Hz and a fixture pinned there would hide every other bug behind
#: the one we already know about. Pass `rate_hz=10.0` to reproduce it on purpose.
DEFAULT_RATE_HZ = 50.0

#: Broadband amplitude sigma for a body that is moving around. Comfortably above
#: `MOVING_RMS` in `agents.people.respiration`, so "moving" in the fixture and
#: in the agent mean the same thing.
MOVING_SIGMA = 0.25


class SyntheticCsiFeed:
    """Generates plausible per-zone channel amplitude. Implements `CsiFeed`.

    Each zone has a state: empty, occupied and breathing, or occupied and
    moving. Breathing is a sinusoid at the zone's respiration rate; movement is
    broadband noise on top of it. That is the same split the sensing agents
    measure with - narrowband for breathing, RMS for motion - so this fixture
    tests whether they can separate the two rather than handing them an answer.
    """

    def __init__(
        self,
        zones: tuple[str, ...],
        *,
        rate_hz: float = DEFAULT_RATE_HZ,
        seed: int = 7,
        history_s: float = 120.0,
        realtime: bool = False,
    ) -> None:
        self.rate_hz = rate_hz
        # In a test, frames appear only when `advance()` is called, which is
        # what makes 130 simulated seconds cost milliseconds and keeps every
        # result deterministic.
        #
        # In a running process nobody calls `advance()`, so without this the
        # feed produces no frames at all and every agent above it correctly
        # reports that it has nothing to say - forever. That failure is honest
        # but useless, so a live feed catches up to the wall clock on read.
        self._realtime = realtime
        self._wall_origin: float | None = None
        self._zones = zones
        self._random = random.Random(seed)
        self._frames: deque[CsiFrame] = deque(maxlen=int(rate_hz * history_s))
        self._t = 0.0
        self._start = datetime.now(UTC)
        self._sequence = 0
        # zone -> (breathing_bpm | None, motion_sigma, transient_offset)
        #
        # `motion_sigma` is broadband; `bpm` is narrowband. Keeping them as
        # separate knobs is what lets a test ask whether an agent can tell them
        # apart, which is the only question worth asking of this fixture.
        self._state: dict[str, tuple[float | None, float, float]] = {
            zone: (None, 0.0, 0.0) for zone in zones
        }

    # ------------------------------------------------------------------ control

    def occupy(self, zone: str, *, bpm: float = 15.0, moving: bool = False) -> None:
        """Put a breathing body in a zone.

        **A moving body's respiration is not recoverable here, and that is
        correct.** Movement is broadband energy sitting on top of the 0.1-0.5 Hz
        band, and on a 1x1 link it swamps a 5-12mm chest displacement. It is
        also why the respiration reader rather than motion is what finds the person on the
        floor: the case it is good at is exactly the case that matters.
        """
        self._state[zone] = (bpm, MOVING_SIGMA if moving else 0.0, 0.0)

    def vacate(self, zone: str) -> None:
        self._state[zone] = (None, 0.0, 0.0)

    def perturb(self, zone: str, magnitude: float = 0.4) -> None:
        """A curtain. Moves the channel, breathes at nothing.

        The single most useful fixture in this file: it is what a naive
        implementation calls a person, and it is what the respiration reader exists to
        refuse.
        """
        self._state[zone] = (None, magnitude, 0.0)

    # --------------------------------------------------------------- the feed

    def advance(self, seconds: float) -> None:
        """Generate `seconds` of frames. Tests drive this instead of sleeping."""
        for _ in range(int(seconds * self.rate_hz)):
            self._step()

    def _step(self) -> None:
        self._t += 1.0 / self.rate_hz
        amplitude: dict[str, float] = {}
        for zone in self._zones:
            bpm, sigma, offset = self._state[zone]
            # Baseline: the static multipath structure, plus thermal noise.
            value = 1.0 + self._random.gauss(0.0, 0.004)
            if bpm is not None:
                # Chest wall displacement. The one thing in the band of interest.
                value += 0.05 * math.sin(2.0 * math.pi * (bpm / 60.0) * self._t)
            if sigma:
                value += self._random.gauss(0.0, sigma)
            if offset:
                value += offset * self._random.random()
                # A transient decays. Left to persist it would read as a
                # permanent change in the room rather than as an event.
                self._state[zone] = (bpm, sigma, max(0.0, offset - 8.0 / self.rate_hz))
            amplitude[zone] = value

        self._sequence += 1
        self._frames.append(
            CsiFrame(
                captured_at=self._start + timedelta(seconds=self._t),
                sequence=self._sequence,
                amplitude=amplitude,
                rate_hz=self.rate_hz,
                source="ruview-sim",
                baseline_age_s=self._t,
            )
        )

    def _catch_up(self) -> None:
        """Generate whatever the wall clock says should have arrived by now.

        Capped at the history window: a process that was paused for an hour
        should not then synthesize an hour of CSI, it should behave like a
        capture that has just started.
        """
        if not self._realtime:
            return
        now = time.monotonic()
        if self._wall_origin is None:
            self._wall_origin = now
            # Prime enough history that the rolling baseline can form rather
            # than making every agent wait two minutes from a cold start.
            self.advance(min(self._t + 150.0, 150.0))
            return
        due = (now - self._wall_origin) - self._t
        if due > 0:
            self.advance(min(due, 5.0))

    def latest(self) -> CsiFrame | None:
        self._catch_up()
        return self._frames[-1] if self._frames else None

    def window(self, seconds: float) -> list[CsiFrame]:
        self._catch_up()
        if not self._frames:
            return []
        cutoff = self._frames[-1].captured_at - timedelta(seconds=seconds)
        return [f for f in self._frames if f.captured_at >= cutoff]


class StaticRoster:
    """The household, as configuration. Implements `RosterSource`.

    Two residents, matching the demo house. Labels are opaque: the card, the
    sealed record and the transparency log are all world-readable, and
    `resident_1` is not a privacy leak where a real name would be.
    """

    def __init__(self) -> None:
        self._residents = (
            Resident(resident_id="r1", label="resident_1", device_ids=("dev-a",)),
            Resident(resident_id="r2", label="resident_2", device_ids=("dev-b",)),
        )
        self._associated: set[str] = {"dev-a", "dev-b"}

    def residents(self) -> tuple[Resident, ...]:
        return self._residents

    def associated_devices(self) -> frozenset[str]:
        return frozenset(self._associated)

    def leave(self, device_id: str) -> None:
        """A phone drops off the network. The house empties, as far as we know."""
        self._associated.discard(device_id)

    def arrive(self, device_id: str) -> None:
        self._associated.add(device_id)


class SyntheticOccupancy:
    """A camera that sees somebody every so often. Implements `OccupancySource`.

    The deployed agents run with no Pi and no Logitech attached, and `vision`
    still has to say something true on every tick. This says "person present"
    for `present_s` out of every `period_s`, and "nobody" the rest of the time,
    off the wall clock so a running agent produces a verdict that changes while
    somebody is watching it.

    It is constructed only where `Source.CAMERA_SIM` is passed alongside it, and
    that pairing is the point: `VisionAgent` refuses any source label that is not
    a camera, and `CAMERA_SIM` is what the app renders a simulated badge from. A
    fixture that could present as `CAMERA_UVC` would be a lie about which sensor
    produced the claim.
    """

    def __init__(self, *, period_s: float = 40.0, present_s: float = 15.0) -> None:
        self.period_s = period_s
        self.present_s = present_s

    def occupancy(self) -> "Occupancy":
        from hawkeye_vision.occupancy import Occupancy

        if time.time() % self.period_s < self.present_s:
            return Occupancy.PERSON_PRESENT
        return Occupancy.NO_PERSON


class DevOpenAttestations:
    """A shutter that always reports the shield clear. Implements `AttestationSource`.

    In the real mesh `vision` gets this attestation from `shutter` over ANS,
    signed and bound to a nonce, and refuses to claim anything without it. The
    deployed dev process runs each agent alone, with no `shutter` on the other
    end of a socket to attest anything, so this stands in - and it returns a
    *fresh* attestation on every read rather than a cached one, because the gate
    checks `att.at` against `ATTESTATION_TTL_S` and a static timestamp would go
    stale seconds into a running process and wedge `vision` at `shield_closed`.

    **This is not the demo.** Like `LocalMesh`, it verifies nothing: a real
    attestation is a signed grant from a separately registered agent, and the
    refusal path that is the whole submission runs through `shutter`, not here.
    It exists so the single-process `vision` runner has something true to say.
    """

    def current(self) -> "Attestation":
        from datetime import UTC, datetime

        from agents.shutter.backend import OPEN_ANGLE
        from agents.shutter.shutter import Attestation

        return Attestation(
            position="open",
            commanded_angle=OPEN_ANGLE,
            nonce="dev-open",
            at=datetime.now(UTC),
        )


class DevNarrations:
    """A canned running description. Implements `NarrationSource`.

    The real narration is a Gemini Live sentence off the camera's current frame;
    this rotates a short scripted line off the wall clock so the single-process
    `vision` runner emits a `vision.description` that changes while somebody is
    watching it. Every line is generic and scene-neutral on purpose - a dev
    fixture must never author specifics a real camera would have to see.
    """

    _LINES: tuple[str, ...] = (
        "A person is standing near the doorway.",
        "The person has moved further into the room.",
        "The person appears to be looking around the room.",
    )

    def latest(self) -> "Narration":
        from datetime import UTC, datetime

        from hawkeye_vision.narrate import Narration

        index = int(time.time() / 6.0) % len(self._LINES)
        return Narration(
            text=self._LINES[index],
            at=datetime.now(UTC),
            frame_index=index,
            model="dev-stub",
            latency_s=0.0,
        )
