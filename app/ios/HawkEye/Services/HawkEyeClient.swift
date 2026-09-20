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

    /// Notices raised by the sensing agents, newest first.
    ///
    /// A notice is information the resident acts on. It does not raise an
    /// incident and it does not dial; a human tap still does that.
    var notices: [Notice] { get }

    /// Dismiss one. Local to this device: the notice stays in the sealed log.
    func dismissNotice(_ id: String)

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

    /// Forgets the open incident on this phone. **Front-end only** — the
    /// backend has no stand-down route (see `app/CLAUDE.md`), so this does
    /// not tell `master` anything and is not a claim that the 911 call was
    /// actually ended. It exists so ending a call on this screen frees
    /// `raiseIncident` to open a new one; without it, `incident` stays set
    /// until the backend eventually sends `resolved`, and the 911 button
    /// silently does nothing in the meantime.
    func dismissIncident()

    /// The roster. Empty until loaded.
    var household: [HouseholdMember] { get }

    /// Devices seen on the network that nobody claims. Binding candidates.
    var unclaimedDevices: [ObservedDevice] { get }

    /// Vouch for a presence, this session only. Suppresses its notices.
    func approvePresence(_ presenceID: String) async throws

    /// Name a visitor and optionally bind a device. Permanent.
    func rememberVisitor(name: String, kind: HouseholdMember.Kind, deviceID: String?) async throws

    /// Remove a member. Their devices become unclaimed again.
    func forgetMember(_ memberID: String) async throws

    /// Refresh the roster and the unclaimed device list.
    func refreshHousehold() async

    /// The resident's current leg on the call bridge. Defaults to `.watching`
    /// and stays there for as long as no incident is open.
    ///
    /// This is client-tracked state, not something the hub streams back on
    /// `incident` frames: the backend has no wire field for it, only the
    /// `POST /v1/incident/{id}/mode` route that changes it. Set optimistically
    /// on a successful call to `setParticipationMode`.
    var participationMode: ParticipationMode { get }

    /// State of the call to the 911 operator. Mirrors `incident?.callState`
    /// so a view asking "is a call happening" does not have to unwrap
    /// `incident` first; `.notPlaced` when there is no open incident.
    var callState: CallState { get }

    /// Switches the resident's leg on the bridge. `mode` moving toward
    /// `.fullVoice` must only ever be called from a human-initiated control —
    /// see the automation rule on `ParticipationMode`.
    func setParticipationMode(_ mode: ParticipationMode) async throws

    /// The `TAKE OVER` control. Moves straight to `.fullVoice`; always a
    /// human action, held for 1.5s in the UI before this is called.
    func takeOver() async throws
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
    case notice(Notice)
    case error(code: String, message: String)
}

extension HubEvent: Decodable {
    private enum CodingKeys: String, CodingKey {
        case kind
        case state, phase, incident, line, instruction, result, note, notice, code, message
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
        case "notice":
            self = .notice(try c.decode(Notice.self, forKey: .notice))
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
