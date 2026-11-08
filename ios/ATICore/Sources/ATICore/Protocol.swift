// Uzaktan kontrol protokolü v1 (shared/protocol/remote-v1.md) — telefon tarafı.
//
// İmza, gönderilen JSON metninin kendisi üzerine atılır: {"p": metin, "s": imza}.
// Telefon → motor: P-256 ECDSA/SHA-256, ham r‖s (64 bayt).
// Motor → telefon: Ed25519; telefon QR koddan aldığı motor anahtarıyla doğrular.

import Foundation

#if canImport(CryptoKit)
    import CryptoKit
#else
    import Crypto
#endif

public enum ProtocolError: Error, Equatable, Sendable {
    case invalidBase64
    case invalidPairingCode(String)
    case badSignature
    case malformed(String)
    case signerFailed(String)
}

// MARK: - Kodlama yardımcıları

public enum Codec {
    public static func base64(_ data: Data) -> String { data.base64EncodedString() }

    public static func unbase64(_ text: String) throws -> Data {
        guard let data = Data(base64Encoded: text) else { throw ProtocolError.invalidBase64 }
        return data
    }

    public static func unbase64URL(_ text: String) throws -> Data {
        var s = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while s.count % 4 != 0 { s += "=" }
        return try unbase64(s)
    }

    /// Kimlik: açık anahtarın SHA-256 özetinin ilk 16 baytı (onaltılık, küçük harf).
    public static func keyID(_ publicRaw: Data) -> String {
        SHA256.hash(data: publicRaw).prefix(16).map { String(format: "%02x", $0) }.joined()
    }

    /// Sıralı anahtarlı, boşluksuz JSON metni (imzalanacak içerik).
    public static func json(_ object: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(
            withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        guard let text = String(data: data, encoding: .utf8) else {
            throw ProtocolError.malformed("utf8")
        }
        return text
    }
}

// MARK: - İmzalı mesaj

public struct SignedMessage: Codable, Equatable, Sendable {
    public let p: String
    public let s: String
    public var proof: String?

    public init(p: String, s: String, proof: String? = nil) {
        self.p = p
        self.s = s
        self.proof = proof
    }

    public var dictionary: [String: Any] {
        var d: [String: Any] = ["p": p, "s": s]
        if let proof { d["proof"] = proof }
        return d
    }
}

/// Telefonun imza anahtarı. Secure Enclave anahtarı uygulama hedefinde, yazılım anahtarı burada.
public protocol DeviceSigner: Sendable {
    /// X9.63 sıkıştırılmamış açık anahtar (65 bayt).
    var publicKeyX963: Data { get }
    /// Ham r‖s (64 bayt) ECDSA/SHA-256 imzası. Korumalı anahtarda Face ID burada istenir.
    func signature(for data: Data) throws -> Data
}

public struct SoftwareSigner: DeviceSigner {
    private let key: P256.Signing.PrivateKey

    public init() { key = P256.Signing.PrivateKey() }
    public init(rawRepresentation: Data) throws {
        key = try P256.Signing.PrivateKey(rawRepresentation: rawRepresentation)
    }

    public var rawRepresentation: Data { key.rawRepresentation }
    public var publicKeyX963: Data { key.publicKey.x963Representation }

    public func signature(for data: Data) throws -> Data {
        try key.signature(for: data).rawRepresentation
    }
}

public enum P256Verifier {
    public static func isValid(publicX963: Data, signature: Data, data: Data) -> Bool {
        guard let key = try? P256.Signing.PublicKey(x963Representation: publicX963),
            let sig = try? P256.Signing.ECDSASignature(rawRepresentation: signature)
        else { return false }
        return key.isValidSignature(sig, for: data)
    }
}

/// Motor mesajlarının doğrulayıcısı (Ed25519). İmza geçmeden içerik ayrıştırılmaz.
public struct EngineVerifier: Sendable {
    public let engineKey: Data
    public let engineID: String

    public init(engineKey: Data) throws {
        guard engineKey.count == 32, (try? Curve25519.Signing.PublicKey(rawRepresentation: engineKey)) != nil
        else { throw ProtocolError.malformed("engine_key") }
        self.engineKey = engineKey
        self.engineID = Codec.keyID(engineKey)
    }

    /// İmzayı doğrular; geçerliyse içeriği (JSON nesnesi) döner.
    public func open(_ message: SignedMessage) throws -> [String: Any] {
        let data = Data(message.p.utf8)
        let signature = try Codec.unbase64(message.s)
        let key = try Curve25519.Signing.PublicKey(rawRepresentation: engineKey)
        guard key.isValidSignature(signature, for: data) else { throw ProtocolError.badSignature }
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProtocolError.malformed("payload")
        }
        guard object["engine_id"] as? String == engineID else { throw ProtocolError.malformed("engine_id") }
        return object
    }

    /// İmzayı doğrular ve içeriği verilen türe çözer.
    public func decode<T: Decodable>(_ type: T.Type, from message: SignedMessage) throws -> T {
        _ = try open(message)
        return try JSONDecoder().decode(T.self, from: Data(message.p.utf8))
    }
}

// MARK: - Eşleştirme kodu (QR)

public struct PairingCode: Codable, Equatable, Sendable {
    public let v: Int
    public let relay: String
    public let engine_id: String
    public let engine_key: String
    public let pair: String
    public let exp: Int64

