import Foundation

/// The single file that decides where the app gets its data.
///
/// Everything mocked/live in this app is switched from here and nowhere else.
/// If you are hunting for a hardcoded localhost or a stray demo branch, there
/// is only one place to look.
enum Config {

    // MARK: The switch

    /// `true` runs the whole app against in-process mocks: no Pi, no hub, no
    /// network at all. The Connect screen still discovers hubs, they are just
    /// fabricated ones, and the incident path runs a scripted 911 call.
    ///
    /// This exists because the demo cannot depend on hardware being alive.
    /// Flip it to `false` and the identical UI runs against the real hub.
    static let useMocks = true

    // MARK: Live backend

    /// Base URL for REST calls when `useMocks` is false.
    ///
    /// In practice this is replaced at runtime by the endpoint resolved from
    /// Bonjour when a hub is selected, so this value is only the fallback for
    /// running against a hosted instance directly.
    static let fallbackBaseURL = URL(string: "https://hub.hawkeye.ai")!

    /// The Bonjour service type Hawk Eye hubs advertise.
    /// Must match the `NSBonjourServices` entry in the Info.plist exactly or
    /// `NWBrowser` returns nothing and fails silently.
    static let bonjourServiceType = "_hawkeye._tcp"

    /// Bonjour domain. `local.` is the only one that matters here.
    static let bonjourDomain = "local."

    /// The port the hub's API listens on when its Bonjour record does not
    /// publish one. `HAWKEYE_PORT` in `app/backend`, whose default is this.
    static let defaultHubPort = 8787

    // MARK: Hub API paths
    //
    // These are `app/backend`'s routes, verbatim. Every one of them has a
    // matching example payload in `app/backend/schema/`, and the Codable types
    // in `Models/` are matched against those files rather than against prose.

    /// `WS /v1/stream`. One socket, every event kind.
    static let streamPath = "/v1/stream"

    /// `GET /v1/hub`. Hub identity and health.
    static let hubPath = "/v1/hub"

    /// `GET /v1/state`. The interior state, so the view has something to draw
    /// before the first stream tick.
    static let statePath = "/v1/state"

    /// `POST /v1/incident`. The resident raises an incident.
    static let incidentPath = "/v1/incident"

    // MARK: Behaviour

    /// How long the Connect screen shows the verifying state before entering
    /// the app. Real in live mode (it is the handshake); scripted in mocks.
    static let minimumVerifyDuration: Duration = .milliseconds(900)

    /// Reconnect backoff bounds for the WebSocket client.
    static let reconnectMinDelay: Duration = .milliseconds(500)
    static let reconnectMaxDelay: Duration = .seconds(8)

    // MARK: Mock script

    /// In mock mode, how long after connecting the scripted fall is detected.
    /// Set to `nil` to disable it and drive the demo from the buttons only.
    ///
    /// **It raises an alert, not a call.** Hawk Eye never dials 911 on its own;
    /// a human tap is what releases `agents/caller`. The detection is what makes
    /// the tap informed: by the time the resident presses Faint, the system
    /// already knows who is down, in which room, whether they are breathing, and
    /// for how long.
    static let mockFallDetectedAfter: Duration? = .seconds(22)

    // MARK: Site

    /// One resident, hardcoded. No accounts, no onboarding. See `app/CLAUDE.md`.
    static let siteID = "hawkeye-demo-home"
    static let residentName = "Cayden"
}
