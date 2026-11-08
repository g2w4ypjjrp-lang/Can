// Uzaktan kontrol oturum denetleyicisi: eşleştirme, aktarma bağlantısı, komut gönderimi ve
// gelen (imzası doğrulanmış) mesajların durumu. Arayüzden bağımsızdır; SwiftUI bu nesneyi izler.

import Foundation
import Observation

/// Aktarma servisine çerçeve (metin) taşıyan bağlantı. Uygulamada WebSocket, testlerde benzetim.
public protocol FrameTransport: AnyObject, Sendable {
    func connect(to url: URL) async throws
    func send(_ text: String) async throws
    func receive() async throws -> String
    func close() async
}

/// Telefon anahtarları. Korumalı anahtarla imza atmadan önce biyometrik doğrulama yapılır.
public protocol KeyProvider: Sendable {
    var protection: String { get }
    func signingKey() throws -> DeviceSigner
    func guardedPublicKey() throws -> Data
    func guardedSigner(reason: String) async throws -> DeviceSigner
    func reset() throws
}

public struct PairedEngine: Codable, Equatable, Sendable {
    public var relay: String
    public var engineID: String
    public var engineKey: String
    public var engineName: String
    public var deviceName: String
    public var pairedAtMs: Int64
}

/// Kalıcı depolama (uygulamada UserDefaults/Anahtar Zinciri).
@MainActor
public protocol ControllerStorage: AnyObject {
    var pairedEngine: PairedEngine? { get set }
    var lastSeq: Int64 { get set }
}

@MainActor
public final class MemoryStorage: ControllerStorage {
    public var pairedEngine: PairedEngine?
    public var lastSeq: Int64 = 0
    public init() {}
}

public enum ConnectionStatus: Equatable, Sendable {
    case idle
    case connecting
    case connected
    case failed(String)
}

public enum ControllerError: Error, Equatable, LocalizedError {
    case notPaired
    case timeout(String)
    case pairingRejected(String)

    public var errorDescription: String? {
        switch self {
        case .notPaired: return "Telefon bir bilgisayarla eşleştirilmemiş"
        case .timeout(let what): return "Zaman aşımı: \(what)"
        case .pairingRejected(let reason): return "Eşleştirme reddedildi: \(reason)"
        }
    }
}

@MainActor
@Observable
public final class RemoteController {
    public private(set) var paired: PairedEngine?
    public private(set) var session: SessionState?
    public private(set) var status: ConnectionStatus = .idle
    public private(set) var banner: String?
    public private(set) var rejectedFrames = 0
    public private(set) var sending = false

    private let makeTransport: @Sendable () -> FrameTransport
    private let keys: KeyProvider
    private let storage: ControllerStorage
    private var transport: FrameTransport?
    private var receiver: Task<Void, Never>?
    private var verifier: EngineVerifier?
    private var counter: SequenceCounter
    private var stopped = false
    public var reconnectDelay: Duration = .seconds(1)
    public var responseTimeout: Double = 20

    public init(transport: @escaping @Sendable () -> FrameTransport, keys: KeyProvider, storage: ControllerStorage) {
        self.makeTransport = transport
        self.keys = keys
        self.storage = storage
        self.paired = storage.pairedEngine
        self.counter = SequenceCounter(last: storage.lastSeq)
        if let paired = storage.pairedEngine, let signer = try? keys.signingKey() {
            self.session = SessionState(deviceID: Codec.keyID(signer.publicKeyX963))
            self.verifier = try? EngineVerifier(engineKey: Codec.unbase64(paired.engineKey))
        }
    }

    public var deviceID: String? { (try? keys.signingKey()).map { Codec.keyID($0.publicKeyX963) } }

    // MARK: Bağlantı

    /// Eşleştirilmiş bilgisayara bağlanır (uygulama açılışında).
    public func start() async {
        guard let paired, status != .connected, status != .connecting else { return }
        stopped = false
        try? await open(relay: paired.relay, engineID: paired.engineID)
    }

    public func stop() async {
        stopped = true
        receiver?.cancel()
        receiver = nil
        await transport?.close()
        transport = nil
        status = .idle
    }