    /// QR metnini ayrıştırır ve denetler: güvenli adres, kimlik-anahtar uyumu, süre.
    public static func parse(_ text: String, now: Date = Date()) throws -> PairingCode {
        guard let code = try? JSONDecoder().decode(PairingCode.self, from: Data(text.utf8)) else {
            throw ProtocolError.invalidPairingCode("Kod okunamadı")
        }
        guard code.v == 1 else { throw ProtocolError.invalidPairingCode("Desteklenmeyen sürüm") }
        let loopback = ["ws://127.0.0.1", "ws://localhost", "ws://[::1]"]
        guard code.relay.hasPrefix("wss://") || loopback.contains(where: { code.relay.hasPrefix($0) }) else {
            throw ProtocolError.invalidPairingCode("Aktarma adresi güvenli değil")
        }
        let key = try Codec.unbase64(code.engine_key)
        guard Codec.keyID(key) == code.engine_id else {
            throw ProtocolError.invalidPairingCode("Motor kimliği anahtarla eşleşmiyor")
        }
        guard (try? Codec.unbase64URL(code.pair))?.count == 32 else {
            throw ProtocolError.invalidPairingCode("Eşleştirme gizli değeri geçersiz")
        }
        guard Int64(now.timeIntervalSince1970 * 1000) <= code.exp else {
            throw ProtocolError.invalidPairingCode("Kodun süresi doldu; masaüstünde yeni kod oluşturun")
        }
        return code
    }

    public func verifier() throws -> EngineVerifier {
        try EngineVerifier(engineKey: try Codec.unbase64(engine_key))
    }
}

// MARK: - Komutlar

public enum KeyKind: String, Codable, Sendable { case signing, guarded }

/// İzin listesi (motordakiyle aynı). Yeni pozisyon açma, para çekme, sınır değiştirme YOKTUR.
public enum RemoteCommand: String, CaseIterable, Codable, Sendable {
    case engageKillSwitch = "engage_kill_switch"
    case pauseAutotrade = "pause_autotrade"
    case requestSnapshot = "request_snapshot"
    case resumeAutotrade = "resume_autotrade"
    case releaseKillSwitch = "release_kill_switch"
    case closePosition = "close_position"
    case closeAll = "close_all"

    /// Face ID gerektiren komutlar korumalı anahtarla imzalanır.
    public var requiredKey: KeyKind {
        switch self {
        case .engageKillSwitch, .pauseAutotrade, .requestSnapshot: return .signing
        case .resumeAutotrade, .releaseKillSwitch, .closePosition, .closeAll: return .guarded
        }
    }
}

/// Artan sıra numarası: max(son + 1, şimdi_ms). Uygulama yeniden kurulsa da geriye gitmez.
public struct SequenceCounter: Sendable {
    public private(set) var last: Int64

    public init(last: Int64 = 0) { self.last = last }

    public mutating func next(now: Date = Date()) -> Int64 {
        last = max(last + 1, Int64(now.timeIntervalSince1970 * 1000))
        return last
    }
}

public enum MessageFactory {
    public static func nowMs(_ date: Date = Date()) -> Int64 { Int64(date.timeIntervalSince1970 * 1000) }

    public static func pairRequest(
        code: PairingCode, signing: DeviceSigner, guardedKey: Data, name: String,
        protection: String, now: Date = Date(), nonce: String = UUID().uuidString
    ) throws -> SignedMessage {
        let deviceID = Codec.keyID(signing.publicKeyX963)
        let payload: [String: Any] = [
            "v": 1, "type": "pair_request", "engine_id": code.engine_id, "device_id": deviceID,
            "name": String(name.prefix(60)), "signing_key": Codec.base64(signing.publicKeyX963),
            "guarded_key": Codec.base64(guardedKey), "protection": protection,
            "ts_ms": nowMs(now), "nonce": nonce,
        ]
        let text = try Codec.json(payload)
        let data = Data(text.utf8)
        let secret = SymmetricKey(data: try Codec.unbase64URL(code.pair))
        let proof = Data(HMAC<SHA256>.authenticationCode(for: data, using: secret))
        return SignedMessage(p: text, s: Codec.base64(try signing.signature(for: data)), proof: Codec.base64(proof))
    }

    public static func command(
        _ command: RemoteCommand, args: [String: String] = [:], engineID: String,
        deviceID: String, signer: DeviceSigner, key: KeyKind, seq: Int64, now: Date = Date()
    ) throws -> SignedMessage {
        let payload: [String: Any] = [
            "v": 1, "type": "command", "engine_id": engineID, "device_id": deviceID,
            "key": key.rawValue, "seq": seq, "ts_ms": nowMs(now), "command": command.rawValue,
            "args": args,
        ]
        let text = try Codec.json(payload)
        return SignedMessage(p: text, s: Codec.base64(try signer.signature(for: Data(text.utf8))))
    }

    public static func helloText(deviceID: String, engineID: String, ts: Int64) -> String {
        "ati-relay-hello|device|\(deviceID)|\(engineID)|\(ts)"
    }

    /// Aktarma servisine kimlik kanıtı (imza anahtarıyla).
    public static func hello(engineID: String, signer: DeviceSigner, now: Date = Date()) throws -> String {
        let deviceID = Codec.keyID(signer.publicKeyX963)
        let ts = nowMs(now)
        let sig = try signer.signature(for: Data(helloText(deviceID: deviceID, engineID: engineID, ts: ts).utf8))
        return try Codec.json([
            "type": "hello", "role": "device", "device_id": deviceID, "engine_id": engineID,
            "key": Codec.base64(signer.publicKeyX963), "ts_ms": ts, "sig": Codec.base64(sig),
        ])
    }

    public static func toEngine(_ message: SignedMessage) throws -> String {
        try Codec.json(["type": "to_engine", "msg": message.dictionary])
    }
}
