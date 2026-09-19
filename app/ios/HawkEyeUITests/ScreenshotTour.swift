import XCTest

/// Drives the app through its three screens and writes a PNG per screen into
/// the runner's Documents directory, where the host can pull them out with
/// `xcrun simctl get_app_container`.
///
/// This exists because Xcode 27 ships no Simulator.app, so there is no window
/// to click. It doubles as a smoke test: if the app cannot get from Connect to
/// an open incident, this fails.
final class ScreenshotTour: XCTestCase {

    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
    }

    private func shoot(_ name: String) {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let url = dir.appendingPathComponent("\(name).png")
        try? png.write(to: url)
        print("SHOT \(name) -> \(url.path)")
    }

    func testTour() {
        // 1. Connect screen, hubs discovered.
        let home = app.buttons.containing(.staticText, identifier: "Home").firstMatch
        XCTAssertTrue(home.waitForExistence(timeout: 20), "no hub row appeared")
        sleep(2)
        shoot("01-connect")

        // 2. Connect, then the main screen.
        home.tap()
        sleep(5)
        shoot("02-home")

        // 3. Let the scripted entry land. Config.mockDetectionAfter is 14s,
        //    then a few more before respiration is acquired and the presence
        //    stops being unconfirmed. Poll for the roster headline rather than
        //    guessing at a sleep.
        let unexpected = app.staticTexts["Unexpected person"].firstMatch
        XCTAssertTrue(unexpected.waitForExistence(timeout: 45), "no unexpected person was identified")
        sleep(3)
        shoot("03-identified")

        // 3b. Give the intruder time to route into another room, so the pair of
        //     screenshots shows it actually moving rather than sitting still.
        sleep(16)
        shoot("04-approaching")

        // 4. Raise the incident by hand. Hawk Eye does not dial on its own.
        //    SwiftUI wraps the label in a button, so match on contained text.
        let burglary = app.buttons.containing(.staticText, identifier: "Burglary").firstMatch
        XCTAssertTrue(burglary.waitForExistence(timeout: 10), "no Burglary button")
        burglary.tap()
        sleep(2)
        shoot("05-confirm")

        let confirm = app.buttons["Raise Burglary"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "no confirm button")
        confirm.tap()

        // 5. The call screen, early.
        sleep(14)
        shoot("06-incident")

        // 6. Far enough in for the frame that matters to be said out loud.
        sleep(28)
        shoot("07-transcript")
        sleep(22)
        shoot("08-later")
    }
}
