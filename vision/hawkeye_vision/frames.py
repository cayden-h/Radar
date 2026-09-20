"""One frame, and the interface anything that produces frames must satisfy.

The seam `docs/swapping-in-real-parts.md` asks every simulated thing to have.
`FileFixture` is what the tests and the venue fallback run on, `MacCamera` is
the Brio on this laptop, and a `PiV4L2` will be the Brio on the Pi. Nothing
downstream knows which one it has.

`source` is part of the interface rather than a detail of each implementation,
for the same reason `ShutterBackend.source` is: it is what stops a video file
presenting as a camera.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
from hawkeye_backend.models.common import Source


def utc_now() -> datetime:
    """Timezone-aware now. Every timestamp in this package is UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Frame:
    """One image off the camera, and when it was taken.

    `captured_at` is not decoration. A track overlay drawn on the client has to
    align to the video rather than drift against it, and a claim has to say
    which instant it describes.
    """

    image: np.ndarray
    index: int
    captured_at: datetime


class FrameSource(Protocol):
    """Something that produces frames and says what it is."""

    source: Source

    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source is exhausted or closed."""

    def close(self) -> None:
        """Release the device or file handle."""
