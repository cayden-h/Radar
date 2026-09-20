"""Every tuneable number in the camera path, in one place.

These are configuration rather than constants because they must be calibrated
at the location the demo runs in, and the value that works in one room is wrong
in another. A threshold hard-coded in a module is a threshold nobody can fix at
the venue at 2am.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionConfig(BaseModel):
    """Thresholds and rates for capture, lighting and tracking."""

    model_config = {"frozen": True}

    # --- lighting ---------------------------------------------------------
    day_threshold: float = Field(
        default=90.0,
        description="Mean luminance at or above this is DAY. Calibrate at the venue.",
    )
    dark_threshold: float = Field(
        default=25.0,
        description="Mean luminance below this is TOO_DARK: no detection, no narration.",
    )
    hysteresis: float = Field(
        default=8.0,
        description=(
            "Luminance a reading must move past a threshold by before the state is "
            "allowed to change back. Stops a value sitting on the boundary flapping."
        ),
    )
    dwell_frames: int = Field(
        default=45,
        description=(
            "Consecutive frames a candidate state must hold before it takes effect. "
            "At 15fps this is roughly three seconds, which is long enough that a "
            "passing shadow or a car headlight does not switch the pipeline."
        ),
    )

    # --- capture ----------------------------------------------------------
    day_fps: int = Field(default=15, description="Capture rate in good light.")
    low_fps: int = Field(default=8, description="Capture rate in low light, longer exposures.")
    detect_width: int = Field(default=640, description="Long edge fed to the detector.")

    # --- tracking ---------------------------------------------------------
    day_confidence: float = Field(default=0.35, description="Detection confidence floor in DAY.")
    low_confidence: float = Field(
        default=0.50,
        description=(
            "Higher floor in LOW. A noisy, gain-boosted frame produces confident "
            "nonsense, and a false person on a 911 call is worse than a missed one."
        ),
    )
    track_expiry_frames: int = Field(
        default=30,
        description="Frames a track survives unseen before it stops counting as present.",
    )
