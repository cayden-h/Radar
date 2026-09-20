"""Record a short clip off the Brio, for the tests that need real people in them.

Synthetic rectangles are not people and YOLO will not detect them, so the
tracking integration tests need genuine footage. This records it.

    python3 -m hawkeye_vision.record_fixture tests/footage/person.mp4 --seconds 10

Walk in and out of frame while it runs. For the occlusion test, have two people
cross paths in front of the lens.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hawkeye_vision.record import SegmentWriter
from hawkeye_vision.webcam import MacCamera


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Where to write the mp4.")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--camera", type=int, default=1, help="AVFoundation device index.")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    wanted = args.seconds * args.fps

    with MacCamera(index=args.camera) as camera:
        # One segment holding the whole clip: this is a fixture, not a record.
        with SegmentWriter(output.parent, fps=args.fps, segment_frames=wanted + 1) as writer:
            for frame in camera.frames():
                writer.write(frame)
                if frame.index + 1 >= wanted:
                    break

    written = Path(writer.sealed[0].path)
    written.rename(output)
    print(f"wrote {output} ({wanted} frames)")


if __name__ == "__main__":
    main()
