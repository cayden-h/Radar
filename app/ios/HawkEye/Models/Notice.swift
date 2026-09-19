import Foundation

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

    var id: String { noticeID }

    enum CodingKeys: String, CodingKey {
        case severity, title, body, zone, room, provenance
        case noticeID = "notice_id"
        case presenceID = "presence_id"
        case raisedAt = "raised_at"
    }
}
