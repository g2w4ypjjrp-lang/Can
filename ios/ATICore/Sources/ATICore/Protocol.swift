// Uzaktan kontrol protokolü v1 (shared/protocol/remote-v1.md) — telefon tarafı.
//
// İmza, gönderilen JSON metninin kendisi üzerine atılır: {"p": metin, "s": imza}.
// Telefon → motor: P-256 ECDSA/SHA-256, ham r‖s (64 bayt).
// Motor → telefon: Ed25519; telefon QR koddan aldığı motor anahtarıyla doğrular.
// Uçtan uca şifreleme (Aşama 18): imzalı mesaj alıcının P-256 anahtarına şifrelenir
// (geçici anahtar → ECDH → HKDF-SHA256 → AES-256-GCM). Aktarma servisi içeriği göremez.

import Foundation

#if canImport(CryptoKit)
    @preconcurrency import CryptoKit
#else
    @preconcurrency import Crypto
#endif

public enum ProtocolError: Error, Equatable, Sendable {
    case invalidBase64
    case invalidPairingCode(String)
    case badSignature
    case malformed(String)
    case signerFailed(String)
    case undecryptable
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

/// Yazılım anahtarı (simülatör ve testler). Anahtar ham baytlarıyla tutulur (Sendable).
public struct SoftwareSigner: DeviceSigner {
    public let rawRepresentation: Data
    public let publicKeyX963: Data

    public init() {
        let key = P256.Signing.PrivateKey()
        rawRepresentation = key.rawRepresentation
        publicKeyX963 = key.publicKey.x963Representation
    }

    public init(rawRepresentation: Data) throws {
        let key = try P256.Signing.PrivateKey(rawRepresentation: rawRepresentation)
        self.rawRepresentation = key.rawRepresentation
        publicKeyX963 = key.publicKey.x963Representation
    }

    public func signature(for data: Data) throws -> Data {
        try P256.Signing.PrivateKey(rawRepresentation: rawRepresentation).signature(for: data).rawRepresentation
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

// MARK: - Uçtan uca şifreleme (Aşama 18)

/// Telefonun P-256 anahtar anlaşması anahtarı. Uygulamada Secure Enclave'dedir (CryptoKit Secure
/// Enclave'de P-256 anlaşmasını destekler); simülatör ve testlerde yazılım anahtarı.
public protocol DeviceAgreement: Sendable {
    /// X9.63 sıkıştırılmamış açık anahtar (65 bayt).
    var publicKeyX963: Data { get }
    func sharedSecret(with peerX963: Data) throws -> SharedSecret
}

public struct SoftwareAgreement: DeviceAgreement {
    public let rawRepresentation: Data
    public let publicKeyX963: Data

    public init() {
        let key = P256.KeyAgreement.PrivateKey()
        rawRepresentation = key.rawRepresentation
        publicKeyX963 = key.publicKey.x963Representation
    }

    public init(rawRepresentation: Data) throws {
        let key = try P256.KeyAgreement.PrivateKey(rawRepresentation: rawRepresentation)
        self.rawRepresentation = key.rawRepresentation
        publicKeyX963 = key.publicKey.x963Representation
    }

    public func sharedSecret(with peerX963: Data) throws -> SharedSecret {
        let peer = try P256.KeyAgreement.PublicKey(x963Representation: peerX963)
        return try P256.KeyAgreement.PrivateKey(rawRepresentation: rawRepresentation)
            .sharedSecretFromKeyAgreement(with: peer)
    }
}

public enum Direction: String, Sendable {
    case engineToDevice = "e2d"
    case deviceToEngine = "d2e"
}

/// Şifreli zarf: {"v":1, "e": geçici açık anahtar, "n": nonce, "c": şifreli metin + etiket}.
/// Bağlam (yön, motor ve cihaz kimliği) HKDF bilgisinde ve GCM ek verisindedir: aktarma servisi
/// mesajı başka cihaza veya yöne yönlendirirse çözülemez.
public enum Envelope {
    static let tagBytes = 16

    public static func info(_ direction: Direction, engineID: String, deviceID: String) -> Data {
        Data("ati-remote-v1|\(direction.rawValue)|\(engineID)|\(deviceID)".utf8)
    }

    static func key(shared: SharedSecret, ephemeral: Data, recipient: Data, info: Data) -> SymmetricKey {
        shared.hkdfDerivedSymmetricKey(
            using: SHA256.self, salt: ephemeral + recipient, sharedInfo: info, outputByteCount: 32)
    }

    /// ``ephemeral`` ve ``nonce`` yalnızca test vektörleri içindir; normalde her mesajda yenidir.
    public static func seal(
        _ plaintext: Data, to recipientX963: Data, info: Data,
        ephemeral: P256.KeyAgreement.PrivateKey = P256.KeyAgreement.PrivateKey(),
        nonce: AES.GCM.Nonce = AES.GCM.Nonce()
    ) throws -> [String: Any] {
        let recipient = try P256.KeyAgreement.PublicKey(x963Representation: recipientX963)
        let shared = try ephemeral.sharedSecretFromKeyAgreement(with: recipient)
        let eph = ephemeral.publicKey.x963Representation
        let symmetric = key(shared: shared, ephemeral: eph, recipient: recipientX963, info: info)
        let box = try AES.GCM.seal(plaintext, using: symmetric, nonce: nonce, authenticating: info)
        let nonceData = nonce.withUnsafeBytes { Data($0) }
        return [
            "v": 1, "e": Codec.base64(eph), "n": Codec.base64(nonceData),
            "c": Codec.base64(box.ciphertext + box.tag),
        ]
    }

    public static func open(_ envelope: Any?, with agreement: DeviceAgreement, info: Data) throws -> Data {
        guard let env = envelope as? [String: Any], intValue(env["v"]) == 1,
            let e = env["e"] as? String, let n = env["n"] as? String, let c = env["c"] as? String,
            c.count <= 96_000
        else { throw ProtocolError.undecryptable }
        guard let eph = try? Codec.unbase64(e), let nonceData = try? Codec.unbase64(n),
            let sealed = try? Codec.unbase64(c), nonceData.count == 12, sealed.count >= tagBytes
        else { throw ProtocolError.undecryptable }
        do {
            let shared = try agreement.sharedSecret(with: eph)
            let symmetric = key(shared: shared, ephemeral: eph, recipient: agreement.publicKeyX963, info: info)
            let box = try AES.GCM.SealedBox(
                nonce: AES.GCM.Nonce(data: nonceData), ciphertext: sealed.prefix(sealed.count - tagBytes),
                tag: sealed.suffix(tagBytes))
            return try AES.GCM.open(box, using: symmetric, authenticating: info)
        } catch {
            throw ProtocolError.undecryptable
        }
    }

    public static func sealJSON(_ object: [String: Any], to recipientX963: Data, info: Data) throws -> [String: Any] {
        try seal(Data(try Codec.json(object).utf8), to: recipientX963, info: info)
    }

    public static func openJSON(_ envelope: Any?, with agreement: DeviceAgreement, info: Data) throws -> [String: Any] {
        let data = try open(envelope, with: agreement, info: info)
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProtocolError.undecryptable
        }
        return object
    }

    static func intValue(_ value: Any?) -> Int? {
        if let int = value as? Int { return int }
        return (value as? NSNumber)?.intValue
    }
}

// MARK: - Eşleştirme kodu (QR)

public struct PairingCode: Codable, Equatable, Sendable {
    public let v: Int
    public let relay: String
    public let engine_id: String
    public let engine_key: String
    /// Motorun şifreleme anahtarı (P-256, X9.63). QR bant dışı olduğu için güvenilir kaynaktır.
    public let engine_kx: String
    public let pair: String
    public let exp: Int64