    private func open(relay: String, engineID: String) async throws {
        receiver?.cancel()
        await transport?.close()
        status = .connecting
        let link = makeTransport()
        transport = link
        do {
            guard let url = URL(string: relay + "/v1/relay/device") else {
                throw ProtocolError.invalidPairingCode("adres")
            }
            try await link.connect(to: url)
            try await link.send(try MessageFactory.hello(engineID: engineID, signer: try keys.signingKey()))
        } catch {
            status = .failed(error.localizedDescription)
            scheduleReconnect()
            throw error
        }
        receiver = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    let frame = try await link.receive()
                    self?.handle(frame)
                } catch {
                    self?.connectionLost(error)
                    return
                }
            }
        }
        try await waitUntil("aktarma servisi", seconds: responseTimeout) { self.status == .connected }
    }

    private func connectionLost(_ error: Error) {
        guard !stopped else { return }
        status = .failed("Bağlantı koptu")
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        guard !stopped, let paired else { return }
        let delay = reconnectDelay
        Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard let self, !self.stopped, self.status != .connected, self.status != .connecting else { return }
            try? await self.open(relay: paired.relay, engineID: paired.engineID)
        }
    }

    private func waitUntil(_ what: String, seconds: Double, _ condition: @escaping @MainActor () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(seconds)
        while !condition() {
            if Date() > deadline { throw ControllerError.timeout(what) }
            try await Task.sleep(for: .milliseconds(50))
        }
    }

    // MARK: Gelen çerçeveler

    func handle(_ frame: String) {
        if let relayStatus = RelayStatus.parse(frame) {
            if case .welcome = relayStatus { status = .connected }
            session?.apply(relayStatus)
            return
        }
        guard let verifier else { return }
        do {
            guard let message = try verifier.message(from: frame) else { return }
            session?.apply(message)
            if case .result(let result) = message, result.device_id == session?.deviceID {
                banner = result.ok ? result.message : ReasonText.text(result.reason)
            }
        } catch {
            rejectedFrames += 1  // imzası doğrulanamayan mesaj: yok sayılır
        }
    }

    // MARK: Eşleştirme

    /// QR kodla eşleştirir. Başarılıysa bağlantı açık kalır ve özet gelmeye başlar.
    @discardableResult
    public func pair(code text: String, deviceName: String) async throws -> PairResult {
        let code = try PairingCode.parse(text)
        let signer = try keys.signingKey()
        let deviceID = Codec.keyID(signer.publicKeyX963)
        verifier = try code.verifier()
        session = SessionState(deviceID: deviceID)
        stopped = false
        try await open(relay: code.relay, engineID: code.engine_id)
        let request = try MessageFactory.pairRequest(
            code: code, signing: signer, guardedKey: try keys.guardedPublicKey(), name: deviceName,
            protection: keys.protection)
        try await transport?.send(try MessageFactory.toEngine(request))
        try await waitUntil("eşleştirme yanıtı", seconds: responseTimeout) { self.session?.pairResult != nil }
        guard let result = session?.pairResult else { throw ControllerError.timeout("eşleştirme") }
        guard result.ok else {
            await stop()
            throw ControllerError.pairingRejected(result.reason)
        }
        let engine = PairedEngine(
            relay: code.relay, engineID: code.engine_id, engineKey: code.engine_key,
            engineName: result.name ?? "Bilgisayar", deviceName: deviceName,
            pairedAtMs: MessageFactory.nowMs())
        storage.pairedEngine = engine
        paired = engine
        return result
    }

    public func unpair() async {
        await stop()
        storage.pairedEngine = nil
        paired = nil
        session = nil
        verifier = nil
        try? keys.reset()
    }

    // MARK: Komutlar

    /// İmzalı komut gönderir. Face ID gerektirenlerde korumalı anahtar biyometrik onay ister.
    public func send(_ command: RemoteCommand, args: [String: String] = [:]) async {
        guard let paired, let transport, let deviceID else {
            banner = ControllerError.notPaired.localizedDescription
            return
        }
        sending = true
        defer { sending = false }
        do {
            let signer: DeviceSigner
            if command.requiredKey == .guarded {
                signer = try await keys.guardedSigner(reason: Self.reason(for: command))
            } else {
                signer = try keys.signingKey()
            }
            let seq = counter.next()
            storage.lastSeq = seq
            let message = try MessageFactory.command(
                command, args: args, engineID: paired.engineID, deviceID: deviceID, signer: signer,
                key: command.requiredKey, seq: seq)
            try await transport.send(try MessageFactory.toEngine(message))
            banner = "Gönderildi, motorun onayı bekleniyor…"
        } catch {
            banner = "Gönderilemedi: \(error.localizedDescription)"
        }
    }

    public static func reason(for command: RemoteCommand) -> String {
        switch command {
        case .resumeAutotrade: return "Otomatik işlemi başlatmayı onaylayın"
        case .releaseKillSwitch: return "Acil durdurmayı kaldırmayı onaylayın"
        case .closePosition: return "Pozisyonu kapatmayı onaylayın"
        case .closeAll: return "Tüm pozisyonları kapatmayı onaylayın"
        default: return "İşlemi onaylayın"
        }
    }

    public func clearBanner() { banner = nil }
}

/// Yazılım anahtarları (Secure Enclave olmayan ortamlar: simülatör, testler).
public final class SoftwareKeyProvider: KeyProvider, @unchecked Sendable {
    private let lock = NSLock()
    private var signing: SoftwareSigner
    private var guarded: SoftwareSigner
    private let authorize: @Sendable (String) async throws -> Void

    public init(authorize: @escaping @Sendable (String) async throws -> Void = { _ in }) {
        signing = SoftwareSigner()
        guarded = SoftwareSigner()
        self.authorize = authorize
    }

    public var protection: String { "software" }
    public func signingKey() throws -> DeviceSigner { lock.withLock { signing } }
    public func guardedPublicKey() throws -> Data { lock.withLock { guarded.publicKeyX963 } }

    public func guardedSigner(reason: String) async throws -> DeviceSigner {
        try await authorize(reason)
        return lock.withLock { guarded }
    }

    public func reset() throws {
        lock.withLock {
            signing = SoftwareSigner()
            guarded = SoftwareSigner()
        }
    }
}
