import Foundation

/// The entire contract between the phone and the watch.
///
/// One snapshot going out, one command coming back, and nothing else. The watch
/// never speaks to the hub, so this file is the whole of its network surface and
/// is the only place to look when the two devices disagree.
///
/// Both types are deliberately small. A snapshot crosses WatchConnectivity on
/// every state change, and a wrist is not where a floorplan, a roster or a
/// verification feed belongs.
enum WatchWire {

    /// Key the snapshot travels under, in an application context or a message.
    static let snapshotKey = "snapshot"
    /// Key a command travels back under.
    static let commandKey = "command"
    /// Key the phone replies under when it has acted on a command.
    static let outcomeKey = "outcome"

    static func encode<T: Encodable>(_ value: T) throws -> Data {
        try HawkEyeCoding.encoder.encode(value)
    }

    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try HawkEyeCoding.decoder.decode(type, from: data)
    }
}

// MARK: - Phone to watch

/// Everything the watch is allowed to know, as of one moment on the phone.
///
/// Latest-wins by design. The watch holds no history the phone does not have,
/// per `app/CLAUDE.md`: "Hold state the phone does not have. If they disagree,
/// the phone wins and the watch says it is reconnecting."
struct WatchSnapshot: Codable, Sendable, Hashable {

    /// When the phone built this. The watch shows staleness off it rather than
    /// guessing from its own clock drift.
    var generatedAt: Date = .distantPast

    /// Whether the phone currently holds a live socket to the hub. False means
    /// the watch is looking at a picture the phone cannot refresh.
    var hubLinked: Bool = false

    /// The hub's display name, for the one line on the Idle screen.
    var hubName: String?

    /// Where the lens shield is, as the shutter attested it. Nil until the
    /// shutter has reported; the watch says so rather than assuming closed.
    var shield: ShieldStatus?

    /// The notice awaiting an answer, or nil when there is nothing to answer.
    var notice: WatchNotice?

    /// The last answer this watch gave, and what the hub did with it.
    var outcome: WatchOutcome?

    /// True when an incident is open on the hub right now. The watch shows it
    /// as a state, not as a screen: the live call surface is the phone's.
    var incidentOpen: Bool = false

    enum CodingKeys: String, CodingKey {
        case shield, notice, outcome
        case generatedAt = "generated_at"
        case hubLinked = "hub_linked"
        case hubName = "hub_name"
        case incidentOpen = "incident_open"
    }

    /// The resting snapshot, before the phone has said anything.
    static let unknown = WatchSnapshot()
}

/// A notice, trimmed to what fits on a wrist.
///
/// This is not `Notice`. It carries the camera's sentence and a thumbnail and
/// drops the zone, the severity and the provenance object, because none of the
/// three change what the resident does in the four seconds they have.
struct WatchNotice: Codable, Sendable, Hashable, Identifiable {

    var noticeID: String
    /// The camera's own sentence. **Never a generic "motion detected"**: that
    /// string on a wrist throws away the entire camera pivot. The phone refuses
    /// to build a `WatchNotice` without one; see `PhoneWatchRelay`.
    var narration: String
    /// The room the camera covers. One fixed camera sees one room.
    var room: String?
    var raisedAt: Date
    /// A JPEG thumbnail from the moment the shield opened, or nil when the
    /// shield never opened and there is genuinely nothing to show.
    var stillFrame: Data?
    /// Session-scoped. Carried so the phone can vouch for the right presence.
    var presenceID: String?

    /// True when the frame and the sentence came from the mock rather than from
    /// a camera.
    ///
    /// **Carried in the data, not in a comment**, per the honesty rule in the
    /// root `CLAUDE.md`: a scoped claim must not be presentable as an unscoped
    /// one by accident. The watch draws a marker off this, so a demo frame can
    /// never be mistaken on stage for something a lens saw.
    var simulated: Bool = false

    var id: String { noticeID }

    enum CodingKeys: String, CodingKey {
        case narration, room, simulated
        case noticeID = "notice_id"
        case raisedAt = "raised_at"
        case stillFrame = "still_frame"
        case presenceID = "presence_id"
    }
}

// MARK: - Watch to phone

/// The two things a wrist can say about a notice.
///
/// **There is no incident type here and there must never be one.** The pivot
/// left one type, Intrusion, so there is nothing to choose, which is the right
/// shape for a control someone uses while frightened.
///
/// "Remember this visitor" is deliberately absent: it names a person, and naming
/// needs a keyboard. It stays on the phone, and the Saved screen says so.
enum WatchAction: String, Codable, Sendable, Hashable, CaseIterable {

    /// Raise the incident. The only path to a phone call in the whole system.
    case startIncident = "start_incident"

    /// Vouch for this presence for this session. A mute button, and nothing
    /// persists. It is not the same control as remembering a visitor and the
    /// two must not be merged, or a stranger gets persisted because someone
    /// wanted a banner to go away.
    case expected

    var title: String {
        switch self {
        case .startIncident: "Start Incident"
        case .expected: "This is expected"
        }
    }

    /// What the watch says out loud after the hub has taken it.
    var pastTense: String {
        switch self {
        case .startIncident: "Incident started"
        case .expected: "Marked expected"
        }
    }

    /// Consequential actions are held, never tapped. 1.5 seconds, per
    /// `app/CLAUDE.md`: a wrist is the easiest surface in the world to press by
    /// accident, and an accidental tap here calls 911.
    var requiresHold: Bool {
        switch self {
        case .startIncident: true
        case .expected: false
        }
    }
}

/// One thing the resident did on the watch.
struct WatchCommand: Codable, Sendable, Hashable, Identifiable {
    var commandID: String
    var noticeID: String
    var action: WatchAction
    var issuedAt: Date

    var id: String { commandID }

    enum CodingKeys: String, CodingKey {
        case action
        case commandID = "command_id"
        case noticeID = "notice_id"
        case issuedAt = "issued_at"
    }
}

/// What the hub did with a command, relayed back so the watch can stop guessing.
///
/// `recorded` is the honest word and the only one the watch is allowed to use.
/// It is set from the hub's acknowledgement, never optimistically on send: a
/// watch that says "recorded" for something the hub never took is exactly the
/// quiet lie this project is built against.
struct WatchOutcome: Codable, Sendable, Hashable, Identifiable {

    enum Disposition: String, Codable, Sendable, Hashable {
        /// Sent to the phone, no acknowledgement yet.
        case pending
        /// The hub took it and it is in the sealed record.
        case recorded
        /// It did not reach the hub. The watch says so and offers the action again.
        case failed
    }

    var commandID: String
    var noticeID: String
    var action: WatchAction
    var disposition: Disposition
    /// When the hub acknowledged. Nil while pending or failed.
    var recordedAt: Date?
    /// Set when `disposition` is `failed`. Plain English, shown as is.
    var failureReason: String?

    var id: String { commandID }

    enum CodingKeys: String, CodingKey {
        case action, disposition
        case commandID = "command_id"
        case noticeID = "notice_id"
        case recordedAt = "recorded_at"
        case failureReason = "failure_reason"
    }
}
