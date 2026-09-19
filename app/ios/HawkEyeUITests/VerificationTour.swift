import XCTest

/// The refusal path, which is the one that matters. Gets to the incident
/// screen, then opens the verification feed and captures the discarded claim.
final class VerificationTour: XCTestCase {

    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
    }

    private func shoot(_ name: String) {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        try? png.write(to: dir.appendingPathComponent("\(name).png"))
        print("SHOT \(name)")
    }

    func testRefusal() {
        let home = app.buttons.containing(.staticText, identifier: "Home").firstMatch
        XCTAssertTrue(home.waitForExistence(timeout: 20))
        home.tap()

        let unexpected = app.staticTexts["Unexpected person"].firstMatch
        XCTAssertTrue(unexpected.waitForExistence(timeout: 45), "no unexpected person was identified")

        let burglary = app.buttons.containing(.staticText, identifier: "Burglary").firstMatch
        XCTAssertTrue(burglary.waitForExistence(timeout: 10))
        burglary.tap()
        let confirm = app.buttons["Raise Burglary"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        confirm.tap()

        // Let the verifications accumulate, including the discarded one.
        sleep(40)

        let tab = app.buttons["What was verified"].firstMatch
        XCTAssertTrue(tab.waitForExistence(timeout: 15), "no verification tab")
        tab.tap()
        sleep(2)
        shoot("10-verified-top")

        // Scroll the feed to reach the refusal detail.
        app.swipeUp()
        sleep(1)
        shoot("11-verified-mid")
        app.swipeUp()
        sleep(1)
        shoot("12-verified-refusal")
        app.swipeUp()
        sleep(1)
        shoot("13-verified-more")
    }
}
