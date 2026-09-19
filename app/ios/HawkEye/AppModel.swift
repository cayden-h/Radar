import Foundation
import Observation

/// The app's one piece of shared state: which hub we are on, and the client
/// that hub gave us.
///
/// There are exactly two stages, Connect and Main, and this type owns the
/// transition between them. There is no third stage, no onboarding and no
/// settings, per `app/CLAUDE.md`.
@MainActor
@Observable
final class AppModel {

    enum Stage: Sendable, Hashable {
        case connect
        case main(hubName: String)
    }

    private(set) var stage: Stage = .connect
    private(set) var connectError: String?
    private(set) var verifyingHubID: String?

    let browser: any HubBrowsing
    let client: any HawkEyeClienting

    init() {
        if Config.useMocks {
            browser = MockHubBrowser()
            client = MockHawkEyeClient()
        } else {
            browser = BonjourHubBrowser()
            client = LiveHawkEyeClient()
        }
    }

    func startDiscovery() {
        connectError = nil
        browser.start()
    }

    /// Tapping a hub row. Short verifying state, then the main app.
    func connect(to hub: Hub) async {
        guard verifyingHubID == nil else { return }
        connectError = nil
        verifyingHubID = hub.id

        async let minimum: Void = Task.sleep(for: Config.minimumVerifyDuration)
        do {
            try await client.connect(to: hub)
            _ = try? await minimum
            browser.stop()
            stage = .main(hubName: hub.name)
        } catch {
            _ = try? await minimum
            connectError = (error as? LocalizedError)?.errorDescription
                ?? "Could not connect to \(hub.name)."
        }
        verifyingHubID = nil
    }
}
