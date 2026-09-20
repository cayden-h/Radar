"""Interior state: who is in the building, where, and whether they are breathing.

This is what the app's 3D view renders. The three states app/CLAUDE.md requires
are carried explicitly by `PresenceState` rather than being left for the client
to infer from a pile of booleans, because the difference between them is the
difference between dispatching an ambulance and reporting a curtain.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from hawkeye_backend.models.common import Provenance, utc_now
from hawkeye_backend.models.household import ObservedDevice


class PresenceState(StrEnum):
    """The three states app/CLAUDE.md requires the 3D view to distinguish.

    CONFIRMED_MOVING: moving and breathing. A person, confirmed.
    CONFIRMED_STILL:  a person who is not moving. Either still breathing, or
                      carrying a breathing signature that was resolvable and is
                      not now - see Presence.respiration_lost_s, which is what
                      separates those two. A lost signature is never a finding
                      that breathing stopped.
                      The loudest thing on screen. This is what the system exists for.
    UNCONFIRMED:      a perturbation with no respiration signature. Render it as
                      such, not as a person. A curtain is not an intruder.
    UNKNOWN:          not enough data yet. Absence of respiration is NOT proof of
                      absence of a person, so a presence that has not been
                      resolved sits here rather than being called UNCONFIRMED.
    """

    CONFIRMED_MOVING = "confirmed_moving"
    CONFIRMED_STILL = "confirmed_still"
    UNCONFIRMED = "unconfirmed"
    UNKNOWN = "unknown"


class RespirationStatus(StrEnum):
    """Respiration is the personhood test. Never heart rate."""

    BREATHING = "breathing"
    # No periodicity found in the 0.1-0.5 Hz band. NOT the same as "no person":
    # shallow breathing, breath-holding, and range limits all degrade to this.
    NO_SIGNATURE = "no_signature"
    UNKNOWN = "unknown"


class PresenceClass(StrEnum):
    """Coarse class, decided from respiration rate, not signal amplitude.

    Adult 12-20 BPM, child 20-30, infant 30-60, dog/cat 15-30+. The overlap
    between child and pet is real and is stated rather than hidden; the honest
    resolution is "adult versus small and fast-breathing".
    """

    ADULT = "adult"
    CHILD = "child"
    PET = "pet"
    UNKNOWN = "unknown"


class Position(BaseModel):
    """Coarse position inside the floorplan.

    `zone` is the honest answer and is what the agents reason over. `x`/`y` exist
    only so the 3D view has somewhere to draw; they are a zone centroid with
    jitter, not a localization claim. Do not promise coordinates.
    """

    zone: str = Field(description="Room-level zone id, e.g. 'main_bedroom'. Coarse by design.")
    x: float = Field(description="Metres from floorplan origin. Zone centroid, not a fix.")
    y: float = Field(description="Metres from floorplan origin. Zone centroid, not a fix.")
    zone_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the zone, 0-1.")


class Vitals(BaseModel):
    """Respiration and heart rate. Respiration carries the personhood verdict."""

    respiration: RespirationStatus
    breathing_bpm: float | None = Field(
        default=None,
        ge=6.0,
        le=30.0,
        description="RuView's stated range. Outside 6-30, report null rather than a number.",
    )
    heart_bpm: float | None = Field(
        default=None,
        ge=40.0,
        le=120.0,
        description="Stretch goal, and a good number to say on the call. Never the personhood test.",
    )
    person_confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence that this perturbation is a living body."
    )


class Presence(BaseModel):
    """One tracked presence.

    `presence_id` is stable within a session only. We do not do person
    re-identification and must not claim to.
    """

    presence_id: str
    state: PresenceState
    position: Position
    moving: bool
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence the presence exists at all.")
    vitals: Vitals
    presence_class: PresenceClass = PresenceClass.UNKNOWN
    class_basis: str | None = Field(
        default=None,
        description="What the class decision was made from. 'respiration_rate' is the defensible one.",
    )
    expected: bool | None = Field(
        default=None,
        description=(
            "agents/intruder's inference from context (entry point, time of day, count vs "
            "reported residents). Never a recognition result. null when not yet decided."
        ),
    )
    respiration_lost_s: float | None = Field(
        default=None,
        description=(
            "Seconds since a breathing signature was last resolvable on this presence, from "
            "agents/people. Only ever set on a presence that HAD a signature: the transition "
            "is the signal, and a presence that never resolved one carries no information. "
            "Never a finding that breathing has stopped."
        ),
    )
    provenance: Provenance = Field(description="Required. See the honesty rule.")


class Room(BaseModel):
    """One room in the floorplan. Polygon in metres, floorplan origin at (0,0)."""

    zone: str
    name: str
    polygon: list[tuple[float, float]] = Field(min_length=3)


class Floorplan(BaseModel):
    """Static building geometry the 3D view draws. One resident, hardcoded."""

    site_id: str
    name: str
    units: str = "m"
    width_m: float
    depth_m: float
    wall_height_m: float = 2.5
    rooms: list[Room]


class Calibration(BaseModel):
    """Rolling-baseline health.

    `healthy` going false must propagate and must suppress escalation. A stale
    baseline produces confident nonsense.
    """

    baseline_age_s: float
    healthy: bool
    note: str | None = None


class EnvironmentReading(BaseModel):
    """Air quality. Carbon monoxide, and not from CSI.

    CSI cannot sense gas composition at 2.4/5 GHz. This reading comes from a
    separate modality, which is what makes it real corroboration rather than two
    views of one stream. No gas sensor was purchased, so in practice
    `provenance.source` is `demo-trigger` and `provenance.simulated` is true.
    """

    co_ppm: float = Field(ge=0.0)
    smoke_detected: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance = Field(description="Required. Carries demo-trigger when simulated.")


class InteriorState(BaseModel):
    """Everything the app needs to draw the house right now."""

    site_id: str
    captured_at: datetime = Field(default_factory=utc_now)
    sensor_identity: str = Field(description="ANSName of the sensing device.")
    calibration: Calibration
    presences: list[Presence]
    associated_devices: list[ObservedDevice] = Field(
        default_factory=list,
        description=(
            "Devices the router reports associated, hashed by the producer. An "
            "absent field means not reported, never that nobody is here."
        ),
    )
    environment: EnvironmentReading | None = Field(
        default=None, description="Null when agents/master has not reported."
    )
    floorplan: Floorplan
    active_incident_id: str | None = None
