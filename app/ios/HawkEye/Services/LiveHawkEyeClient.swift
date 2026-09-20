import Foundation
import Network
import Observation

/// The real client. REST for commands, one WebSocket for everything streaming.
///
/// Every path here is one of `app/backend`'s routes, and every type it decodes
/// has a matching example file in `app/backend/schema/`. The backend is the
/// authority on the wire format; this file follows it.
///
/// Nothing here is demo-specific: if the hub is up, this is what runs. When the
/// hub is not up, `Config.useMocks` selects `MockHawkEyeClient` instead and the
/// views are identical.
@MainActor
@Observable
final class LiveHawkEyeClient: HawkEyeClienting {

    private(set) var interior = InteriorState()
    private(set) var incident: Incident?
    private(set) var transcript: [TranscriptLine] = []
    private(set) var instructions: [Instruction] = []
    private(set) var verifications: [VerificationResult] = []
    private(set) var notices: [Notice] = []
    private(set) var hello: HubHello?
    private(set) var link: LinkState = .offline
    private(set) var missedFrames = false
    private(set) var household: [HouseholdMember] = []
    private(set) var unclaimedDevices: [ObservedDevice] = []

    /// The resident's leg of the call bridge. Client-tracked: the backend has
    /// no wire field for it on `incident`/`state` frames, only the
    /// `POST /v1/incident/{id}/mode` route that changes it. Set optimistically
    /// by `setParticipationMode` on success.
    private(set) var participationMode: ParticipationMode = .watching

    /// Mirrors `incident?.callState`, `.notPlaced` with nothing open, so a
    /// view can ask this directly instead of unwrapping `incident` first.
    var callState: CallState { incident?.callState ?? .notPlaced }

    // The camera path, added 2026-09-20. The views for these are T32 and T33;
    // the state is carried here now so the hub's events are not dropped on the
    // floor in the meantime.

    /// The newest camera thumbnail off the stream.
    ///
    /// Check `cameraFrame?.live` before drawing it. False means it is the last
    /// thing the camera saw and not the room now, and drawing it as current is
    /// the single most dangerous thing this app can do.
    private(set) var cameraFrame: CameraFrame?

    /// What the camera has said, newest first.
    private(set) var narration: [Narration] = []
    private(set) var occupancy: Occupancy?

    /// Where the lens shield is, including when it refused to move.
    private(set) var shield: ShieldReport?

    /// Ceiling on retained narration lines. A long incident produces one a
    /// second and no screen needs an hour of them.
    static let narrationLimit = 200

    @ObservationIgnored private var baseURL: URL = Config.fallbackBaseURL
    @ObservationIgnored private let session = URLSession(configuration: .default)
    @ObservationIgnored private var socket: URLSessionWebSocketTask?
    @ObservationIgnored private var pump: Task<Void, Never>?
    @ObservationIgnored private var sequence = SequenceTracker()

    // MARK: Connect

    func connect(to hub: Hub) async throws {
        disconnect()
        link = .connecting

        baseURL = try Self.resolveBaseURL(for: hub)

        // GET /v1/hub is the handshake: it returns the ANSName the hub is
        // anchored to, and we refuse to proceed if it does not match what
        // Bonjour advertised.
        //
        // **This is a consistency check and it is not ANS verification.**
        // ANS verification is per claim, it happens in the agent mesh, and it
        // reaches this app on the `verification` event. The UI never claims
        // otherwise and must not start to.
        let status = try await fetchHubStatus()
        if let advertised = hub.ansName, status.hubANSName != advertised {
            link = .offline
            throw HawkEyeClientError.identityMismatch(
                "This hub identified itself as \(status.hubANSName), not \(advertised)."
            )
        }

        // Draw the house immediately rather than waiting for the first tick.
        if let state = try? await fetchState() { interior = state }

        PairingStore.remember(hub.id)
        openStream()
    }

    func dismissNotice(_ id: String) {
        notices.removeAll { $0.id == id }
    }

    func disconnect() {
        pump?.cancel()
        pump = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        sequence.reset()
        missedFrames = false
        hello = nil
        link = .offline
        participationMode = .watching
    }

    // MARK: Commands

    func raiseIncident(_ type: IncidentType) async throws {
        _ = try await post(
            path: Config.incidentPath,
            body: RaiseIncidentRequest(incidentType: type, note: nil)
        )
    }

    /// Local only — see the protocol doc. The next `state`/`incident` frame
    /// from the hub is the real source of truth and will overwrite this if
    /// the backend still considers the incident open.
    func dismissIncident() {
        incident = nil
    }

