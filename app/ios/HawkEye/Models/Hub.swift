import Foundation

/// A Hawk Eye hub discovered on the local network.
///
/// IMPORTANT, and this is a constraint rather than a design choice:
/// **this is not a list of WiFi networks.** iOS does not let a third-party app
/// enumerate nearby SSIDs. Doing that requires the `NEHotspotHelper`
/// entitlement, which Apple grants only to MFi hotspot vendors on request, and
/// which we do not have and will not get. `NEHotspotNetwork` only reports the
/// network you are already joined to, and only with Location permission.
///
/// So the honest mechanism is the one implemented here: the phone is already on
/// the home WiFi, and we browse Bonjour for Hawk Eye hubs advertising
/// `_hawkeye._tcp` on that network. The Connect screen is "which of your hubs",
/// not "which WiFi network".
struct Hub: Sendable, Hashable, Identifiable {

    /// Bonjour service name. Unique on a network, so it works as the identity.
    var id: String
    /// What the resident sees. The hub's own display name.
    var name: String
    /// Resolved endpoint description, for display only.
    var endpoint: String?
    /// 0...1, derived from the interface and RSSI hint the hub publishes in its
    /// TXT record. Nil when the hub does not publish one.
    var signal: Double?
    /// True when this device has paired with this hub before.
    var paired: Bool
    /// The hub's address on this network, published in its TXT record as
    /// `host`.
    ///
    /// **This is carried rather than resolved, deliberately.** The obvious
    /// design is to let `URLSession` resolve the Bonjour service instance, but
    /// `Hub Name._hawkeye._tcp.local.` is a service instance name and not a
    /// hostname, and `URLSession` cannot resolve one. The hub publishes the
    /// address it actually bound and the app dials that. See
    /// `app/backend/hawkeye_backend/discovery.py`.
    ///
    /// Nil for a hub advertising an older TXT record, which cannot be connected
    /// to and is reported as such rather than silently failing to resolve.
    var host: String?
    /// The port the hub serves its API on, from the Bonjour service record.
    /// Nil means fall back to `Config.defaultHubPort`.
    var port: Int?
    /// The hub's ANSName, published in its TXT record. Displayed because it is
    /// the identity everything downstream is anchored to.
    var ansName: String?

    var signalBars: Int {
        guard let signal else { return 0 }
        return max(1, min(4, Int((signal * 4).rounded(.up))))
    }
}

/// `GET /v1/hub`. Hub identity and health, hit after Bonjour discovery.
///
/// `healthy` means "the app may proceed", not "every agent is up". A tier 3
/// agent being unreachable does not block the app; a dead sensing pipeline does,
/// and the app says so rather than drawing an empty house.
struct HubStatus: Codable, Sendable, Hashable {

    /// One agent in the mesh, as seen from the hub.
    ///
    /// **This is reachability, not verification.** Verification is per claim and
    /// lives on the `verification` event, because an agent trusted ninety
    /// seconds ago may not be trusted now.
    struct AgentReachability: Codable, Sendable, Hashable, Identifiable {
        enum Reachability: String, Codable, Sendable, Hashable, CaseIterable {
            case reachable, unreachable, degraded, simulated
        }

        var name: String
        var ansName: String
        /// Build priority tier from `agents/CLAUDE.md`.
        var tier: Int
        var reachability: Reachability
        var lastSeenAt: Date?
        var latencyMs: Double?
        var detail: String?

        var id: String { name }

        enum CodingKeys: String, CodingKey {
            case name, tier, reachability, detail
            case ansName = "ansname"
            case lastSeenAt = "last_seen_at"
            case latencyMs = "latency_ms"
        }
    }

    /// Whether CSI is actually flowing.
    ///
    /// `frameRateHz` against `minUsefulFrameRateHz` is what catches the quiet
    /// failure named in `sensor/CLAUDE.md`: without a traffic generator you get
    /// beacons at roughly 10 Hz, which barely resolves breathing and so cannot
    /// tell a lost signature from a starved capture, with every component
    /// reporting healthy.
    struct SensorLiveness: Codable, Sendable, Hashable {
        var source: Provenance.Source
        /// Derived by the hub from `source`. Mirrors `Provenance.simulated`.
        var simulated: Bool
        var live: Bool
        var frameRateHz: Double?
        var minUsefulFrameRateHz: Double = 100
        var lastFrameAt: Date?
        var baselineHealthy: Bool
        var baselineAgeS: Double?
        var detail: String?

        enum CodingKeys: String, CodingKey {
            case source, simulated, live, detail
            case frameRateHz = "frame_rate_hz"
            case minUsefulFrameRateHz = "min_useful_frame_rate_hz"
            case lastFrameAt = "last_frame_at"
            case baselineHealthy = "baseline_healthy"
            case baselineAgeS = "baseline_age_s"
        }
    }

    var hubName: String
    /// The ANSName this hub is anchored to.
    var hubANSName: String
    var masterANSName: String
    var siteID: String
    var siteAddress: String
    /// `simulated` or `live`. Printed in the app, not hidden.
    var mode: String
    var version: String
    var healthy: Bool
    var serverTime: Date = .distantPast
    var uptimeS: Double = 0
    var sensor: SensorLiveness
    var agents: [AgentReachability] = []
    var activeIncidentID: String?
    var streamPath: String = "/v1/stream"

    enum CodingKeys: String, CodingKey {
        case mode, version, healthy, sensor, agents
        case hubName = "hub_name"
        case hubANSName = "hub_ansname"
        case masterANSName = "master_ansname"
        case siteID = "site_id"
        case siteAddress = "site_address"
        case serverTime = "server_time"
        case uptimeS = "uptime_s"
        case activeIncidentID = "active_incident_id"
        case streamPath = "stream_path"
    }
}

/// Where the Connect screen is in its lifecycle.
enum DiscoveryPhase: Sendable, Hashable {
    /// Browser has not started.
    case idle
    /// Browsing, nothing found yet. The quiet "Looking for your home" state.
    case searching
    /// At least one hub found.
    case found
    /// Verifying the selected hub's identity before entering the app.
    case verifying(hubID: String)
    /// Connected and past the Connect screen.
    case connected(hubID: String)
    /// Browser failed. Local network permission denied is the usual cause.
    case failed(String)
}
