import Foundation
import Observation

/// Every network call in the app goes through this one type, so the backend can
/// be swapped without touching a view.
///
/// There are exactly two implementations: `LiveHawkEyeClient`, which talks to a
/// hub over REST and a WebSocket, and `MockHawkEyeClient`, which scripts the
/// same sequence in process. `Config.useMocks` chooses.
///
/// Both emit exactly the same types, including verifications, because the demo
/// must not depend on hardware being alive and must not look different when it
/// is not.
@MainActor
protocol HawkEyeClienting: AnyObject {

    /// The live interior view. Updated on every `state` frame.
    var interior: InteriorState { get }

    /// The open incident, or nil when nothing is happening.
    var incident: Incident? { get }

    /// The live 911 transcript, oldest first.
    var transcript: [TranscriptLine] { get }

    /// Instructions from `agents/caller`, oldest first.
    var instructions: [Instruction] { get }

    /// ANS verification results, newest first. Discarded claims included, and
    /// especially: the refusal path is the thing worth showing.
    var verifications: [VerificationResult] { get }

    /// What the hub said about itself on the `hello` frame.
    var hello: HubHello? { get }

    /// Connection health, surfaced so the app never pretends to be live when
    /// the stream has dropped.
    var link: LinkState { get }

    /// Set when the stream skipped a sequence number, so the UI can say the
    /// view may be behind rather than quietly drawing a stale house.
    var missedFrames: Bool { get }

    /// Opens the connection to a hub. Throws if the hub cannot be reached or
    /// does not answer with the identity it advertised.
    func connect(to hub: Hub) async throws

    func disconnect()

    /// Raises an incident to `agents/master`. The manual path.
    func raiseIncident(_ type: IncidentType) async throws

    /// Sends free-text context to `master`, which makes it available to
    /// `caller` for the rest of the call.
    func sendContext(_ text: String) async throws
}

enum LinkState: Sendable, Hashable {
    case offline
    case connecting
    case live
    /// The stream dropped and is backing off before retrying.
    case reconnecting

    var label: String {
        switch self {
        case .offline: "Not connected"
        case .connecting: "Connecting"
        case .live: "Live"
        case .reconnecting: "Reconnecting"
        }
    }
}

enum HawkEyeClientError: Error, LocalizedError {
    case notConnected
    case badEndpoint
    case identityMismatch(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .notConnected: "Not connected to a hub."
        case .badEndpoint: "That hub did not give a usable address."
        case .identityMismatch(let why): why
        case .transport(let why): why
        }
    }
}

// MARK: - Wire format

/// The first frame on every websocket connection. Tells the client what it just
/// joined.
///
/// `hubANSName` is the name the hub is anchored to. The app displays it and
/// checks it against what Bonjour advertised. **That is a consistency check and
/// not ANS verification**, which is per claim and lives on the `verification`
/// event.
struct HubHello: Codable, Sendable, Hashable {
    var hubName: String
    var hubANSName: String
    var mode: String
    var streamProtocolVersion: Int = 1
    var activeIncidentID: String?
    /// Sequence of the oldest event still buffered, for gap recovery.
    var replayFromSeq: Int?

    enum CodingKeys: String, CodingKey {
        case mode
        case hubName = "hub_name"
        case hubANSName = "hub_ansname"
        case streamProtocolVersion = "stream_protocol_version"
        case activeIncidentID = "active_incident_id"
        case replayFromSeq = "replay_from_seq"
    }
}

/// The payload of one websocket frame. A tagged union discriminated on `kind`.
///
/// **The payload envelope differs per kind and is not uniformly named
/// `payload`.** That is the backend's shape and this mirrors it exactly rather
/// than normalising it, so a reader can diff this file against
/// `app/backend/schema/` line for line.
enum HubEvent: Sendable, Hashable {
    case hello(HubHello)
    case state(InteriorState)
    case incident(phase: IncidentPhase, incident: Incident)
    case transcript(TranscriptLine)
    case instruction(Instruction)
    case verification(VerificationResult)
    case context(ContextNote)
    case error(code: String, message: String)
}

