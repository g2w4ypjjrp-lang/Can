import XCTest

/// Arayüz testleri: uygulama, gerçek imza kurallarını uygulayan bellek içi motor benzetimiyle
/// (-UITestMockEngine) çalışır. Eşleştirme, acil durdurma, Face ID gerektiren kapatma ve aktarma
/// servisinden gelen sahte mesajın yok sayılması.
final class ATIUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    private func launchPaired() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-UITestMockEngine"]
        app.launch()
        let useCode = app.buttons["use-test-code"]
        XCTAssertTrue(useCode.waitForExistence(timeout: 10))
        useCode.tap()
        app.buttons["pair-button"].tap()
        XCTAssertTrue(app.staticTexts["engine-state"].waitForExistence(timeout: 15), "eşleştirme sonrası özet gelmedi")
        return app
    }

    func testPairingShowsEngineSummary() {
        let app = launchPaired()
        XCTAssertEqual(app.staticTexts["engine-state"].label, "Çalışıyor")
        XCTAssertTrue(app.staticTexts["Test ağı"].exists)
    }

    func testKillSwitchIsOneTapWithConfirmation() {
        let app = launchPaired()
        app.buttons["kill-switch"].tap()
        let alert = app.alerts["Acil durdurma"]
        XCTAssertTrue(alert.waitForExistence(timeout: 5))
        alert.buttons["Durdur"].tap()
        let state = app.staticTexts["engine-state"]
        XCTAssertTrue(state.waitForLabel("Acil durdurma", timeout: 10))
        XCTAssertTrue(app.staticTexts["banner"].waitForLabel("Acil durdurma devrede", timeout: 10))
        XCTAssertTrue(app.buttons["kill-release"].exists)
    }

    func testClosePositionNeedsConfirmation() {
        let app = launchPaired()
        app.tabBars.buttons["Pozisyonlar"].tap()
        let close = app.buttons["close-BTCUSDT"]
        XCTAssertTrue(close.waitForExistence(timeout: 10))
        close.tap()
        let alert = app.alerts.firstMatch
        XCTAssertTrue(alert.waitForExistence(timeout: 5))
        alert.buttons["Kapat (Face ID)"].tap()
        XCTAssertTrue(close.waitForNonExistence(timeout: 10), "pozisyon kapanmadı")
        XCTAssertTrue(app.buttons["close-ETHUSDT"].exists)
    }

    func testForgedMessageFromRelayIsIgnored() {
        let app = launchPaired()
        app.tabBars.buttons["Ayarlar"].tap()
        let counter = app.staticTexts["rejected-count"]
        XCTAssertTrue(counter.waitForExistence(timeout: 5))
        XCTAssertEqual(counter.label, "0")
        app.buttons["inject-forgery"].tap()
        XCTAssertTrue(counter.waitForLabel("1", timeout: 10))
        app.tabBars.buttons["Özet"].tap()
        XCTAssertEqual(app.staticTexts["engine-state"].label, "Çalışıyor")  // sahte "acil durdurma" gösterilmedi
    }

    func testBotControlAndUnpair() {
        let app = launchPaired()
        let state = app.staticTexts["bot-state"]
        XCTAssertTrue(state.waitForExistence(timeout: 5))
        XCTAssertEqual(state.label, "Kapalı")
        app.buttons["bot-resume"].tap()
        app.alerts.firstMatch.buttons["Başlat (Face ID)"].tap()
        XCTAssertTrue(state.waitForLabel("Açık", timeout: 10))
        app.tabBars.buttons["Ayarlar"].tap()
        app.buttons["unpair"].tap()
        app.alerts.firstMatch.buttons["Kaldır"].tap()
        XCTAssertTrue(app.buttons["pair-button"].waitForExistence(timeout: 10))
    }
}

extension XCUIElement {
    func waitForLabel(_ label: String, timeout: TimeInterval) -> Bool {
        let predicate = NSPredicate(format: "label == %@", label)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: self)
        return XCTWaiter().wait(for: [expectation], timeout: timeout) == .completed
    }
}
