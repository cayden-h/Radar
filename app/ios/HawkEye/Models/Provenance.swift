import Foundation

/// Where a reading came from.
///
/// This is the backend's `Provenance` object, field for field. It is required on
/// every reading the hub emits, and it is how the honesty rule from the root
/// `CLAUDE.md` is enforced in the data rather than in a comment.
///
/// `sourceClass` and `simulated` are **computed on the server from `source`**,
/// so a producer cannot label a simulated number as measured even by accident.
/// The client reads them and never recomputes them.
struct Provenance: Codable, Sendable, Hashable {

    /// What physically produced the reading. Closed set, mirrored from
    /// `schema/enums.json`.
    enum Source: String, Codable, Sendable, Hashable, CaseIterable {
        /// Live CSI off the Pi, nexmon_csi patched firmware.
        case nexmonCSI = "nexmon-csi"
        /// Real CSI captured earlier and replayed. Measured, not live.
        case replayCSI = "replay-csi"
        /// RuView's synthetic CSI generator. Not measured.
        case ruviewSim = "ruview-sim"
        /// A real MQ-7 carbon monoxide sensor. No such sensor exists today.
        case mq7GPIO = "mq7-gpio"
        /// The literal string the root `CLAUDE.md` requires for a simulated
        /// gas reading. No gas sensor was purchased.
        case demoTrigger = "demo-trigger"
        /// The resident typed it into the "what is happening" box.
        case userInput = "user-input"
        /// The 911 operator said it on the call.
        case operatorAudio = "operator-audio"
        /// An agent derived it rather than sensing it.
        case agentInference = "agent-inference"
    }

    /// How much weight the reading's origin can bear. Derived server-side.
    enum SourceClass: String, Codable, Sendable, Hashable, CaseIterable {
        case measuredLive = "measured-live"
        case measuredReplay = "measured-replay"
        case simulated
        case human
        case derived
    }

    var source: Source
    /// Which agent or component emitted it, e.g. `agents/environment`.
    var producer: String
    /// The ANSName of the producing agent, when it has one.
    var ansName: String?
    /// Free text, e.g. the capture session a replay came from.
    var detail: String?
    var sourceClass: SourceClass
    /// True when the number was not measured by any instrument. The app renders
    /// a badge off this, and it is derived server-side, so it cannot lie.
    var simulated: Bool

    enum CodingKeys: String, CodingKey {
        case source, producer, detail, simulated
        case ansName = "ansname"
        case sourceClass = "source_class"
    }
}