    /// QR metnini ayrıştırır ve denetler: güvenli adres, kimlik-anahtar uyumu, süre.
    /// QR içeriği doğrudan JSON ya da telefon sayfasının adresi olabilir
    /// (`https://…/telefon#p=<base64url JSON>`); adres biçiminde JSON # kısmından çıkarılır.
    static func payloadText(_ text: String) -> String {
        guard text.hasPrefix("https://") || text.hasPrefix("http://"),
              let marker = text.range(of: "#p=") else { return text }
        var encoded = String(text[marker.upperBound...])
        if let end = encoded.firstIndex(of: "&") { encoded = String(encoded[..<end]) }
        encoded = encoded.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while encoded.count % 4 != 0 { encoded += "=" }
        guard let data = Data(base64Encoded: encoded), let json = String(data: data, encoding: .utf8) else {
            return text
        }
        return json
    }

    public static func parse(_ text: String, now: Date = Date()) throws -> PairingCode {
        guard let code = try? JSONDecoder().decode(PairingCode.self, from: Data(payloadText(text).utf8)) else {
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
        guard let kx = try? Codec.unbase64(code.engine_kx),
            (try? P256.KeyAgreement.PublicKey(x963Representation: kx)) != nil
        else {
            throw ProtocolError.invalidPairingCode("Şifreleme anahtarı geçersiz; masaüstü uygulamasını güncelleyin")
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
        code: PairingCode, signing: DeviceSigner, guardedKey: Data, agreementKey: Data, name: String,
        protection: String, now: Date = Date(), nonce: String = UUID().uuidString
    ) throws -> SignedMessage {
        let deviceID = Codec.keyID(signing.publicKeyX963)
        let payload: [String: Any] = [
            "v": 1, "type": "pair_request", "engine_id": code.engine_id, "device_id": deviceID,
            "name": String(name.prefix(60)), "signing_key": Codec.base64(signing.publicKeyX963),
            "guarded_key": Codec.base64(guardedKey), "kx_key": Codec.base64(agreementKey),
            "protection": protection, "ts_ms": nowMs(now), "nonce": nonce,
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

    /// Motora giden çerçeve: imzalı mesaj, motorun şifreleme anahtarına şifrelenir.
    public static func toEngine(
        _ message: SignedMessage, engineKX: Data, engineID: String, deviceID: String
    ) throws -> String {
        let envelope = try Envelope.sealJSON(
            message.dictionary, to: engineKX,
            info: Envelope.info(.deviceToEngine, engineID: engineID, deviceID: deviceID))
        return try Codec.json(["type": "to_engine", "msg": envelope])
    }
}
