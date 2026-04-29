//
//  retailmanagementUITests.swift
//  retailmanagementUITests
//

import XCTest

final class retailmanagementUITests: XCTestCase {
    private let launchArgument = "--uitest-manager-inventory"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testManagerInventoryHappyPathHarnessRendersCoreManagerWorkflow() throws {
        let app = XCUIApplication()
        app.launchArguments.append(launchArgument)
        app.launch()

        XCTAssertTrue(app.otherElements["managerInventory.root"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["managerInventory.runBrain"].exists)
        XCTAssertTrue(app.staticTexts["managerInventory.watchlistTitle"].exists)
        XCTAssertTrue(app.buttons["managerInventory.insight.PRE-001"].exists)
        XCTAssertTrue(app.staticTexts["Supplier Pendant"].exists)

        app.buttons["managerInventory.insight.CUS-900"].tap()

        XCTAssertTrue(app.staticTexts["managerInventory.detailTitle"].waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["Custom Bridal Halo"].exists)
        XCTAssertTrue(app.staticTexts["Demand spiked after a bridal expo appointment."].exists)
        XCTAssertTrue(app.staticTexts["managerInventory.recommendationsTitle"].exists)

        scrollToElement(app.staticTexts["managerInventory.workflowStudioTitle"], in: app)
        XCTAssertTrue(app.staticTexts["managerInventory.workflowStudioTitle"].exists)
        XCTAssertTrue(app.staticTexts["Purchase Order Builder"].exists)
        XCTAssertTrue(app.staticTexts["Work Orders & Transfers"].exists)
    }

    @MainActor
    func testLaunchPerformance() throws {
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            let app = XCUIApplication()
            app.launchArguments.append(launchArgument)
            app.launch()
        }
    }

    @MainActor
    private func scrollToElement(_ element: XCUIElement, in app: XCUIApplication, maxSwipes: Int = 6) {
        var remainingSwipes = maxSwipes
        while !element.exists && remainingSwipes > 0 {
            app.swipeUp()
            remainingSwipes -= 1
        }
    }
}
