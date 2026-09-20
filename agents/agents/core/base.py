"""The base every agent inherits: an always-running loop and a latest answer.

**Every agent runs continuously. Nothing spawns on incident.** That is a
requirement rather than an optimisation, and this class is where it is
structural: an agent has no "handle a request" entry point, only a `tick` that
runs whether or not anyone is asking. It is what allows the system to notice an
unidentified person in the house at 3am, or CO climbing while everyone sleeps.

`tick` is synchronous and pure-ish on purpose. It takes the agent's inputs and
returns an observation, so every agent in this package can be tested by calling
one function with a fixture and asserting on what comes back, with no event
loop, no clock and no transport involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agents.core.identity import AgentIdentity
from agents.core.observations import AgentObservation, Assertion, Unknown

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from agents.core.signing import ClaimSigner

logger = logging.getLogger(__name__)


class Agent(ABC):
    """One of the five.

    Subclasses implement `tick`. Everything else - the loop, the latest
    observation, the health reporting - is here so that five agents behave
    identically in the ways that are not their job.
    """

    #: How often `tick` runs. Sensing agents want a second or less; the
    #: coordination and human-boundary agents are event-shaped and idle most of
    #: the time, so they tick slowly and do their real work when called.
    interval_s: float = 1.0

    def __init__(self, identity: AgentIdentity) -> None:
        self.identity = identity
        self._latest: AgentObservation | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._ticks = 0
        self._errors = 0

    # ------------------------------------------------------------------ the job

    @abstractmethod
    def tick(self) -> AgentObservation:
        """Look at the inputs and say what is true right now.

        Must not raise for ordinary missing data. An agent with no frames yet
        returns an unhealthy observation carrying an `Unknown`, because that is
        a fact a dispatcher would want and an exception is not.
        """

    def a2a_methods(self, signer: "ClaimSigner") -> "dict[str, Callable[[dict], dict]]":
        """Extra JSON-RPC methods this agent answers on `/a2a`.

        Almost always empty, and deliberately so: what differs between agents is
        `tick`, and an agent that grew its own protocol would be a service with
        an agent inside it. `shutter` is the exception the hook exists for,
        because it is the one agent that takes an order rather than answering a
        question, and `shutter.open` has no shape in the observe protocol.

        They are extra **methods**, not an extra route. There is one `/a2a` per
        agent because that is the endpoint our card publishes and the one the
        judge's verifier sends its live message to. A second router claiming the
        same path would resolve to whichever registered first, and the loser's
        methods would come back as `unknown method`.

        The signer is handed in rather than held by the agent, because it
        belongs to the transport: an agent is a `tick` and some state, and one
        that owned a private key would be a service with an agent inside it.
        `shutter` needs it because **a refusal is an observation and
        observations are signed** - an unsigned "I refused" in a log proves
        nothing to anyone not already trusting us.
        """
        return {}

    # --------------------------------------------------------------- convenience

    def observe(
        self,
        *,
        assertions: tuple[Assertion, ...] = (),
        unknowns: tuple[Unknown, ...] = (),
        healthy: bool = True,
        note: str | None = None,
    ) -> AgentObservation:
        """Build an observation stamped with this agent's identity."""
        return AgentObservation(
            agent=self.identity.name,
            ansname=self.identity.ansname,
            assertions=assertions,
            unknowns=unknowns,
            healthy=healthy,
            note=note,
        )

    def blind(self, field: str, reason: str, *, zone: str = "site") -> AgentObservation:
        """The "I cannot tell you that" observation. Used, not avoided."""
        return self.observe(
            unknowns=(Unknown(field=field, zone_scope=zone, reason=reason),),
            healthy=False,
            note=reason,
        )

    # ---------------------------------------------------------------- the loop

    @property
    def latest(self) -> AgentObservation | None:
        """The most recent observation, or None before the first tick."""
        return self._latest

    def run_once(self) -> AgentObservation:
        """One tick, recorded. Separated from the loop so tests can drive it."""
        self._ticks += 1
        try:
            observation = self.tick()
        except Exception:  # noqa: BLE001 - an agent must not die of one bad frame
            self._errors += 1
            # Fail closed and fail quietly: the verifier that throws mid-incident
            # is a worse outcome than the one that refuses a claim. Same rule
            # applies to a sensing agent that hits a bad window.
            logger.exception("%s tick failed; reporting unhealthy", self.identity.name)
            observation = self.observe(
                healthy=False, note="tick raised; see logs. Reporting nothing rather than guessing."
            )
        self._latest = observation
        return observation

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name=f"{self.identity.slug}-loop")
        logger.info("%s running at %.2fs intervals", self.identity.name, self.interval_s)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            # `tick` is synchronous by design - it takes inputs and returns an
            # observation, so every agent is testable by calling one function
            # with a fixture, with no event loop involved.
            #
            # But master's tick makes blocking HTTP calls to its peers, and
            # running that on the event loop would stall this agent's own
            # server for the duration: two peers at a three second timeout is
            # six seconds during which the agent answers nothing, including the
            # fan-out it is itself being asked for. So the tick runs in a
            # thread and the loop stays free.
            await asyncio.to_thread(self.run_once)
            await asyncio.sleep(self.interval_s)

    # --------------------------------------------------------------- reporting

    def health(self) -> dict[str, object]:
        """What `/healthz` serves. Never goes in the card: it is not byte-stable."""
        latest = self._latest
        return {
            "agent": self.identity.name,
            "ansname": self.identity.ansname,
            "running": self._task is not None and not self._task.done(),
            "ticks": self._ticks,
            "tick_errors": self._errors,
            "healthy": bool(latest and latest.healthy),
            "observed_at": latest.observed_at.isoformat() if latest else None,
        }
