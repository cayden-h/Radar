import XCTest

/// Approving and remembering, from the notice banner.
///
/// Covers the path `NoticeTour` does not: naming the unexpected presence
/// turns it into a household member, and doing so also clears the banner,
/// because the resident has just answered the question the banner was asking.
final class HouseholdTour: XCTestCase {

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

    func testRememberingAVisitorClearsTheBannerAndJoinsTheRoster() {
        enterHome()

        let rememberButton = app.buttons["Remember this visitor"].firstMatch
        XCTAssertTrue(
            rememberButton.waitForExistence(timeout: 60),
            "the notice banner (and its remember action) never appeared"
        )
        rememberButton.tap()

        let nameField = app.textFields["Name"].firstMatch
        XCTAssertTrue(nameField.waitForExistence(timeout: 10), "the remember sheet never showed a Name field")
        nameField.tap()
        nameField.typeText("Grandma")

        let saveButton = app.buttons["Save"].firstMatch
        XCTAssertTrue(saveButton.exists, "no Save button in the toolbar")
        XCTAssertTrue(saveButton.isEnabled, "Save should be enabled once a name is typed")
        saveButton.tap()

        // Remembering also approves the presence and dismisses the notice, so
        // the banner's dismiss control should be gone.
        XCTAssertFalse(
            waitForElementToDisappear(app.buttons["Dismiss"].firstMatch, timeout: 10),
            "the notice banner is still up after remembering the visitor"
        )

        let householdButton = app.buttons["Household"].firstMatch
        XCTAssertTrue(householdButton.waitForExistence(timeout: 10), "no Household button in the header")
        householdButton.tap()

        let grandma = app.staticTexts["Grandma"].firstMatch
        XCTAssertTrue(grandma.waitForExistence(timeout: 10), "Grandma never appeared in the household list")
    }

    /// Waits for an element to stop existing, returning whether it is still
    /// present when the timeout elapses. `XCTNSPredicateExpectation` reads more
    /// clearly here than polling by hand.
    private func waitForElementToDisappear(_ element: XCUIElement, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        let result = XCTWaiter().wait(for: [expectation], timeout: timeout)
        return result != .completed
    }
}
