import XCTest

/// The notice card, in the running app.
///
/// The card is the in-app half of a notice; the other half is an SMS. This
/// covers the half that can be driven here.
///
/// `NoticeCard` replaced the old inline `NoticeBanner` and is now presented
/// as a modal sheet over the camera page (see `HomeView.latestNoticeBinding`),
/// so this file asserts on the sheet's own header rather than on the string
/// "Unexpected person" — that text now belongs solely to the roster row in
/// `InteriorView`, which must keep showing it once the card is dismissed.
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

    func testTheCardAppearsAndStaysDismissed() {
        enterHome()

        // The roster already carries "Unexpected person" once the presence is
        // identified as unaccounted-for, ahead of the notice itself firing.
        let rosterHeadline = app.staticTexts["Unexpected person"].firstMatch
        XCTAssertTrue(rosterHeadline.waitForExistence(timeout: 45), "no unexpected person was identified on the roster")

        // The notice lands `Config.mockNoticeHoldSeconds` after that, which
        // presents `NoticeCard` as a sheet. Poll rather than guessing at a
        // sleep.
        let cardHeader = app.staticTexts["Unexpected motion detected"].firstMatch
        XCTAssertTrue(
            cardHeader.waitForExistence(timeout: 30),
            "the notice card never appeared"
        )

        let dismiss = app.buttons["Dismiss"].firstMatch
        XCTAssertTrue(dismiss.waitForExistence(timeout: 10), "no dismiss control on the notice card")

        dismiss.tap()

        // The sensor loop ticks about every 250ms. If dismissal is gated on the
        // array being empty rather than on a raised flag, the card is back
        // within one tick. Five seconds is twenty ticks, which is emphatic.
        sleep(5)

        XCTAssertFalse(
            app.staticTexts["Unexpected motion detected"].firstMatch.exists,
            "the notice card came back after being dismissed: the raise guard is wrong"
        )

        // The roster row must survive. The card is a discrete event the
        // resident acknowledged; the roster is the live readout of who is in
        // the building, and that person is still in the building.
        XCTAssertTrue(
            app.staticTexts["Unexpected person"].firstMatch.exists,
            "dismissing the notice card also cleared the roster row, which tracks a person who is still there"
        )
    }
}
