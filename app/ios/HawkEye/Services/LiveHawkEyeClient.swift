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
    private(set) var hello: HubHello?
    private(set) var link: LinkState = .offline
    private(set) var missedFrames = false

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

    func disconnect() {
        pump?.cancel()
        pump = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        sequence.reset()
        missedFrames = false
        hello = nil
        link = .offline
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
        }
    }

    private func apply(phase: IncidentPhase, incident value: Incident) {
        if phase == .raised, incident?.id != value.id {
            // A new incident starts with a clean screen. Nothing from the last
            // one belongs on this one.
            transcript = []
            instructions = []
            verifications = []
        }
        incident = value
        if value.status == .resolved || phase == .resolved {
            incident = nil
            transcript = []
            instructions = []
            verifications = []
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
