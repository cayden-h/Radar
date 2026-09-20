import Foundation

/// The four events the camera path added to `WS /v1/stream` on 2026-09-20.
///
/// They are modelled here rather than decoded loosely because the app's decoder
/// throws on an unknown `kind`, and a hub that learned four new events would
/// otherwise put every client into a permanent "you may be behind" state once a
/// second. See `app/backend/hawkeye_backend/models/events.py`, which is the
/// authority these mirror field for field.

/// A camera thumbnail, for the moments a full MJPEG stream is not held open.
///
/// The watch is why this exists: it has no MJPEG decoder and no direct path to
/// the hub, so it gets frames the way it gets everything else, as an envelope
/// relayed through the phone.
struct CameraFrame: Decodable, Sendable, Hashable {
    /// JPEG bytes. Encodes as base64 in JSON, which is what the hub sends.
    var jpeg: Data
    var capturedAt: Date
    var source: Provenance.Source

    /// Whether this frame was current when the hub published it.
    ///
    /// **False means the view must not draw it as the room now.** It is a true
    /// statement about the last thing the camera saw and nothing more. A frozen
    /// picture of an empty room is the most dangerous thing this app can show,
    /// and this flag is the only thing standing between the app and doing it.
    var live: Bool

    /// The room this camera covers. One fixed camera sees one room.
    var room: String?

    enum CodingKeys: String, CodingKey {
        case jpeg = "jpeg_base64"
        case capturedAt = "captured_at"
        case source, live, room
    }
}

/// One line the camera produced about what it is seeing.
///
/// **Not a `TranscriptLine`.** That type is one line of the caller-to-911
/// conversation, and rendering a camera observation as one would present it as
/// something an operator was told.
struct Narration: Decodable, Sendable, Hashable, Identifiable {
    var text: String

    /// The room this camera covers. Never absent: one fixed camera sees one
    /// room, and a scoped claim must not read as an unscoped one.
    var room: String

    /// Seconds of observation this line summarizes.
    ///
    /// About one frame per second reaches the model, so narration is a sequence
    /// of glances rather than continuous tracking. Surface it rather than
    /// letting the line imply the camera watched continuously.
    var windowSeconds: Double
    var at: Date
    var source: Provenance.Source

    var id: Date { at }

    enum CodingKeys: String, CodingKey {
        case text, room, at, source
        case windowSeconds = "window_s"
    }
}

/// Whether the camera can see anybody. What closes the shutter again.
///
/// Personhood only. It never says who: there is no database and no lawful basis
/// for one, and identity is answered separately from the device roster.
struct Occupancy: Decodable, Sendable, Hashable {
    var personPresent: Bool
    var people: Int
    var room: String
    var at: Date
    var source: Provenance.Source

    enum CodingKeys: String, CodingKey {
        case people, room, at, source
        case personPresent = "person_present"
    }
}

/// Where the shield is, and what the shutter said about getting there.
///
/// `positionBasis` is always `commanded` and never `measured`. The SG92R is
/// open-loop with no feedback, so this is the angle the servo was told to reach
/// and never the angle the shield arrived at. A jammed shield attests open
/// while covering the lens, and the only thing that catches that is the frame
/// itself being dark.
struct ShieldReport: Decodable, Sendable, Hashable {
    /// `open`, `closed`, or `unknown`. Unknown only when the shutter could not
    /// be reached at all; a refusal carries the real, unchanged position.
    var position: String
    var positionBasis: String
    var commandedAngle: Int?
    var requestedAction: String

    /// **Not an error.** The shutter declining to move because something could
    /// not prove it was allowed to uncover the camera is this project working.
    var refused: Bool
    var refusalReason: String
    var reason: String
    var at: Date
    var source: Provenance.Source

    /// What the interior view should draw.
    var state: ShieldState {
        if refused { return .refused }
        switch position {
        case "open": return .open
        case "closed": return .closed
        default: return .closed
        }
    }

    enum CodingKeys: String, CodingKey {
        case position, refused, reason, at, source
        case positionBasis = "position_basis"
        case commandedAngle = "commanded_angle"
        case requestedAction = "requested_action"
        case refusalReason = "refusal_reason"
    }
}
