import XCTest
@testable import Radar

/// `MockHawkEyeClient`'s call-bridge state: `participationMode` and
/// `callState`, and the two protocol methods that move them.
///
/// This is state, not networking, so it needs no hub and no simulator
/// pairing — same reasoning as `WatchWireTests`.
@MainActor
final class MockHawkEyeClientCallBridgeTests: XCTestCase {

    func testStartsWatchingByDefault() {
        let client = MockHawkEyeClient()
        XCTAssertEqual(client.participationMode, .watching)
    }

    func testNoCallMeansCallStateIsNotPlaced() {
        let client = MockHawkEyeClient()
        XCTAssertEqual(client.callState, .notPlaced)
    }

    func testTakeOverMovesToFullVoice() async throws {
        let client = MockHawkEyeClient()
        try await client.takeOver()
        XCTAssertEqual(client.participationMode, .fullVoice)
    }

    func testSettingWhisperUpdatesState() async throws {
        let client = MockHawkEyeClient()
        try await client.setParticipationMode(.whisper)
        XCTAssertEqual(client.participationMode, .whisper)
    }

    /// Setting the mode already in effect must not throw and must leave the
    /// state exactly as it was — the no-op guard in `setParticipationMode`.
    func testSettingTheCurrentModeIsANoOp() async throws {
        let client = MockHawkEyeClient()
        try await client.setParticipationMode(.watching)
        XCTAssertEqual(client.participationMode, .watching)
    }

    /// A raised incident starts every call in `.watching`, per the "silent is
    /// the default" rule in `app/CLAUDE.md`, even if a previous call on the
    /// same client instance left it somewhere louder.
    func testANewIncidentResetsParticipationModeToWatching() async throws {
        let client = MockHawkEyeClient()
        try await client.takeOver()
        XCTAssertEqual(client.participationMode, .fullVoice)
        try await client.raiseIncident(.burglary)
        XCTAssertEqual(client.participationMode, .watching)
    }
}
