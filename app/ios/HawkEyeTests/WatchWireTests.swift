import XCTest
@testable import Hawk_Eye

/// The phone-to-watch contract, tested where it can be: the codec and the rule.
///
/// Neither needs a paired device, a simulator pairing, or a running hub, which
/// is the reason both were pulled out of the views in the first place.
final class WatchWireTests: XCTestCase {

    // MARK: Codec

    func testSnapshotSurvivesARoundTrip() throws {
        let snapshot = WatchSnapshot(
            generatedAt: Date(timeIntervalSince1970: 1_758_000_000),
            hubLinked: true,
            hubName: "Chestnut",
            shield: ShieldStatus(
                state: .open,
                changedAt: Date(timeIntervalSince1970: 1_757_999_990),
                grantNonce: "nonce-7f3a91"
            ),
            notice: WatchNotice(
                noticeID: "ntc-p4",
                narration: "A person in a dark jacket is in your living room.",
                room: "Living room",
                raisedAt: Date(timeIntervalSince1970: 1_757_999_995),
                stillFrame: Data([0xFF, 0xD8, 0xFF, 0xE0]),
                presenceID: "p4",
                simulated: true
            ),
            outcome: nil,
            incidentOpen: false
        )

        let data = try WatchWire.encode(snapshot)
        let decoded = try WatchWire.decode(WatchSnapshot.self, from: data)
        XCTAssertEqual(decoded, snapshot)
    }

    func testCommandSurvivesARoundTrip() throws {
        let command = WatchCommand(
            commandID: "cmd-1",
            noticeID: "ntc-p4",
            action: .startIncident,
            issuedAt: Date(timeIntervalSince1970: 1_758_000_100)
        )
        let decoded = try WatchWire.decode(WatchCommand.self, from: WatchWire.encode(command))
        XCTAssertEqual(decoded, command)
    }

    /// The frame is base64 in JSON, which is what the hub sends and what
    /// WatchConnectivity carries. Asserted so a future coder change cannot
    /// quietly switch the representation.
    func testStillFrameTravelsAsBase64() throws {
        let notice = WatchNotice(
            noticeID: "n",
            narration: "x",
            raisedAt: .distantPast,
            stillFrame: Data([0xFF, 0xD8])
        )
        let json = try JSONSerialization.jsonObject(with: WatchWire.encode(notice))
        let object = try XCTUnwrap(json as? [String: Any])
        XCTAssertEqual(object["still_frame"] as? String, Data([0xFF, 0xD8]).base64EncodedString())
    }

    /// An action added later must not silently become a tapped control. Every
    /// consequential control in this project is held.
    func testStartIncidentIsHeldAndExpectedIsNot() {
        XCTAssertTrue(WatchAction.startIncident.requiresHold)
        XCTAssertFalse(WatchAction.expected.requiresHold)
    }

    /// There is one incident type, so the wrist has nothing to choose. If a
    /// third action ever appears here it is a design change, not a detail.
    func testTheWristOffersExactlyTwoActions() {
        XCTAssertEqual(WatchAction.allCases.count, 2)
    }

    // MARK: The router

    private func notice(_ id: String = "ntc-1") -> WatchNotice {
        WatchNotice(noticeID: id, narration: "A person is in your living room.",
                    room: "Living room", raisedAt: Date())
    }

    private func outcome(
        _ disposition: WatchOutcome.Disposition,
        noticeID: String = "ntc-1",
        recordedAt: Date? = nil
    ) -> WatchOutcome {
        WatchOutcome(commandID: "cmd-1", noticeID: noticeID, action: .startIncident,
                     disposition: disposition, recordedAt: recordedAt)
    }

    func testAnEmptySnapshotIsIdle() {
        XCTAssertEqual(WatchRouter.screen(for: .unknown), .idle)
    }

    func testAnUnansweredNoticeShows() {
        let unanswered = notice()
        let snapshot = WatchSnapshot(notice: unanswered)
        XCTAssertEqual(WatchRouter.screen(for: snapshot), .notice(unanswered))
    }

    /// A resident who held Start Incident must never be dropped back to Idle as
    /// though they had not.
    func testAPendingAnswerOutranksTheNotice() {
        let snapshot = WatchSnapshot(notice: notice(), outcome: outcome(.pending))
        XCTAssertEqual(WatchRouter.screen(for: snapshot), .saved(outcome(.pending)))
    }

    /// A failure must be seen rather than expiring quietly, so it has no timeout.
    func testAFailedAnswerNeverExpires() {
        let snapshot = WatchSnapshot(notice: notice(), outcome: outcome(.failed))
        let wayLater = Date().addingTimeInterval(86_400)
        XCTAssertEqual(WatchRouter.screen(for: snapshot, now: wayLater), .saved(outcome(.failed)))
    }

    func testAFreshConfirmationShows() {
        let now = Date()
        let recorded = outcome(.recorded, recordedAt: now)
        let snapshot = WatchSnapshot(notice: notice(), outcome: recorded)
        XCTAssertEqual(WatchRouter.screen(for: snapshot, now: now.addingTimeInterval(2)),
                       .saved(recorded))
    }

    /// The confirmation expires on its own, and the answered notice must not
    /// come back around a second time behind it.
    func testAnExpiredConfirmationFallsToIdleRatherThanBackToTheNotice() {
        let now = Date()
        let recorded = outcome(.recorded, recordedAt: now)
        let snapshot = WatchSnapshot(notice: notice(), outcome: recorded)
        let after = now.addingTimeInterval(WatchRouter.confirmationLingers + 1)
        XCTAssertEqual(WatchRouter.screen(for: snapshot, now: after), .idle)
    }

    /// A different, newer notice after an expired confirmation is a new
    /// question and must be asked.
    func testANewNoticeShowsEvenAfterAnEarlierAnswerExpired() {
        let now = Date()
        let recorded = outcome(.recorded, noticeID: "ntc-old", recordedAt: now)
        let fresh = notice("ntc-new")
        let snapshot = WatchSnapshot(notice: fresh, outcome: recorded)
        let after = now.addingTimeInterval(WatchRouter.confirmationLingers + 1)
        XCTAssertEqual(WatchRouter.screen(for: snapshot, now: after), .notice(fresh))
    }
}
