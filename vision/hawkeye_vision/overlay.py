"""Drawing what the tracker measured onto a copy of the frame.

**A copy, always.** The frame object handed to this function is the same one
going to the segment writer, and an overlay burned into a file that gets emailed
to a police department is evidence with graphics drawn on it.

This is the local preview. The iOS and replay-console overlays are a later phase
and draw from `vision.tracks[]` over the video element, which is why the boxes
are normalised: the same numbers work at any view size.
"""

from __future__ import annotations

import cv2
import numpy as np

from hawkeye_vision.lighting import LightingMode
from hawkeye_vision.track import TrackBook

_MODE_COLOUR: dict[LightingMode, tuple[int, int, int]] = {
    LightingMode.DAY: (120, 220, 120),
    LightingMode.LOW: (80, 180, 255),
    LightingMode.TOO_DARK: (80, 80, 240),
}


def draw(
    image: np.ndarray,
    book: TrackBook,
    mode: LightingMode,
    luminance: float,
) -> np.ndarray:
    """Return a copy of the frame with tracks and the status line drawn on it."""
    canvas = image.copy()
    height, width = canvas.shape[:2]
    colour = _MODE_COLOUR[mode]

    for track in book.active:
        x1 = int(track.bbox.x1 * width)
        y1 = int(track.bbox.y1 * height)
        x2 = int(track.bbox.x2 * width)
        y2 = int(track.bbox.y2 * height)

        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 2)
        cv2.putText(
            canvas,
            f"id {track.track_id}  {track.confidence:.2f}",
            (x1, max(14, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            colour,
            1,
            cv2.LINE_AA,
        )

    status = f"{mode.value}  luma {luminance:5.1f}  people {book.people_visible}"
    cv2.putText(
        canvas, status, (8, height - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA,
    )
    return canvas
