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

        let down = app.staticTexts["Not responding"].firstMatch
        XCTAssertTrue(down.waitForExistence(timeout: 45), "fall never detected")

        let faint = app.buttons.containing(.staticText, identifier: "Faint").firstMatch
        XCTAssertTrue(faint.waitForExistence(timeout: 10))
        faint.tap()
        let confirm = app.buttons["Raise Faint"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        confirm.tap()

        // Let the verifications accumulate, including the discarded one.
        sleep(40)

        print("TREE-START")
        print(app.debugDescription)
        print("TREE-END")

        // The tab may be a button, a segmented control, or a bare tappable
        // text depending on how it was built. Try each in turn.
        var tapped = false
        let asButton = app.buttons.containing(.staticText, identifier: "What was verified").firstMatch
        if asButton.exists { asButton.tap(); tapped = true }
        if !tapped {
            let asText = app.staticTexts["What was verified"].firstMatch
            if asText.exists { asText.tap(); tapped = true }
        }
        if !tapped {
            let byLabel = app.descendants(matching: .any)
                .matching(NSPredicate(format: "label CONTAINS[c] 'verified'")).firstMatch
            if byLabel.exists { byLabel.tap(); tapped = true }
        }
        XCTAssertTrue(tapped, "could not find the verification tab")
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
