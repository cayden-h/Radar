"""The camera path, standalone. No agents, no network, no Gemini.

    python3 -m hawkeye_vision                        # live Brio
    python3 -m hawkeye_vision --fixture clip.mp4     # replay a file
    python3 -m hawkeye_vision --record out/inc-1     # also write segments
    python3 -m hawkeye_vision --fixture clip.mp4 --render print.mp4 --headless

Press q to stop.

This is the phase deliverable and the thing to run when something looks wrong
later: it exercises capture, lighting, tracking and recording with nothing else
in the way.
"""

from __future__ import annotations

import argparse
import contextlib
import logging

import cv2

from hawkeye_vision.config import VisionConfig
from hawkeye_vision.enhance import to_detection_input
from hawkeye_vision.frames import Frame, FrameSource
from hawkeye_vision.lighting import LightingClassifier, mean_luminance
from hawkeye_vision.overlay import draw
from hawkeye_vision.profiles import CaptureProfile, for_mode
from hawkeye_vision.record import SegmentWriter
from hawkeye_vision.render import OverlayRenderer
from hawkeye_vision.track import Detection, TrackBook

logger = logging.getLogger(__name__)


def _source(args: argparse.Namespace) -> FrameSource:
    if args.fixture:
        from hawkeye_vision.fixture import FileFixture

        return FileFixture(args.fixture)

    from hawkeye_vision.webcam import MacCamera

    return MacCamera(index=args.camera)


def detect_for_frame(
    tracker, frame: Frame, profile: CaptureProfile
) -> list[Detection]:
    """Detections for one frame, or none. Never raises.

    `build_tracker` covers a detector that fails to LOAD. This covers one that
    fails mid-incident, which is the case that actually costs footage: an
    exception out of `tracker.update` propagates through the frame loop and
    ends capture, taking the recording with it.

    The recording is the artifact that gets hashed into the chain and emailed
    to a police department. The tracker is only a corroborating view. Losing
    the second must never cost the first, so the except here is deliberately
    broad: no failure from a detector is worth stopping a recording for.
    """
    if not (profile.detect and tracker.available):
        return []

    try:
        if hasattr(tracker, "set_confidence"):
            tracker.set_confidence(profile.confidence)
        detection_input = to_detection_input(frame.image, enhance=profile.enhance)
        return list(
            tracker.update(
                Frame(
                    image=detection_input,
                    index=frame.index,
                    captured_at=frame.captured_at,
                )
            )
        )
    except Exception:
        logger.exception(
            "tracker failed on frame %d; continuing without a measured count",
            frame.index,
        )
        return []


def _run(
    args: argparse.Namespace,
    config: VisionConfig,
    source: FrameSource,
    writer: SegmentWriter | None,
    renderer: OverlayRenderer | None,
    classifier: LightingClassifier,
    book: TrackBook,
    tracker,
) -> None:
    """The frame loop. Everything it touches is already open, and will be closed."""
    for frame in source.frames():
        luminance = mean_luminance(frame.image)
        mode = classifier.update(luminance)
        profile = for_mode(mode, config)

        # The recorder gets the frame exactly as it came off the sensor,
        # before any enhancement and before any overlay.
        if writer is not None:
            writer.write(frame)

        book.ingest(detect_for_frame(tracker, frame, profile), frame_index=frame.index)

        # Drawn once, whoever wants it. `draw` returns a copy, so neither the
        # print nor the window can reach back into the frame the recorder took.
        overlaid = (
            draw(frame.image, book, mode, luminance)
            if (renderer is not None or not args.headless)
            else None
        )
        if renderer is not None and overlaid is not None:
            renderer.write(overlaid)

        if args.headless:
            if frame.index % 15 == 0:
                logger.info(
                    "frame %d  %s  luma %.1f  people %d",
                    frame.index, mode.value, luminance, book.people_visible,
                )
            continue

        cv2.imshow("Hawk Eye vision", overlaid)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", help="Replay this mp4 instead of opening the camera.")
    parser.add_argument(
        "--camera", type=int, default=0,
        help="AVFoundation device index. 0 is the Brio; see webcam.MacCamera.",
    )
    parser.add_argument("--record", help="Directory to write mp4 segments into.")
    parser.add_argument(
        "--render",
        help=(
            "Write one mp4 with the overlay burned in. The film print, not the "
            "record; --record still writes clean evidence alongside it."
        ),
    )
    parser.add_argument("--headless", action="store_true", help="No window; log only.")
    args = parser.parse_args()

    config = VisionConfig()
    classifier = LightingClassifier(config)
    book = TrackBook(config)

    from hawkeye_vision.yolo_tracker import build_tracker

    tracker = build_tracker(config)
    if not tracker.available:
        logger.error("running without measured counts: %s", tracker.reason)

    # One ExitStack, entered before anything is opened. The camera is opened
    # first and the writer second, so a writer that fails to construct, for
    # instance an unwritable --record path, would otherwise leak the camera
    # handle. That is the device-busy failure that then blocks the next run.
    with contextlib.ExitStack() as closing:
        closing.callback(cv2.destroyAllWindows)

        source = _source(args)
        closing.callback(source.close)

        writer: SegmentWriter | None = None
        if args.record:
            writer = SegmentWriter(
                args.record, fps=config.day_fps, segment_frames=config.day_fps * 10
            )
            closing.callback(_report_sealed, writer)
            closing.callback(writer.close)

        renderer: OverlayRenderer | None = None
        if args.render:
            renderer = OverlayRenderer(args.render, fps=config.day_fps)
            closing.callback(renderer.close)

        _run(args, config, source, writer, renderer, classifier, book, tracker)


def _report_sealed(writer: SegmentWriter) -> None:
    """Said after the writer has closed, so the final segment is counted."""
    logger.info("sealed %d segments", len(writer.sealed))


if __name__ == "__main__":
    main()
