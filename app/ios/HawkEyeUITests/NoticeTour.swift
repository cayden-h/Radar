import XCTest

/// The notice banner, in the running app.
///
/// The banner is the in-app half of a notice; the other half is an SMS. This
/// covers the half that can be driven here.
///
/// The dismissal case is the reason this file exists. The first implementation
/// gated re-raising on `notices.isEmpty`, and `dismissNotice` empties that
/// array, so the banner re-appeared within one sensor tick of being swiped
/// away: an undismissable notice. That was caught by reading the code, and this
/// proves the fix in the built app rather than in an argument about it.
final class NoticeTour: XCTestCase {

    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
    }

    /// Gets past the Connect screen into the main app.
    private func enterHome() {
        let home = app.buttons.containing(.staticText, identifier: "Home").firstMatch
        XCTAssertTrue(home.waitForExistence(timeout: 20), "no hub row appeared")
        home.tap()
    }

    func testTheBannerAppearsAndStaysDismissed() {
        enterHome()

        // The notice lands `Config.mockNoticeHoldSeconds` after the intruder is
        // identified, which is itself after `Config.mockDetectionAfter`. Poll
        // rather than guessing at a sleep.
        let banner = app.staticTexts["Unexpected person"].firstMatch
        XCTAssertTrue(
            banner.waitForExistence(timeout: 60),
            "the notice banner never appeared"
        )

        // Two elements now carry this text: the banner and the roster row. That
        // is expected and is the point of the pair, so assert on the count
        // rather than on a single match, and dismiss via the banner's button.
        let dismiss = app.buttons["Dismiss"].firstMatch
        XCTAssertTrue(dismiss.waitForExistence(timeout: 10), "no dismiss control on the banner")

        let before = app.staticTexts.matching(identifier: "Unexpected person").count
        XCTAssertGreaterThanOrEqual(before, 1, "expected the banner and the roster row")

        dismiss.tap()

        // The sensor loop ticks about every 250ms. If dismissal is gated on the
        // array being empty rather than on a raised flag, the banner is back
        // within one tick. Five seconds is twenty ticks, which is emphatic.
        sleep(5)

        XCTAssertFalse(
            app.buttons["Dismiss"].firstMatch.exists,
            "the banner came back after being dismissed: the raise guard is wrong"
        )

        // The roster row must survive. The banner is a discrete event the
        // resident acknowledged; the roster is the live readout of who is in
        // the building, and that person is still in the building.
        let after = app.staticTexts.matching(identifier: "Unexpected person").count
        XCTAssertGreaterThanOrEqual(
            after, 1,
            "dismissing the banner also cleared the roster row, which tracks a person who is still there"
        )
    }
}
