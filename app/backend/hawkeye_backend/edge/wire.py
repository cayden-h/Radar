"""What crosses the edge link, in both directions.

These are the only shapes that reach this process from an untrusted LAN, so
they follow the same rules the claim envelope already lives by:

- **`extra="forbid"`.** A message carrying smuggled members is a parse failure,
  not a field somebody reads later by accident.
- **An unknown `kind` is refused**, never read charitably into the nearest
  matching shape.
- **A signed string crosses opaquely.** `EdgeGrant.grant_json` is a string and
  never a nested object, because any layer that parses and re-serializes it
  breaks the signature, and that failure is indistinguishable from tampering.

A frame does not travel in any of these. A frame is an `EdgeFrameHeader` text
message immediately followed by a binary websocket message carrying the raw
JPEG bytes. Websockets preserve ordering, so the pairing holds, and the frame
never pays base64's 33% overhead on the one path that has to stay smooth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from hawkeye_backend.models.common import Source, utc_now


class _Strict(BaseModel):
    """Every wire type forbids extras. Stated once."""

    model_config = ConfigDict(extra="forbid")


class EdgeHello(_Strict):
    """First message on every link. Says which Pi, and what it is looking through."""

    kind: Literal["hello"] = "hello"
    edge_id: str = Field(min_length=1, description="Which physical edge box this is.")
    source: Source = Field(
        description=(
            "What is actually producing frames. `camera-uvc` is the Brio, "
            "`replay-video` is a file being replayed through the same path. This is "
            "what stops a video file presenting as a camera, and it is carried "
            "rather than assumed for exactly that reason."
        )
    )
    note: str = ""


class EdgeFrameHeader(_Strict):
    """Describes the binary message that follows it. Never carries the frame itself."""

    kind: Literal["frame"] = "frame"
    index: int = Field(ge=0, description="Monotonic per link. A gap means frames were dropped.")
    captured_at: datetime = Field(
        description=(
            "When the camera took it, stamped on the Pi. Not when it arrived here. "
            "The two differ by the link's latency and the difference is the whole "
            "point of reporting frame age honestly."
        )
    )
    bytes: int = Field(gt=0, description="Length of the binary message that follows.")


class EdgeError(_Strict):
    """The Pi reporting that it cannot do its job. Surfaced, never swallowed."""

    kind: Literal["error"] = "error"
    code: str
    message: str
    at: datetime = Field(default_factory=utc_now)


class EdgeChallengeRequest(_Strict):
    """Mac to Pi. Ask the local shutter for a fresh nonce.

    The grant has to be bound to a nonce **the shutter itself issued**, so this
    exchange is two phases and cannot be collapsed into one. Asking for a fresh
    one per grant is what makes a replayed grant detectable; holding one open
    across two grants would give an attacker a window in which a captured grant
    is still live.
    """

    kind: Literal["challenge_request"] = "challenge_request"
    request_id: str = Field(min_length=1)


class EdgeChallenge(_Strict):
    """Pi to Mac. The nonce the shutter just issued, or why it could not."""

    kind: Literal["challenge"] = "challenge"
    request_id: str = Field(min_length=1)
    nonce: str = ""
    failed: bool = False
    detail: str = ""


class EdgeGrant(_Strict):
    """Mac to Pi. A signed shutter grant, to be forwarded to the local shutter agent.

    `grant_json` is opaque here and stays opaque all the way to `shutter`, which
    verifies the signature over exactly these bytes. Nothing on this path may
    parse and re-serialize it.
    """

    kind: Literal["grant"] = "grant"
    request_id: str = Field(min_length=1, description="Echoed back on the attestation.")
    grant_json: str = Field(min_length=1)


class EdgeAttestation(_Strict):
    """Pi to Mac. What the shutter said after being asked to move.

    `refused` is a first-class outcome rather than an error. A shutter refusing a
    grant it cannot verify is the system working, and it is the thing this
    project most wants to be able to show.
    """

    kind: Literal["attestation"] = "attestation"
    request_id: str = Field(min_length=1)
    attestation_json: str = ""
    refused: bool = False
    refusal_reason: str = ""
    position: str = Field(
        default="",
        description=(
            "Where the shield is. Set on a refusal too, because a refused grant "
            "means the shield did not move and the shutter still knows where it "
            "is. Reporting `unknown` there would throw away a true fact. Empty "
            "only when the shutter could not be reached at all, which is the one "
            "case where the position genuinely is unknown."
        ),
    )
    commanded_angle: int | None = None


EdgeMessage = Annotated[
    EdgeHello
    | EdgeFrameHeader
    | EdgeError
    | EdgeGrant
    | EdgeAttestation
    | EdgeChallengeRequest
    | EdgeChallenge,
    Field(discriminator="kind"),
]

_EdgeMessageAdapter: TypeAdapter[EdgeMessage] = TypeAdapter(EdgeMessage)


def decode_edge_message(raw: str | bytes) -> EdgeMessage:
    """Parse one text message off the link, or raise `ValidationError`.

    Raises rather than returning None. A message this process cannot understand
    arriving on the link that moves a physical shield is not a condition to
    shrug at, and the caller closes the link on it.
    """
    return _EdgeMessageAdapter.validate_json(raw)
