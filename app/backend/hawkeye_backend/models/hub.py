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


class CameraStatus(BaseModel):
    """Whether there is a camera, and whether what it last sent is current.

    `linked` and `live` are deliberately two fields rather than one. A link that
    is up while frames have stopped arriving is a real and distinct failure, and
    collapsing it into one boolean would let a stalled camera read as a
    disconnected one, which is a different repair.

    `live` false means the app must not present the last frame as current. That
    is the whole reason this model exists: a frozen picture of an empty room is
    the most dangerous thing this system can put on a screen.
    """

    linked: bool = Field(default=False, description="Is an edge box connected right now.")
    live: bool = Field(
        default=False,
        description="Is the newest frame recent enough to present as current.",
    )
    edge_id: str | None = None
    source: Source | None = Field(
        default=None,
        description=(
            "What the edge claims is producing frames. A video file must not read "
            "as a camera, which is why this is carried rather than assumed."
        ),
    )
    last_frame_age_s: float | None = Field(
        default=None,
        description="Seconds since the newest frame was captured. None if none ever has been.",
    )
    fps: float = Field(default=0.0, description="Frames per second over the last ten seconds.")
    frames_received: int = 0
    frames_dropped: int = Field(
        default=0, description="Inferred from gaps in the edge's frame index."
    )
    detail: str = Field(
        default="No edge camera has connected yet.",
        description="One sentence, written to be printed on a console.",
    )


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
    camera: CameraStatus = Field(
        default_factory=CameraStatus,
        description=(
            "The camera's own health, separate from the radio's. The Connect screen "
            "and the live view both read it, and an unreachable camera must render "
            "as unreachable rather than as a still room. Defaulted to the unlinked "
            "state rather than required, because the honest answer before anything "
            "connects is that there is no camera."
        ),
    )
