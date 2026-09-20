"""The two seams `vision` reads that it does not compute itself.

`vision` answers one question - is there a person, and what are they doing - but
it is forbidden from answering it until two other things are true, and neither of
them is something this agent produces:

- **The shield is clear.** A signed `Attestation` from `shutter`, saying the
  servo has moved the opaque plastic off the lens. Root and `vision/CLAUDE.md` are
  explicit that this is not a flag `vision` sets for itself: "vision produces no
  claim unless it holds a current, verified attestation from shutter saying the
  shield is clear." Without one, every claim collapses to
  `Unknown(reason="shield_closed")`.
- **The narrator has a sentence.** The running description comes from the Gemini
  Live session in `hawkeye_vision.narrate`, which owns the network and the model.
  `vision` reads the latest sentence off it and never generates one itself.

These are `Protocol`s for the same reason the ports in `agents/core/ports.py`
are: a real attestation arriving over ANS and a test pushing one in from memory
must be swappable without anything in `agent.py` changing, and it must be visible
which one is in use. The honest in-process implementations below are the memory
half of that - the mesh (or a test) sets the current attestation and the latest
narration, and the agent reads them - and they are named so nobody mistakes them
for the verified transport.

**The in-process implementations verify nothing.** An `Attestation` set here is
trusted because a test or the local mesh put it here, exactly as `LocalMesh` in
`agents/core/ports.py` trusts what it is handed. The verified path wraps a real
`shutter` attestation that arrived signed; that lives with the transport, not
here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from agents.shutter.shutter import Attestation
from hawkeye_vision.narrate import Narration

#: How fresh a shutter attestation has to be before `vision` will stand on it.
#:
#: A window rather than a point because the attestation is `commanded`, not
#: measured (see `Attestation`): the SG92R is open-loop and a shield can jam
#: after the servo reports open, so an attestation is only ever evidence that the
#: lens was uncovered *recently*. Too long a window lets a stale "open" keep the
#: camera claiming into a room whose shield has since closed; too short a one
#: makes every claim depend on a fresh attestation landing on the same tick. Five
#: seconds covers several vision ticks (`interval_s = 1.0`) while still going
#: dark within a handful of frames of the attestation ceasing to arrive.
ATTESTATION_TTL_S: float = 5.0

#: The one position string that means the lens can see. Mirrors the literal
#: `shutter` writes into `Attestation.position` ("open" or "closed"); named here
#: so a consumer cannot fat-finger the comparison and treat "closed" as clear.
OPEN_POSITION = "open"


@runtime_checkable
class AttestationSource(Protocol):
    """The latest shutter attestation this vision agent is holding.

    A real implementation returns the attestation that arrived signed from
    `shutter` over the transport, or `None` when none has. `None` is a real
    answer and must stay distinguishable from a stale one: no attestation and an
    old attestation are both `shield_closed` to `vision`, but they are different
    facts and `attestation_is_open` decides the second from the timestamp.
    """

    def current(self) -> Attestation | None:
        """The most recent attestation held, or `None` if there is none yet."""
        ...


@runtime_checkable
class NarrationSource(Protocol):
    """The latest sentence the narrator produced, or `None`.

    A real implementation drains the Gemini Live narrator in
    `hawkeye_vision.narrate` and hands back the most recent `Narration`. `None`
    means the narrator has produced nothing to describe yet, which `vision`
    reports as `Unknown(reason="narrator_unreachable")` rather than as a
    fabricated line - a room the model has not described is not a room with
    nothing in it.
    """

    def latest(self) -> Narration | None:
        """The most recent narration line, or `None` if there is none yet."""
        ...


def attestation_is_open(att: Attestation | None, *, now: datetime) -> bool:
    """Whether `vision` may act on `att` at `now`.

    True only when all three hold:

    1. There is an attestation at all.
    2. Its position is the open/clear position, not "closed".
    3. It was attested within `ATTESTATION_TTL_S` of `now`.

    A missing attestation, a "closed" one, and a stale one are all `False`, and
    all three become `Unknown(reason="shield_closed")` upstream. A timestamp
    slightly ahead of `now` (clock skew between the two agents) is treated as
    fresh rather than rejected, because the failure to guard against is a stale
    attestation keeping the camera claiming, not a marginally fast clock.
    """
    if att is None:
        return False
    if att.position != OPEN_POSITION:
        return False
    age_s = (now - att.at).total_seconds()
    return age_s <= ATTESTATION_TTL_S


class InProcessAttestations:
    """Honest in-process `AttestationSource`. Verifies nothing.

    The mesh (or a test) pushes the current shutter attestation in with `set`,
    and `vision` reads it back with `current`. That is the whole object: it holds
    one attestation and hands it over unexamined, exactly as `LocalMesh` hands
    over an observation in `agents/core/ports.py`.

    **It cannot pass as the verified path.** An attestation set here arrived over
    no wire and carries no signature; the real implementation of this port wraps
    an attestation that `shutter` signed and the transport verified. Do not let
    this class survive into the demo any more than `LocalMesh` may.
    """

    def __init__(self, attestation: Attestation | None = None) -> None:
        self._attestation = attestation

    def set(self, attestation: Attestation | None) -> None:
        """Replace the held attestation. `None` clears it back to shield-closed."""
        self._attestation = attestation

    def current(self) -> Attestation | None:
        return self._attestation


class InProcessNarrations:
    """Honest in-process `NarrationSource`. Holds the latest line, nothing more.

    The sampler that drains the Gemini Live narrator pushes each finished
    sentence in with `set`, and `vision` reads the most recent one with `latest`.
    Clearing it to `None` is how "the narrator went unreachable" is expressed to
    the agent without this object needing to know why.
    """

    def __init__(self, narration: Narration | None = None) -> None:
        self._narration = narration

    def set(self, narration: Narration | None) -> None:
        """Replace the latest narration. `None` means nothing to describe yet."""
        self._narration = narration

    def latest(self) -> Narration | None:
        return self._narration
