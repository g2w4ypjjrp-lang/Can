import Foundation
import XCTest

@testable import ATICore

/// Gönderilen çerçeveleri kaydeden sarmalayıcı (tekrar oynatma testi için).
final class SpyTransport: FrameTransport, @unchecked Sendable {
    let inner: MockEngine
    private let lock = NSLock()
    private var _sent: [String] = []
    var sent: [String] { lock.withLock { _sent } }

    init(_ inner: MockEngine) { self.inner = inner }
    func connect(to url: URL) async throws { try await inner.connect(to: url) }
    func send(_ text: String) async throws {
        lock.withLock { _sent.append(text) }
        try await inner.send(text)
    }
    func receive() async throws -> String { try await inner.receive() }
    func close() async { await inner.close() }
}

/// Biyometrik onay isteklerinin kaydı (Face ID benzetimi).
final class AuthRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var _reasons: [String] = []
    var reasons: [String] { lock.withLock { _reasons } }
    func record(_ reason: String) { lock.withLock { _reasons.append(reason) } }
}

@MainActor
final class ControllerTests: XCTestCase {
    var engine: MockEngine!
    var spy: SpyTransport!
    let auth = AuthRecorder()
    var authorized: [String] { auth.reasons }

    func makeController(deny: Bool = false) -> RemoteController {
        engine = MockEngine()
        spy = SpyTransport(engine)
        let transport = spy!
        let recorder = auth
        let keys = SoftwareKeyProvider { reason in
            recorder.record(reason)
            if deny { throw ProtocolError.signerFailed("Face ID iptal edildi") }
        }
        let controller = RemoteController(transport: { transport }, keys: keys, storage: MemoryStorage())
        controller.responseTimeout = 2
        return controller
    }

    func eventually(_ what: String, _ condition: @escaping @MainActor () -> Bool) async throws {
        for _ in 0..<200 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("koşul sağlanmadı: \(what)")
    }

    func testPairingAndSignedCommands() async throws {
        let controller = makeController()
        let result = try await controller.pair(code: engine.pairingCode, deviceName: "Test iPhone")
        XCTAssertTrue(result.ok)
        XCTAssertEqual(controller.paired?.engineID, engine.engineID)
        XCTAssertEqual(controller.status, .connected)
        try await eventually("özet") { controller.session?.snapshot?.data.positions?.count == 2 }

        await controller.send(.engageKillSwitch)
        try await eventually("acil durdurma") { controller.session?.snapshot?.data.engine.kill_switch == true }
        XCTAssertEqual(controller.banner, "Acil durdurma devrede")
        let killSwitch = await engine.killSwitch
        XCTAssertTrue(killSwitch)
        XCTAssertTrue(authorized.isEmpty)  // acil durdurma Face ID istemez

        await controller.send(.closePosition, args: ["market": "usdm_futures", "symbol": "BTCUSDT"])
        try await eventually("kapatma") { controller.session?.snapshot?.data.positions?.count == 1 }
        XCTAssertEqual(controller.banner, "BTCUSDT kapatıldı")
        XCTAssertEqual(authorized, ["Pozisyonu kapatmayı onaylayın"])
    }

    func testCancelledFaceIDSendsNothing() async throws {
        let controller = makeController(deny: true)
        try await controller.pair(code: engine.pairingCode, deviceName: "Test iPhone")
        let before = spy.sent.count
        await controller.send(.closeAll)
        XCTAssertEqual(spy.sent.count, before)
        XCTAssertTrue(controller.banner?.hasPrefix("Gönderilemedi") ?? false)
        let positions = await engine.positions
        XCTAssertEqual(positions.count, 2)
    }

    func testForgedMessageFromRelayIsIgnored() async throws {
        let controller = makeController()
        try await controller.pair(code: engine.pairingCode, deviceName: "Test iPhone")
        try await eventually("özet") { controller.session?.snapshot != nil }
        await engine.injectForgedSnapshot()
        try await eventually("sahte mesaj sayıldı") { controller.rejectedFrames == 1 }
        XCTAssertEqual(controller.session?.snapshot?.data.engine.kill_switch, false)
    }

    func testReplayedCommandIsRejectedByEngine() async throws {
        let controller = makeController()
        try await controller.pair(code: engine.pairingCode, deviceName: "Test iPhone")
        await controller.send(.pauseAutotrade)
        try await eventually("ilk komut") { controller.banner == "Otomatik işlem durduruldu" }
        let command = try XCTUnwrap(spy.sent.last)
        try await engine.deliver(command)  // aktarma servisi aynı mesajı tekrar gönderiyor
        try await eventually("tekrar reddi") { controller.banner == ReasonText.text("replay") }
        let rejections = await engine.rejections
        XCTAssertEqual(rejections, ["replay"])
    }

    func testPairingWithWrongCodeFails() async throws {
        let controller = makeController()
        let other = MockEngine()
        do {
            try await controller.pair(code: other.pairingCode, deviceName: "Test iPhone")
            XCTFail("eşleşmemeliydi")
        } catch {
            XCTAssertEqual(error as? ControllerError, .timeout("eşleştirme yanıtı"))
        }
        XCTAssertNil(controller.paired)
        XCTAssertEqual(controller.session?.engineOnline, false)  // o kanalda motor yok
        let rejections = await engine.rejections
        XCTAssertTrue(rejections.isEmpty)  // bu motora hiç ulaşmadı
    }

    func testCommandWithoutPairingIsRefusedLocally() async {
        let controller = makeController()
        await controller.send(.engageKillSwitch)
        XCTAssertEqual(controller.banner, ControllerError.notPaired.localizedDescription)
        XCTAssertTrue(spy.sent.isEmpty)
    }

    func testUnpairForgetsEverything() async throws {
        let controller = makeController()
        try await controller.pair(code: engine.pairingCode, deviceName: "Test iPhone")
        let oldDevice = controller.deviceID
        await controller.unpair()
        XCTAssertNil(controller.paired)
        XCTAssertNil(controller.session)
        XCTAssertNotEqual(controller.deviceID, oldDevice)  // anahtarlar yenilendi
        XCTAssertEqual(controller.status, .idle)
    }
}
