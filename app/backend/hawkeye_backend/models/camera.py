"""What the detector measured, in a shape the relay can draw.

Separate from `OccupancyEvent` on purpose. Occupancy is a *claim* - personhood,
scoped to a room, carrying provenance, and belonging on the event stream where
every surface and the sealed record can see it. Boxes are not a claim. They are
a rendering detail that arrives at camera frame rate, and putting them on the
event stream would bury the incident in geometry.

So they travel on their own endpoint, update nothing but the relay's overlay
state, and are never sealed into a record.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from hawkeye_backend.models.common import utc_now


class TrackBox(BaseModel):
    """One person the tracker is holding, normalised to 0..1 of the frame.

    Normalised rather than in pixels because the consumers draw at whatever size
    their view happens to be - a watch thumbnail, a phone, a browser - and
    because these numbers must not carry this particular camera's resolution as
    a hidden assumption. The Pi can be swapped for one with a different sensor
    without anything downstream changing.
    """

    track_id: int = Field(ge=0, description="BoT-SORT's identity for this person.")
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "TrackBox":
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError(
                "TrackBox corners must be ordered top-left to bottom-right; "
                f"got ({self.x1}, {self.y1}) to ({self.x2}, {self.y2})"
            )
        return self


class TracksRequest(BaseModel):
    """What `agents/vision` publishes after each pass of the detector."""

    tracks: list[TrackBox] = Field(
        default_factory=list,
        description=(
            "Every person currently held by the tracker. An empty list is "
            "meaningful: it says the detector looked and found nobody, which is "
            "what clears the boxes off the feed."
        ),
    )
    at: datetime = Field(
        default_factory=utc_now,
        description="When the frame these were measured on was captured.",
    )


class PersonVouch(BaseModel):
    """A resident vouching for the person inside one box.

    **Not an identity claim, and the field names keep it that way.** `name` is
    what a human typed, not what anything recognised, and `track_id` is the
    tracker's id for a box rather than a handle on a person. Nothing downstream
    may present this as recognition: see `edge/vouch.py` for the hole this
    leaves open and why it is left open rather than papered over.
    """

    track_id: int = Field(ge=0, description="The box the resident pointed at.")
    name: str = Field(
        min_length=1,
        max_length=40,
        description="What the resident called them. Free text; never matched against anything.",
    )
    vouched_at: datetime = Field(description="When the resident tapped.")
    last_seen_at: datetime = Field(
        description="When the tracker last held this id. What the grace window is measured from."
    )
    held: bool = Field(
        description=(
            "True while the tracker still has this id. False means the person is "
            "out of frame and the vouch is inside its grace window - which every "
            "surface draws differently, because a held vouch and a lapsing one "
            "are different statements about the room."
        )
    )


class VouchRequest(BaseModel):
    """What a surface posts when somebody taps a box and names them."""

    track_id: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        """Strip here, so a name that is only whitespace is a 422 and not a 500.

        It has to happen at the boundary rather than in the ledger: `"  "`
        satisfies `min_length=1` on the way in and is empty by the time anything
        stores it, and a blank vouch would put an *unlabelled green box* on the
        feed - which reads as "the system recognised somebody" to anyone
        glancing at it. That is the one thing this feature must never imply.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("a vouch needs a name; whitespace is not one")
        return stripped


class TracksSnapshot(BaseModel):
    """The boxes and their vouch state, for a surface that draws its own overlay.

    Served by polling rather than pushed on the event stream, and that is the
    same decision `POST /camera/tracks` documents: geometry arrives at camera
    rate and would bury an incident under several hundred messages a minute.
    A phone that is looking at the camera asks for this; nothing else pays for it.
    """

    tracks: list[TrackBox] = Field(default_factory=list)
    vouches: list[PersonVouch] = Field(default_factory=list)
    at: datetime = Field(default_factory=utc_now)
