"""Covers the classification map that enforces the honesty rule.

`classify_source` in `hawkeye_backend.models.common` is the single point where
a `Source` is mapped onto how much weight it can bear. These tests exist so
that a new camera source (or any future source) cannot be added to the enum
without also being placed into `_SOURCE_CLASS`, and so a simulated source can
never be classified as measured by accident.
"""


def test_camera_sources_classify_by_how_much_weight_they_bear():
    """A fixture mp4 must not be presentable as the live Brio."""
    from hawkeye_backend.models.common import Source, SourceClass, classify_source

    assert classify_source(Source.CAMERA_UVC) is SourceClass.MEASURED_LIVE
    assert classify_source(Source.REPLAY_VIDEO) is SourceClass.MEASURED_REPLAY
    assert classify_source(Source.CAMERA_SIM) is SourceClass.SIMULATED


def test_synthetic_video_is_flagged_simulated_and_live_camera_is_not():
    from hawkeye_backend.models.common import Provenance, Source

    synthetic = Provenance(source=Source.CAMERA_SIM, producer="vision/fixture")
    live = Provenance(source=Source.CAMERA_UVC, producer="vision/webcam")

    assert synthetic.simulated is True
    assert live.simulated is False


def test_every_source_member_has_a_classification():
    """The map must stay exhaustive. A new Source with no entry is a KeyError
    at runtime in whatever agent happens to emit it first, which is the worst
    possible place to discover it."""
    from hawkeye_backend.models.common import Source, classify_source

    for source in Source:
        assert classify_source(source) is not None
