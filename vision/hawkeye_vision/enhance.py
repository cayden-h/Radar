"""Making a dim frame legible to the detector.

Scope, because there are two enhancements in this system and confusing them
would be serious:

- **This one** runs before detection, on the Pi or the Mac, so YOLO has usable
  contrast in low light. It affects what is detected. It never touches the
  frame handed to the segment writer.
- **The client one** runs in the iOS app and the replay console, so a resident
  can see the room. It affects what a human sees and nothing else.

Neither one is ever applied to the recorded mp4. Those segments are hashed into
the chain and emailed to a police department, so brightening them is altering
evidence rather than adjusting a picture.
"""

from __future__ import annotations

import cv2
import numpy as np


def to_detection_input(image: np.ndarray, *, enhance: bool) -> np.ndarray:
    """Return the image the detector should run on.

    With `enhance` false this is the frame as captured, returned as-is.

    With `enhance` true the frame is converted to greyscale and put through
    CLAHE, which equalises contrast in local tiles rather than globally. That
    matters in a dark room, where a global stretch is dominated by one bright
    window or lamp and leaves the person in the corner as dark as they started.

    Greyscale rather than colour because colour in a gain-boosted low-light
    frame is mostly chroma noise, and the detector does better without it.

    Never mutates its argument. The same frame object goes to the recorder.
    """
    if not enhance:
        return image

    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    equalised = clahe.apply(grey)
    return cv2.cvtColor(equalised, cv2.COLOR_GRAY2BGR)
