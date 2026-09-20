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

    /// `GET /v1/household`. The roster.
    static let householdPath = "/v1/household"

    /// `GET /v1/household/unclaimed-devices`. Binding candidates.
    static let unclaimedDevicesPath = "/v1/household/unclaimed-devices"

    /// `POST /v1/household/remember`. Name a visitor, optionally bind a device.
    static let rememberPath = "/v1/household/remember"

    /// `DELETE /v1/household/members/{id}`. Base path; the member id is appended.
    static let householdMembersPath = "/v1/household/members"

    /// `POST /v1/presences/{id}/approve`. Base path; the presence id is appended.
    static let presencesPath = "/v1/presences"

    // MARK: Behaviour

    /// How long the Connect screen shows the verifying state before entering
    /// the app. Real in live mode (it is the handshake); scripted in mocks.
    static let minimumVerifyDuration: Duration = .milliseconds(900)

    /// Reconnect backoff bounds for the WebSocket client.
    static let reconnectMinDelay: Duration = .milliseconds(500)
    static let reconnectMaxDelay: Duration = .seconds(8)

    // MARK: Mock script

    /// Which scripted incident the mock runs.
    ///
    /// Both scripts are complete and both run off the same sensor loop and the
    /// same detection timer, so switching here changes the demo and nothing
    /// else. There is no scenario branch anywhere in the views.
    enum MockScenario {

        /// A person walks into the living room. Once respiration is acquired
        /// they are a person, and `agents/intruder` finds that no registered
        /// device accounts for them, so they are unexpected. They then route
        /// across the apartment toward the resident. Two tracked presences,
        /// different rooms, both moving. This is the demo.
        case burglary

        /// The child's breathing signature in the second bedroom stops being
        /// resolvable while carbon monoxide climbs, and `respiration_lost_s`
        /// starts counting. Whether a dispatcher should expect an answer from
        /// that room is the thing the product moves.
        case fire
    }

    /// The scripted incident the mock runs. Burglary is the demo.
    static let mockScenario: MockScenario = .burglary

    /// In mock mode, how long after connecting the scripted detection fires.
    /// Set to `nil` to disable it and drive the demo from the buttons only.
    ///
    /// **It raises an alert, not a call.** Hawk Eye never dials 911 on its own;
    /// a human tap is what releases `agents/caller`. The detection is what makes
    /// the tap informed: by the time the resident presses a button, the system
    /// already knows who is in the house, in which room, and whether it expected
    /// them to be there.
    static let mockDetectionAfter: Duration? = .seconds(14)

    /// How long the mock waits after a presence's breathing signature goes
    /// missing before it surfaces the loss. The real agent uses the elapsed
    /// time since the last resolvable signature; this is the mock's stand-in.
    static let mockRespirationLostDelay: Duration = .seconds(6)

    /// `.burglary` only. How long the new presence has no respiration signature,
    /// and so is `unconfirmed`, exactly like the curtain over the laundry vent.
    /// After this, respiration is acquired and it becomes a confirmed person the
    /// system did not expect.
    static let mockIntruderIdentifiedAfter: Double = 5

    /// Seconds an unexpected presence must hold before it becomes a notice.
    ///
    /// Mirrors `HAWKEYE_NOTICE_HOLD_S` on the hub, whose default is the same 5.
    /// The mock scripts the notice rather than re-deriving the rule in Swift:
    /// the rule lives in `hawkeye_backend/notices/detector.py` and two copies
    /// of a rule is how they drift.
    static let mockNoticeHoldSeconds: Double = 5

    /// `.burglary` only. The intruder's route through the apartment, as
    /// `(zone, seconds dwelled there)`, walked in order from the zone they are
    /// first seen in. Positions are interpolated between zone centroids across
    /// `mockIntruderTravelSeconds`, so the presence visibly moves rather than
    /// teleporting from room to room.
    ///
    /// The resident is on the left of the apartment, so the intruder crosses the
    /// whole plan to reach them and the two are in different rooms the entire
    /// time until the last leg. That is the frame the project is built around.
    static let mockIntruderRoute: [(zone: String, dwellS: Double)] = [
        ("living_room", 11),
        ("kitchen", 9),
        ("hallway", .infinity),
    ]

    /// Seconds spent in transit between two zones on that route.
    static let mockIntruderTravelSeconds: Double = 4.5

    // MARK: Site

    /// One resident, hardcoded. No accounts, no onboarding. See `app/CLAUDE.md`.
    static let siteID = "hawkeye-demo-home"
    static let residentName = "Cayden"
}
