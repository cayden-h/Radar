"""The MasterClient protocol and the sink it publishes through."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hawkeye_backend.models.events import EventPayload
from hawkeye_backend.models.hub import AgentReachability, SensorLiveness
from hawkeye_backend.models.incident import (
    ContextNote,
    Incident,
    IncidentType,
    RaisedBy,
    ReplayRecord,
)
from hawkeye_backend.models.state import InteriorState


class MasterUnavailable(RuntimeError):
    """agents/master could not be reached or answered badly.

    Raised rather than papered over. A hub that quietly invents interior state
    when the mesh is down is the failure this project is built against.
    """


class AutonomousDialRefused(RuntimeError):
    """Something tried to put a SYSTEM-raised incident on the dialing path.

    Hawk Eye never calls 911 on its own; settled 2026-09-19. Detections from
    `agents/people` and `agents/master` surface as interior state a
    person acts on, and a human tap is what releases `agents/caller` to dial.

    This is raised rather than logged because the failure it guards against is
    the whole project in reverse: a house that dials emergency services with
    nobody having asked it to.
    """


class ParticipationModeRefused(RuntimeError):
    """master declined a participation-mode change for an incident's call.

    `app/backend` does not import `agents/`, so this is a local type rather
    than a shared exception class: the two are separately deployable
    processes that only ever talk over HTTP/A2A. `LiveMasterClient` raises
    this when master's A2A endpoint reports the mode change as refused
    (e.g. the incident has no active call, or the requested mode is not one
    master will honour for this call state).
    """


def assert_human_released(incident: Incident) -> None:
    """Gate on the dialing path. Only a human tap releases `agents/caller`.

    Structural, not conventional, in the same way `Provenance.source_class` is
    computed rather than trusted. Every path that can end in a phone call calls
    this first, so a future change that reintroduces an autonomous raise fails
    loudly at the point it would have dialed.
    """
    if incident.raised_by is not RaisedBy.USER:
        raise AutonomousDialRefused(
            f"incident {incident.incident_id} was raised by "
            f"{incident.raised_by.value!r} and must not reach the dialing path. "
            "Hawk Eye never calls 911 on its own (settled 2026-09-19); a detection "
            "surfaces as interior state and a human tap releases the call."
        )


@runtime_checkable
class EventSink(Protocol):
    """Where a MasterClient publishes. Implemented by HubRuntime."""

    async def emit(self, payload: EventPayload, incident_id: str | None = None) -> None: ...


@runtime_checkable
class MasterClient(Protocol):
    """Everything the API layer asks of the agent mesh."""

    async def start(self, sink: EventSink) -> None:
        """Begin producing events into `sink`. Called once on app startup."""
        ...

    async def stop(self) -> None:
        """Shut down cleanly. Called on app shutdown."""
        ...

    async def sensor_liveness(self) -> SensorLiveness:
        """Is CSI actually flowing, and from what source."""
        ...

    async def agent_reachability(self) -> list[AgentReachability]:
        """Which of the five agents the hub can currently reach."""
        ...

    async def current_state(self) -> InteriorState:
        """Interior state right now."""
        ...

    async def raise_incident(
        self, incident_type: IncidentType, raised_by: RaisedBy, note: str | None
    ) -> Incident:
        """Raise an incident to master. Returns the incident as master accepted it."""
        ...

    async def submit_context(self, incident_id: str, text: str) -> ContextNote:
        """Forward the resident's free text to master, for caller to use."""
        ...

    async def fetch_replay(self, incident_id: str) -> ReplayRecord | None:
        """The sealed post-incident record from agents/replay."""
        ...

    async def start_call(self, incident: Incident) -> None:
        """Release agents/caller to dial, for an already human-raised incident.

        Raises `AutonomousDialRefused` (via `assert_human_released`) if
        `incident.raised_by` is not `RaisedBy.USER`. This is a second,
        independent copy of the guard `agents/master.release_for_call` holds
        on the agents side: `app/backend` is a separate deployable process
        that talks to master only over HTTP/A2A, so it cannot rely on that
        in-process check reaching across the network boundary. Hawk Eye
        never calls 911 on its own; settled 2026-09-19.
        """
        ...

    async def set_participation_mode(
        self, incident_id: str, mode: str, *, by_human: bool
    ) -> str:
        """Switch the resident's leg of an in-progress call.

        `mode` is one of "watching", "whisper", "full_voice" (see
        `app/CLAUDE.md`'s mode table). Returns the announcement text spoken
        on the call/shown in-app for the switch. Raises
        `ParticipationModeRefused` if master declines the change (e.g. no
        active call for this incident, or automation tried to move the mode
        louder without `by_human=True` — automation may only ever move
        toward quieter).
        """
        ...

    async def inject_context(self, incident_id: str, text: str) -> None:
        """Route a resident's note straight to agents/caller to be spoken.

        Best-effort. Unlike `submit_context`, which stores the note into the
        incident record, this is the side channel that lets an already-running
        call speak it aloud, attributed to the resident. It is context, never
        instruction: it must never be treated as authorization and must never
        change what the call trusts or where it is directed. Callers of this
        method (see `api.post_context`) are expected to fail soft - a failed
        speak must not fail the note store.
        """
        ...

    async def issue_shutter_grant(
        self, *, action: str, reason: str, nonce: str, incident_id: str | None = None
    ) -> str:
        """Return a signed grant as the opaque JSON string it crosses the wire as.

        A string, never an object. The bytes that were signed must be the bytes
        that are verified, and any layer that parses and re-serializes breaks
        every signature in a way indistinguishable from tampering. See
        `agents/shutter/grant.py`, which states the same rule from the other end.

        `nonce` comes from the shutter itself, via `shutter.challenge`, and is
        never generated here. Binding a grant to a nonce the verifier issued is
        what makes a replayed grant detectable.
        """
        ...
