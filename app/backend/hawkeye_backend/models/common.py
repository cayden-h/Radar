"""Shared primitives, and the enforcement point for the honesty rule.

Root CLAUDE.md: "Simulated inputs are labeled in the data itself, not just in a
comment. A simulated reading must not be presentable as measured by accident."

That is enforced here rather than by convention. `Provenance` is a required
field on every reading that leaves this service, `source` is a closed enum, and
`source_class` is derived from the source rather than supplied by the caller, so
no producer can mislabel a simulated number as a measured one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


def utc_now() -> datetime:
    """Timezone-aware now. Every timestamp in this service is UTC."""
    return datetime.now(UTC)


class Source(StrEnum):
    """What physically produced a reading.

    Closed set on purpose. Adding a value is a deliberate act, and each new value
    must be placed into MEASURED_SOURCES or SIMULATED_SOURCES below.
    """

    # Live Channel State Information off the Pi, nexmon_csi patched firmware.
    NEXMON_CSI = "nexmon-csi"
    # Real CSI, captured at the house earlier, replayed through the same pipeline.
    # Measured, but not live. The venue demo runs on this.
    REPLAY_CSI = "replay-csi"
    # RuView's synthetic CSI generator. Not measured.
    RUVIEW_SIM = "ruview-sim"
    # WiFi RSSI motion detection: the MacBook's CoreWLAN RSSI polled at ~3 Hz and
    # run through the collector->features->classifier pipeline. MEASURED_LIVE
    # because the radio genuinely measured the link, and the disturbance is a real
    # physical perturbation of it, not a synthesized number. It is a coarser
    # modality than nexmon CSI - one scalar per tick, not per-subcarrier amplitude
    # - but it is measured, so it sits on the measured side and must not fail to
    # SIMULATED the way an unknown source string does.
    WIFI_RSSI = "wifi-rssi"
    # A real MQ-7 carbon monoxide sensor on the Pi's GPIO, through an MCP3008 ADC.
    # No such sensor exists today; the value is here so the driver seam is honest.
    MQ7_GPIO = "mq7-gpio"
    # The literal string root CLAUDE.md requires for the simulated gas reading.
    DEMO_TRIGGER = "demo-trigger"
    # The resident typed it into the "what is happening" box.
    USER_INPUT = "user-input"
    # The 911 operator said it on the phone call.
    OPERATOR_AUDIO = "operator-audio"
    # An agent derived it from other readings rather than sensing it.
    AGENT_INFERENCE = "agent-inference"
    # A real SG92R on the Pi's GPIO, driven through pigpio. DERIVED rather than
    # MEASURED, and that is not a technicality: the SG92R is open-loop and has
    # no position feedback, so a shutter position is the angle we *commanded*
    # and never the angle the shield reached. A jammed shield reports open.
    SERVO_GPIO = "servo-gpio"
    # The shutter's stub backend: a servo that exists only as a number. Named
    # separately from SERVO_GPIO so that running the demo with no hardware
    # attached cannot present as running it with hardware attached.
    SERVO_STUB = "servo-stub"
    # The Logitech Brio 101 on USB, frames read live off the device. MEASURED_LIVE
    # because a person is in front of a lens and the sensor recorded them.
    CAMERA_UVC = "camera-uvc"
    # Real footage, captured at the house earlier, replayed through the same
    # pipeline. Mirrors REPLAY_CSI exactly: measured, but not live. The venue
    # fallback runs on this when the camera cannot be set up in the room.
    REPLAY_VIDEO = "replay-video"
    # A synthetic video fixture: flat colour fields, luminance ramps, generated
    # test footage. Not measured, and named separately so a test rig cannot
    # present as a camera.
    CAMERA_SIM = "camera-sim"


class SourceClass(StrEnum):
    """How much weight a reading's origin can bear.

    Derived from `Source`, never supplied. This is the field the iOS app renders
    a "simulated" badge from.
    """

    MEASURED_LIVE = "measured-live"
    MEASURED_REPLAY = "measured-replay"
    SIMULATED = "simulated"
    HUMAN = "human"
    DERIVED = "derived"


_SOURCE_CLASS: dict[Source, SourceClass] = {
    Source.NEXMON_CSI: SourceClass.MEASURED_LIVE,
    Source.MQ7_GPIO: SourceClass.MEASURED_LIVE,
    Source.REPLAY_CSI: SourceClass.MEASURED_REPLAY,
    Source.RUVIEW_SIM: SourceClass.SIMULATED,
    Source.WIFI_RSSI: SourceClass.MEASURED_LIVE,
    Source.DEMO_TRIGGER: SourceClass.SIMULATED,
    Source.USER_INPUT: SourceClass.HUMAN,
    Source.OPERATOR_AUDIO: SourceClass.HUMAN,
    Source.AGENT_INFERENCE: SourceClass.DERIVED,
    Source.SERVO_GPIO: SourceClass.DERIVED,
    Source.SERVO_STUB: SourceClass.SIMULATED,
    Source.CAMERA_UVC: SourceClass.MEASURED_LIVE,
    Source.REPLAY_VIDEO: SourceClass.MEASURED_REPLAY,
    Source.CAMERA_SIM: SourceClass.SIMULATED,
}

MEASURED_SOURCES: frozenset[Source] = frozenset(
    s for s, c in _SOURCE_CLASS.items() if c in (SourceClass.MEASURED_LIVE, SourceClass.MEASURED_REPLAY)
)
SIMULATED_SOURCES: frozenset[Source] = frozenset(
    s for s, c in _SOURCE_CLASS.items() if c is SourceClass.SIMULATED
)


def classify_source(source: Source) -> SourceClass:
    """Map a source onto how much weight it can bear."""
    return _SOURCE_CLASS[source]


class Provenance(BaseModel):
    """Where a reading came from. Required on every reading. No default.

    `source_class` and `simulated` are computed from `source`, so a producer
    cannot claim a demo-trigger reading was measured.
    """

    model_config = ConfigDict(frozen=True)

    source: Source = Field(description="What physically produced this reading. Required.")
    producer: str = Field(
        description="Which agent or component emitted it, e.g. 'agents/master'."
    )
    ansname: str | None = Field(
        default=None,
        description="ANSName of the producing agent, when it has one.",
    )
    detail: str | None = Field(
        default=None,
        description="Free text, e.g. the capture session id a replay came from.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_class(self) -> SourceClass:
        """Derived from `source`. Never supplied by the caller."""
        return classify_source(self.source)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def simulated(self) -> bool:
        """True when this number was not measured by any instrument.

        The iOS app renders a badge off this. It is derived, so it cannot lie.
        """
        return classify_source(self.source) is SourceClass.SIMULATED
