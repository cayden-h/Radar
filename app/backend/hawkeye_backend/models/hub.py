"""Hub identity and health. What the iOS Connect screen hits after Bonjour discovery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import Source, utc_now


class Reachability(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    DEGRADED = "degraded"
    SIMULATED = "simulated"


class AgentReachability(BaseModel):
    """One agent in the mesh, as seen from the hub.

    The hub reports what it can reach. It does not report ANS verification
    results here: verification is per-claim and lives on the verification stream,
    because an agent that was trusted ninety seconds ago may not be trusted now.
    """

    name: str = Field(description="Agent directory name, e.g. 'agents/people'.")
    ansname: str
    tier: int = Field(ge=1, le=3, description="Build priority tier from agents/CLAUDE.md.")
    reachability: Reachability
    last_seen_at: datetime | None = None
    latency_ms: float | None = None
    detail: str | None = None


class SensorLiveness(BaseModel):
    """Whether CSI is actually flowing.

    `frame_rate_hz` is the field that catches the quiet failure: without a
    traffic generator you get beacons at roughly 10 Hz, which barely resolves
    breathing and never resolves a short motion transient, with every component
    reporting healthy. Below `min_useful_frame_rate_hz` the hub reports degraded.
    """

    source: Source = Field(description="Required. What is behind the sensor interface right now.")
    simulated: bool = Field(description="Derived from source by the hub. Mirrors Provenance.simulated.")
    live: bool = Field(description="Is the sensing pipeline producing frames at all.")
    frame_rate_hz: float | None = None
    min_useful_frame_rate_hz: float = 100.0
    last_frame_at: datetime | None = None
    baseline_healthy: bool
    baseline_age_s: float | None = None
    detail: str | None = None


class HubStatus(BaseModel):
    """GET /v1/hub response.

    The Connect screen verifies the hub with this before entering the main app.
    """

    hub_name: str
    hub_ansname: str = Field(description="The ANSName this hub is anchored to.")
    master_ansname: str
    site_id: str
    site_address: str
    mode: str = Field(description="'simulated' or 'live'. Printed in the app, not hidden.")
    version: str
    healthy: bool = Field(description="True when the app may proceed past the Connect screen.")
    server_time: datetime = Field(default_factory=utc_now)
    uptime_s: float
    sensor: SensorLiveness
    agents: list[AgentReachability]
    active_incident_id: str | None = None
    stream_path: str = "/v1/stream"
