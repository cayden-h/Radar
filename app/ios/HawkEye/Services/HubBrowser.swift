import Foundation
import Network
import Observation

/// Discovers Hawk Eye hubs on the network the phone is already joined to.
///
/// Read `Hub` for why this is a list of hubs and not a list of WiFi SSIDs.
/// The one-line version: enumerating nearby SSIDs from a third-party iOS app
/// requires the `NEHotspotHelper` entitlement, which we do not have.
@MainActor
protocol HubBrowsing: AnyObject {
    var hubs: [Hub] { get }
    var phase: DiscoveryPhase { get }
    func start()
    func stop()
}

// MARK: - Live

/// Bonjour discovery over `_hawkeye._tcp` using `NWBrowser`.
///
/// Requires both `NSLocalNetworkUsageDescription` and an `NSBonjourServices`
/// entry naming the exact service type. Missing either one produces no results
/// and no error, which is the single most common way this silently fails.
@MainActor
@Observable
final class BonjourHubBrowser: HubBrowsing {

    private(set) var hubs: [Hub] = []
    private(set) var phase: DiscoveryPhase = .idle

    @ObservationIgnored private var browser: NWBrowser?
    @ObservationIgnored private let pairedHubIDs: Set<String>

    init(pairedHubIDs: Set<String> = PairingStore.pairedHubIDs()) {
        self.pairedHubIDs = pairedHubIDs
    }

    func start() {
        guard browser == nil else { return }
        phase = .searching

        let params = NWParameters()
        params.includePeerToPeer = true

        let descriptor = NWBrowser.Descriptor.bonjourWithTXTRecord(
            type: Config.bonjourServiceType,
            domain: Config.bonjourDomain
        )
        let browser = NWBrowser(for: descriptor, using: params)

        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch state {
                case .failed(let error):
                    self.phase = .failed(Self.describe(error))
                case .cancelled:
                    if case .connected = self.phase { return }
                    self.phase = .idle
                default:
                    break
                }
            }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            let mapped = results.compactMap { Self.hub(from: $0) }
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.hubs = mapped
                    .map { hub in
                        var hub = hub
                        hub.paired = self.pairedHubIDs.contains(hub.id)
                        return hub
                    }
                    // Paired hubs first, then strongest signal, then name.
                    .sorted { lhs, rhs in
                        if lhs.paired != rhs.paired { return lhs.paired }
                        if (lhs.signal ?? 0) != (rhs.signal ?? 0) {
                            return (lhs.signal ?? 0) > (rhs.signal ?? 0)
                        }
                        return lhs.name < rhs.name
                    }
                if case .connected = self.phase { return }
                if case .verifying = self.phase { return }
                self.phase = self.hubs.isEmpty ? .searching : .found
            }
        }

        self.browser = browser
        browser.start(queue: .main)
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }

    // MARK: Mapping

    private nonisolated static func hub(from result: NWBrowser.Result) -> Hub? {
        guard case .service(let name, _, _, _) = result.endpoint else { return nil }

        var signal: Double?
        var ansName: String?
        var display = name
        var host: String?
        var port: Int?

        if case .bonjour(let txt) = result.metadata {
            if let raw = txt["signal"], let value = Double(raw) {
                signal = min(max(value, 0), 1)
            }
            ansName = txt["ans"]
            if let friendly = txt["name"], !friendly.isEmpty {
                display = friendly
            }
            // The address the hub actually bound, published rather than
            // resolved. `Hub.host` says why; the short version is that a
            // service instance name is not a hostname and `URLSession` cannot
            // resolve one.
            if let advertised = txt["host"], !advertised.isEmpty {
                host = advertised
            }
            if let raw = txt["port"], let value = Int(raw) {
                port = value
            }
        }

        return Hub(
            id: name,
            name: display,
            endpoint: endpointDescription(result),
            signal: signal,
            paired: false,
            host: host,
            port: port,
            ansName: ansName
        )
    }

    private nonisolated static func endpointDescription(_ result: NWBrowser.Result) -> String? {
        for interface in result.interfaces {
            switch interface.type {
            case .wifi: return "Wi-Fi"
            case .wiredEthernet: return "Ethernet"
            case .cellular: return "Cellular"
            default: continue
            }
        }
        return nil
    }

    private nonisolated static func describe(_ error: NWError) -> String {
        // The overwhelmingly likely cause is the local network prompt being
        // declined, so say that rather than surfacing a POSIX code.
        "Radar cannot see this network. Allow Local Network access for Radar in Settings, then try again."
    }
}

// MARK: - Mock

/// Fabricated hubs, so the Connect screen is fully demoable with no Pi present.
///
/// Switched on by `Config.useMocks`. The timings here are chosen to look like a
/// real discovery: one hub appears quickly, a second a beat later, because a
/// list that snaps into existence fully formed reads as fake.
@MainActor
@Observable
final class MockHubBrowser: HubBrowsing {

    private(set) var hubs: [Hub] = []
    private(set) var phase: DiscoveryPhase = .idle

    @ObservationIgnored private var task: Task<Void, Never>?

    func start() {
        guard task == nil else { return }
        phase = .searching
        hubs = []

        task = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(1100))
            guard let self, !Task.isCancelled else { return }
            self.hubs = [
                Hub(id: "hawkeye-home", name: "Home", endpoint: "Wi-Fi",
                    signal: 0.92, paired: true, host: "127.0.0.1",
                    port: Config.defaultHubPort, ansName: "home.hub.hawkeye.ai")
            ]
            self.phase = .found
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }
}

// MARK: - Direct

/// Surfaces a single, known hub without any discovery.
///
/// Bonjour is the honest mechanism when the hub advertises itself, but for a
/// live demo it is fragile: it needs the advertisement to exist and a
/// service-instance name to resolve as an HTTP host. This browser skips all of
/// that and hands the Connect screen the one hub named by `Config.directHubURL`,
/// so the identical connect/verify/stream path runs against a hub whose address
/// we already know.
///
/// `ansName` is deliberately `nil`: the `GET /v1/hub` handshake only enforces an
/// identity match when Bonjour advertised one, so a direct hub is trusted for
/// its address and still identified (and displayed) by what `/v1/hub` returns.
@MainActor
@Observable
final class DirectHubBrowser: HubBrowsing {

    private(set) var hubs: [Hub] = []
    private(set) var phase: DiscoveryPhase = .idle

    @ObservationIgnored private let url: URL

    init(url: URL) {
        self.url = url
    }

    func start() {
        let host = url.host ?? "hub"
        hubs = [
            Hub(
                id: "direct-\(host)",
                name: "Home hub (\(host))",
                endpoint: "Wi-Fi",
                signal: 1.0,
                paired: true,
                port: url.port,
                ansName: nil
            )
        ]
        phase = .found
    }

    func stop() {
        hubs = []
        phase = .idle
    }
}

// MARK: - Pairing

/// Which hubs this device has connected to before. One resident, one device,
/// so `UserDefaults` is the right size of tool. This is not credentials: the
/// hub identity that matters is its ANSName, verified on connect.
enum PairingStore {
    private static let key = "hawkeye.pairedHubIDs"

    static func pairedHubIDs() -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: key) ?? [])
    }

    static func remember(_ hubID: String) {
        var ids = pairedHubIDs()
        ids.insert(hubID)
        UserDefaults.standard.set(Array(ids), forKey: key)
    }
}