    func sendContext(_ text: String) async throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard let incident else { throw HawkEyeClientError.notConnected }
        _ = try await post(
            path: "\(Config.incidentPath)/\(incident.id)/context",
            body: ContextRequest(text: trimmed)
        )
    }

    /// Switches the resident's leg on the bridge via `POST /v1/incident/{id}/mode`.
    /// `byHuman` defaults `true` on `SetParticipationModeRequest`, matching the
    /// backend's rule that only the automation itself is allowed to ask for
    /// `false` — nothing on this client does that. See `ParticipationMode`'s doc.
    func setParticipationMode(_ mode: ParticipationMode) async throws {
        guard let incident else { throw HawkEyeClientError.notConnected }
        _ = try await post(
            path: "\(Config.incidentPath)/\(incident.id)/mode",
            body: SetParticipationModeRequest(mode: mode)
        )
        participationMode = mode
    }

    /// `TAKE OVER`. Always a human action — the UI holds this for 1.5s before
    /// calling it — so it goes straight to `.fullVoice` rather than through
    /// whisper first.
    func takeOver() async throws {
        try await setParticipationMode(.fullVoice)
    }

    // MARK: Household

    /// Vouches for a presence for this session only. Nothing persists: the
    /// backend suppresses that presence's notices and the client re-syncs the
    /// roster in case the vouch changed anything recognisable there, though it
    /// normally will not.
    func approvePresence(_ presenceID: String) async throws {
        _ = try await post(path: "\(Config.presencesPath)/\(presenceID)/approve")
    }

    /// Names a visitor and optionally binds the device that just joined.
    /// Permanent, unlike `approvePresence`.
    ///
    /// On success the returned member is appended locally and, if a device was
    /// bound, dropped from `unclaimedDevices`, so the household list and the
    /// remember sheet's device picker both update without a refetch.
    func rememberVisitor(name: String, kind: HouseholdMember.Kind, deviceID: String?) async throws {
        let data = try await post(
            path: Config.rememberPath,
            body: RememberRequest(name: name, kind: kind, deviceID: deviceID)
        )
        let member = try HawkEyeCoding.decoder.decode(HouseholdMember.self, from: data)
        household.removeAll { $0.id == member.id }
        household.append(member)
        if let deviceID {
            unclaimedDevices.removeAll { $0.id == deviceID }
        }
    }

    /// Removes a member. Their devices become unclaimed again on the backend;
    /// `refreshHousehold` is what would pick that back up, since a forgotten
    /// device is not implied by anything this call returns.
    func forgetMember(_ memberID: String) async throws {
        try await delete(path: "\(Config.householdMembersPath)/\(memberID)")
        household.removeAll { $0.id == memberID }
    }

    /// Refreshes both the roster and the unclaimed device list. Called once on
    /// `HomeView` appearing, and again after any change that might have moved a
    /// device between the two lists in a way the mutating call did not already
    /// account for locally.
    func refreshHousehold() async {
        // Both routes wrap their array under a named key rather than returning
        // it bare, so the response is decoded into a one-field container
        // rather than `[HouseholdMember].self` / `[ObservedDevice].self`.
        struct MembersResponse: Decodable { var members: [HouseholdMember] }
        struct DevicesResponse: Decodable { var devices: [ObservedDevice] }

        async let members = try? get(MembersResponse.self, path: Config.householdPath)
        async let devices = try? get(DevicesResponse.self, path: Config.unclaimedDevicesPath)
        if let members = await members { household = members.members }
        if let devices = await devices { unclaimedDevices = devices.devices }
    }

    // MARK: Stream

    private func openStream() {
        guard var components = URLComponents(
            url: baseURL.appendingPathComponent(Config.streamPath),
            resolvingAgainstBaseURL: false
        ) else { return }
        components.scheme = (components.scheme == "https") ? "wss" : "ws"
        guard let url = components.url else { return }

        let task = session.webSocketTask(with: url)
        socket = task
        task.resume()

        pump = Task { [weak self] in
            await self?.pumpMessages(task)
        }
    }

    private func pumpMessages(_ task: URLSessionWebSocketTask) async {
        link = .live

        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                switch message {
                case .data(let data):
                    apply(data)
                case .string(let string):
                    apply(Data(string.utf8))
                @unknown default:
                    break
                }
            } catch {
                guard !Task.isCancelled else { return }
                link = .reconnecting
                // A reconnect starts a new sequence run. The hub's `hello`
                // names the oldest buffered seq, so a gap is reported rather
                // than papered over.
                sequence.reset()
                try? await Task.sleep(for: Config.reconnectMinDelay)
                guard !Task.isCancelled else { return }
                openStream()
                return
            }
        }
    }

    private func apply(_ data: Data) {
        guard let envelope = try? HawkEyeCoding.decoder.decode(Envelope.self, from: data) else {
            // An undecodable frame is a contract break, not a thing to ignore
            // quietly. It is dropped, and the missed-frame flag says the view
            // may be behind.
            missedFrames = true
            return
        }
        if sequence.accept(envelope.seq) { missedFrames = true }

        switch envelope.payload {
        case .hello(let value):
            hello = value
        case .state(let state):
            interior = state
        case .incident(let phase, let value):
            apply(phase: phase, incident: value)
        case .transcript(let line):
            upsert(line)
        case .instruction(let instruction):
            upsert(instruction)
        case .verification(let result):
            // Newest first. Discards included, and they are the point.
            verifications.removeAll { $0.id == result.id }
            verifications.insert(result, at: 0)
        case .notice(let notice):
            notices.removeAll { $0.id == notice.id }
            notices.insert(notice, at: 0)
        case .context(let note):
            // Echoed back so the app can confirm delivery. The incident carries
            // the authoritative list.
            if incident?.contextNotes.contains(note) == false {
                incident?.contextNotes.append(note)
            }
        case .error(let code, let message):
            // Never a silently dropped frame.
            missedFrames = true
            NSLog("hub error %@: %@", code, message)

        // ------------------------------------------------ the camera path

        case .frame(let value):
            // Kept whatever its `live` flag says, because the last frame seen is
            // a true statement. Every view reads `cameraFrame?.live` before
            // drawing it as the room now.
            cameraFrame = value
        case .narration(let value):
            // Newest first, and bounded. A long incident produces a line a
            // second and a wrist does not need an hour of them.
            narration.insert(value, at: 0)
            if narration.count > Self.narrationLimit {
                narration.removeLast(narration.count - Self.narrationLimit)
            }
        case .occupancy(let value):
            occupancy = value
        case .shield(let value):
            shield = value

        case .unrecognised(let kind):
            // The hub knows an event this build does not, which happens when
            // the two move at different speeds. Deliberately **not**
            // `missedFrames`: that flag means the view may be behind on state
            // it should have, and a new event type is not that.
            NSLog("hub sent an event this build does not know: %@", kind)
        }
    }

    private func apply(phase: IncidentPhase, incident value: Incident) {
        if phase == .raised, incident?.id != value.id {
            // A new incident starts with a clean screen. Nothing from the last
            // one belongs on this one.
            transcript = []
            instructions = []
            verifications = []
            participationMode = .watching
        }
        incident = value
        if value.status == .resolved || phase == .resolved {
            incident = nil
            transcript = []
            instructions = []
            verifications = []
            participationMode = .watching
        }
    }

    /// Transcript lines arrive partial and are then revised in place, matched on
    /// `line_id`, so this upserts rather than appending blindly.
    private func upsert(_ line: TranscriptLine) {
        if let i = transcript.firstIndex(where: { $0.id == line.id }) {
            transcript[i] = line
        } else {
            transcript.append(line)
        }
    }

    private func upsert(_ instruction: Instruction) {
        if let i = instructions.firstIndex(where: { $0.id == instruction.id }) {
            instructions[i] = instruction
        } else {
            instructions.append(instruction)
        }
    }

    // MARK: REST

    private func fetchHubStatus() async throws -> HubStatus {
        try await get(HubStatus.self, path: Config.hubPath)
    }

    private func fetchState() async throws -> InteriorState {
        try await get(InteriorState.self, path: Config.statePath)
    }

    private func get<T: Decodable>(_ type: T.Type, path: String) async throws -> T {
        let url = baseURL.appendingPathComponent(path)
        do {
            let (data, response) = try await session.data(from: url)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw HawkEyeClientError.transport("The hub is not able to answer right now.")
            }
            return try HawkEyeCoding.decoder.decode(T.self, from: data)
        } catch let error as HawkEyeClientError {
            throw error
        } catch {
            throw HawkEyeClientError.transport("Could not reach the hub: \(error.localizedDescription)")
        }
    }

    @discardableResult
    private func post(path: String, body: some Encodable) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try HawkEyeCoding.encoder.encode(body)
        return try await send(request)
    }

    /// A POST with no body, e.g. `/v1/presences/{id}/approve`, which acts on
    /// the id in the path and needs nothing else.
    @discardableResult
    private func post(path: String) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        return try await send(request)
    }

    private func delete(path: String) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "DELETE"
        _ = try await send(request)
    }

    @discardableResult
    private func send(_ request: URLRequest) async throws -> Data {
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw HawkEyeClientError.transport("The hub rejected that request.")
            }
            return data
        } catch let error as HawkEyeClientError {
            throw error
        } catch {
            throw HawkEyeClientError.transport(error.localizedDescription)
        }
    }

    // MARK: Endpoint resolution

    /// Turns a Bonjour result into an HTTP base URL.
    ///
    /// `<service>.<type>.<domain>` is resolvable by the system resolver, so it
    /// can be used directly as a host. That avoids hand-rolling an address
    /// resolution that would break on IPv6-only networks, and Bonjour names are
    /// what survive a DHCP lease change.
    private static func resolveBaseURL(for hub: Hub) throws -> URL {
        let host = "\(hub.id).\(Config.bonjourServiceType).\(Config.bonjourDomain)"
            .replacingOccurrences(of: " ", with: "\\032")
        let port = hub.port ?? Config.defaultHubPort
        guard let url = URL(string: "http://\(host):\(port)") else {
            throw HawkEyeClientError.badEndpoint
        }
        return url
    }
}