extension HubEvent: Decodable {
    private enum CodingKeys: String, CodingKey {
        case kind
        case state, phase, incident, line, instruction, result, note, code, message
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let kind = try c.decode(String.self, forKey: .kind)
        switch kind {
        case "hello":
            // `hello` carries its fields inline rather than under a key.
            self = .hello(try HubHello(from: decoder))
        case "state":
            self = .state(try c.decode(InteriorState.self, forKey: .state))
        case "incident":
            self = .incident(
                phase: try c.decode(IncidentPhase.self, forKey: .phase),
                incident: try c.decode(Incident.self, forKey: .incident)
            )
        case "transcript":
            self = .transcript(try c.decode(TranscriptLine.self, forKey: .line))
        case "instruction":
            self = .instruction(try c.decode(Instruction.self, forKey: .instruction))
        case "verification":
            self = .verification(try c.decode(VerificationResult.self, forKey: .result))
        case "context":
            self = .context(try c.decode(ContextNote.self, forKey: .note))
        case "error":
            self = .error(
                code: try c.decode(String.self, forKey: .code),
                message: try c.decode(String.self, forKey: .message)
            )
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .kind, in: c,
                debugDescription: "Unknown hub event kind: \(kind)"
            )
        }
    }
}

/// Every websocket frame is one of these.
///
/// `seq` is monotonic and server-wide: a gap means the client missed a frame and
/// the UI says so. The two prologue frames sent on connect (the `hello` and the
/// replayed last state) both carry `seq` 0 and are excluded from gap detection.
struct Envelope: Decodable, Sendable {
    var seq: Int
    var at: Date
    /// Set when the event belongs to an incident.
    var incidentID: String?
    var payload: HubEvent

    enum CodingKeys: String, CodingKey {
        case seq, at, payload
        case incidentID = "incident_id"
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        seq = try c.decodeIfPresent(Int.self, forKey: .seq) ?? 0
        at = try c.decodeIfPresent(Date.self, forKey: .at) ?? Date()
        incidentID = try c.decodeIfPresent(String.self, forKey: .incidentID)
        payload = try c.decode(HubEvent.self, forKey: .payload)
    }
}

/// Tracks `seq` across a connection and reports gaps.
///
/// A gap is not fatal and must not tear the stream down. It is surfaced,
/// because a client that silently skipped an incident frame and kept drawing is
/// exactly the quiet lie this project is built against.
struct SequenceTracker: Sendable {
    private(set) var last: Int?
    private(set) var missed = false

    /// Returns true when this frame left a hole behind it.
    @discardableResult
    mutating func accept(_ seq: Int) -> Bool {
        // The connect prologue is sent with seq 0 and is not part of the
        // sequence. Nothing before the first real frame can be a gap.
        guard seq > 0 else { return false }
        defer { last = seq }
        guard let last else { return false }
        if seq > last + 1 {
            missed = true
            return true
        }
        return false
    }

    mutating func reset() {
        last = nil
        missed = false
    }
}

enum HawkEyeCoding {

    /// The hub emits RFC 3339 UTC with microsecond precision, e.g.
    /// `2026-09-20T04:12:33.843012Z`. `JSONDecoder.iso8601` rejects fractional
    /// seconds outright, so both shapes are parsed here rather than discovering
    /// it at 3am against a live hub.
    static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            if let date = try? fractional.parse(text) { return date }
            if let date = try? plain.parse(text) { return date }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Not an ISO 8601 timestamp: \(text)"
            )
        }
        return d
    }

    static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(fractional.format(date))
        }
        return e
    }

    /// `Date.ISO8601FormatStyle` is a value type and `Sendable`, unlike
    /// `ISO8601DateFormatter`, so these can be shared across isolation domains
    /// under strict concurrency.
    private static let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
    private static let plain = Date.ISO8601FormatStyle()
}
