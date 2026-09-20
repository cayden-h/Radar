"""Drawing the tracker's boxes onto a copy of a relayed frame.

**The relay is not the record.** `vision/` writes the evidence mp4 from the
frames it captured, unannotated, and this never touches that path. What is drawn
here is drawn onto a copy of a JPEG that is already on its way to a screen, and
it exists so that a person watching the live console can see what the detector
is seeing rather than take it on trust.

The hub cannot run YOLO - `ultralytics` is not in its environment, and putting
inference on the request path of the one service every surface talks to would be
a bad trade even if it were. So the boxes arrive as normalised coordinates from
`agents/vision`, which already ran the model, and this only rasterises them.

That split has one consequence worth stating out loud, because it is visible:
the boxes lag the picture slightly. They were measured on a frame a few hundred
milliseconds old and are drawn on the newest one. `TRACK_STALE_AFTER_S` in
`LiveCamera` is what stops that becoming a lie - past it, nothing is drawn at
all, because a box floating over a room the detector has stopped looking at is
worse than no box.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import cv2
import numpy as np

from hawkeye_backend.models.camera import TrackBox

logger = logging.getLogger(__name__)

#: BGR, because OpenCV. A green that survives both a dark room and a bright one.
BOX_COLOUR = (120, 220, 120)

#: Re-encode quality. High enough that the overlay does not visibly degrade the
#: frame, low enough that a 7 fps relay does not become the bottleneck.
JPEG_QUALITY = 85


def draw_tracks(jpeg: bytes, tracks: Sequence[TrackBox]) -> bytes:
    """Return the JPEG with boxes burned in, or the original if it cannot.

    **Never raises.** This sits between the camera and every surface that
    renders it, and a malformed box must not be able to take the live feed down.
    A failure here degrades to the unannotated frame, which is still true.
    """
    if not tracks:
        return jpeg

    try:
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jpeg

        height, width = image.shape[:2]
        for track in tracks:
            x1 = int(track.x1 * width)
            y1 = int(track.y1 * height)
            x2 = int(track.x2 * width)
            y2 = int(track.y2 * height)
            cv2.rectangle(image, (x1, y1), (x2, y2), BOX_COLOUR, 2)
            cv2.putText(
                image,
                f"person {track.track_id}  {track.confidence:.2f}",
                (x1, max(14, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                BOX_COLOUR,
                1,
                cv2.LINE_AA,
            )

        ok, encoded = cv2.imencode(
            ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        )
        if not ok:
            return jpeg
        return encoded.tobytes()
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning("could not draw tracks on a frame (%s); serving it clean", exc)
        return jpeg
