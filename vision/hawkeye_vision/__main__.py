"""The camera path, standalone. No agents, no network, no Gemini.

    python3 -m hawkeye_vision                        # live Brio
    python3 -m hawkeye_vision --fixture clip.mp4     # replay a file
    python3 -m hawkeye_vision --record out/inc-1     # also write segments

Press q to stop.

This is the phase deliverable and the thing to run when something looks wrong
later: it exercises capture, lighting, tracking and recording with nothing else
in the way.
"""

from __future__ import annotations

import argparse
import logging

import cv2

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.enhance import to_detection_input
from hawkeye_vision.frames import Frame, FrameSource
from hawkeye_vision.lighting import LightingClassifier, mean_luminance
from hawkeye_vision.overlay import draw
from hawkeye_vision.profiles import for_mode
from hawkeye_vision.record import SegmentWriter
from hawkeye_vision.track import TrackBook

logger = logging.getLogger(__name__)


def _source(args: argparse.Namespace) -> FrameSource:
    if args.fixture:
        from hawkeye_vision.fixture import FileFixture

        return FileFixture(args.fixture)

    from hawkeye_vision.webcam import MacCamera

    return MacCamera(index=args.camera)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", help="Replay this mp4 instead of opening the camera.")
    parser.add_argument(
        "--camera", type=int, default=0,
        help="AVFoundation device index. 0 is the Brio; see webcam.MacCamera.",
    )
    parser.add_argument("--record", help="Directory to write mp4 segments into.")
    parser.add_argument("--headless", action="store_true", help="No window; log only.")
    args = parser.parse_args()

    config = VisionConfig()
    classifier = LightingClassifier(config)
    book = TrackBook(config)

    from hawkeye_vision.yolo_tracker import build_tracker

    tracker = build_tracker(config)
    if not tracker.available:
        logger.error("running without measured counts: %s", tracker.reason)

    source = _source(args)
    writer = (
        SegmentWriter(args.record, fps=config.day_fps, segment_frames=config.day_fps * 10)
        if args.record
        else None
    )

    try:
        for frame in source.frames():
            luminance = mean_luminance(frame.image)
            mode = classifier.update(luminance)
            profile = for_mode(mode, config)

            # The recorder gets the frame exactly as it came off the sensor,
            # before any enhancement and before any overlay.
            if writer is not None:
                writer.write(frame)

            if profile.detect and tracker.available:
                if hasattr(tracker, "set_confidence"):
                    tracker.set_confidence(profile.confidence)
                detection_input = to_detection_input(frame.image, enhance=profile.enhance)
                detections = tracker.update(
                    Frame(
                        image=detection_input,
                        index=frame.index,
                        captured_at=frame.captured_at,
                    )
                )
            else:
                detections = []

            book.ingest(detections, frame_index=frame.index)

            if args.headless:
                if frame.index % 15 == 0:
                    logger.info(
                        "frame %d  %s  luma %.1f  people %d",
                        frame.index, mode.value, luminance, book.people_visible,
                    )
                continue

            cv2.imshow("Hawk Eye vision", draw(frame.image, book, mode, luminance))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        source.close()
        if writer is not None:
            writer.close()
            logger.info("sealed %d segments", len(writer.sealed))
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
