import Foundation

/// A still frame from the moment the shield cleared the lens.
///
/// A thumbnail, not the recording. This travels over WatchConnectivity to a
/// wrist, so it is deliberately small; the full segment stays on the hub and is
/// sealed into the replay record with everything else.
///
/// **The frame is what makes a notice answerable.** Before the camera pivot the
/// resident was asked to judge an unlabelled blob on a floorplan. Now they are
/// looking at the person they are being asked about, which is the difference
/// between "call the police or dismiss a banner you cannot evaluate" and "oh,
/// that is my brother".
struct NoticeFrame: Codable, Sendable, Hashable {
    /// JPEG bytes. Encodes as base64 in JSON, which is what the hub sends.
    var jpeg: Data
    var capturedAt: Date
    /// The room the camera covers. One fixed camera sees one room, and every
    /// vision claim carries its scope rather than implying it has none.
    var room: String?

    enum CodingKeys: String, CodingKey {
        case room
        case jpeg = "jpeg_base64"
        case capturedAt = "captured_at"
    }
}

/// Something the resident should know about, that is not an incident.
///
/// This is the backend's `Notice`, field for field, checked against
/// `app/backend/schema/event-notice.json`.
///
/// A notice does not raise an incident and does not dial. `app/CLAUDE.md`:
/// "An alert is information a person acts on. It is not a call."
struct Notice: Codable, Sendable, Hashable, Identifiable {

    /// How loudly to render it. Never a dispatch decision.
    enum Severity: String, Codable, Sendable, Hashable, CaseIterable {
        case info
        case attention
    }

    var noticeID: String
    var severity: Severity
    /// Short and factual. "Unexpected person".
    var title: String
    /// One line. Never contains the street address.
    var body: String
    var zone: String?
    /// The floorplan's display name for `zone`, e.g. "Living room". Resolved by
    /// the producer so no consumer has to re-derive it or parse it out of `body`.
    var room: String?
    /// Session-scoped only. We do not do person re-identification.
    var presenceID: String?
    var raisedAt: Date
    /// Required, same as every other reading.
    var provenance: Provenance

    /// The camera's own first sentence about what it is looking at, from
    /// `agents/vision`.
    ///
    /// Optional because it did not exist before the camera pivot and a hub that
    /// predates it must still decode. **When it is present it is what the
    /// notification says.** A generic "motion detected" on the wrist throws away
    /// the entire pivot; see `TASKS.md` T30.
    var narration: String?

    /// A still from the moment the shield opened. Nil until `agents/vision`
    /// produces one, and nil forever if the shield never opened.
    var stillFrame: NoticeFrame?

    var id: String { noticeID }

    /// What the resident actually reads. The camera's sentence when there is
    /// one, the producer's body line when there is not.
    var headline: String { narration ?? body }

    enum CodingKeys: String, CodingKey {
        case severity, title, body, zone, room, provenance, narration
        case stillFrame = "still_frame"
        case noticeID = "notice_id"
        case presenceID = "presence_id"
        case raisedAt = "raised_at"
    }
}
