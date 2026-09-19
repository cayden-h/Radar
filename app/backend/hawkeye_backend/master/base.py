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
        """Which of the nine agents the hub can currently reach."""
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
