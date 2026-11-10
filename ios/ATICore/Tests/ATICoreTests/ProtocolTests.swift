import Foundation
import XCTest

@testable import ATICore

#if canImport(CryptoKit)
    @preconcurrency import CryptoKit
#else
    @preconcurrency import Crypto
#endif

/// Motorun (Python) ürettiği ortak test vektörleri: shared/protocol/test-vectors/remote-v1.json
struct Vectors: Decodable {
    struct Engine: Decodable {
        let key: String
        let engine_id: String
        let snapshot: SignedMessage
        let tampered_snapshot: SignedMessage
    }
    struct Device: Decodable {
        let private_scalar_hex: String
        let public_x963: String
        let device_id: String
        let command: SignedMessage
    }
    struct Pairing: Decodable {
        let secret_b64url: String
        let payload: String
        let proof: String
    }
    struct Relay: Decodable {
        let device_hello_text: String
    }
    struct Sealed: Decodable {
        let v: Int
        let e: String
        let n: String
        let c: String
        var dictionary: [String: Any] { ["v": v, "e": e, "n": n, "c": c] }
    }
    struct EnvelopeCase: Decodable {
        let info: String
        let ephemeral_private_hex: String
        let nonce: String
        let plaintext: String
        let envelope: Sealed
    }
    struct Envelopes: Decodable {
        let device_kx_private_hex: String
        let device_kx_public_x963: String
        let engine_kx_private_hex: String
        let engine_kx_public_x963: String
        let e2d: EnvelopeCase
        let d2e: EnvelopeCase
    }
    let engine: Engine
    let device: Device
    let pairing: Pairing
    let relay: Relay
    let envelope: Envelopes

    static func load() throws -> Vectors {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("shared/protocol/test-vectors/remote-v1.json")
        return try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: url))
    }
}

final class VectorTests: XCTestCase {
    func testEngineSignatureFromPythonVerifies() throws {
        let v = try Vectors.load()
        let verifier = try EngineVerifier(engineKey: try Codec.unbase64(v.engine.key))
        XCTAssertEqual(verifier.engineID, v.engine.engine_id)
        let payload = try verifier.open(v.engine.snapshot)
        XCTAssertEqual(payload["type"] as? String, "snapshot")
        let snapshot = try verifier.decode(Snapshot.self, from: v.engine.snapshot)
        XCTAssertEqual(snapshot.data.engine.trading_mode, "testnet")
        XCTAssertEqual(snapshot.events.first?.body, "Büyük alım ğüşıöç")
    }

    func testTamperedEngineMessageIsRejected() throws {
        let v = try Vectors.load()
        let verifier = try EngineVerifier(engineKey: try Codec.unbase64(v.engine.key))
        XCTAssertThrowsError(try verifier.open(v.engine.tampered_snapshot)) { error in
            XCTAssertEqual(error as? ProtocolError, .badSignature)
        }
    }

    func testDeviceIdentityAndPythonCommandSignature() throws {
        let v = try Vectors.load()
        let x963 = try Codec.unbase64(v.device.public_x963)
        XCTAssertEqual(Codec.keyID(x963), v.device.device_id)
        let signature = try Codec.unbase64(v.device.command.s)
        XCTAssertTrue(P256Verifier.isValid(publicX963: x963, signature: signature, data: Data(v.device.command.p.utf8)))
        XCTAssertFalse(P256Verifier.isValid(publicX963: x963, signature: signature, data: Data("x".utf8)))
    }

    func testSameDeviceKeyFromScalarProducesSameIdentity() throws {
        let v = try Vectors.load()
        let raw = Data(hexString: v.device.private_scalar_hex)
        let signer = try SoftwareSigner(rawRepresentation: raw)
        XCTAssertEqual(Codec.base64(signer.publicKeyX963), v.device.public_x963)
    }

    func testPairingProofMatchesEngine() throws {
        let v = try Vectors.load()
        let key = SymmetricKey(data: try Codec.unbase64URL(v.pairing.secret_b64url))
        let proof = Data(HMAC<SHA256>.authenticationCode(for: Data(v.pairing.payload.utf8), using: key))
        XCTAssertEqual(Codec.base64(proof), v.pairing.proof)
    }

    func testRelayHelloTextMatchesEngine() throws {
        let v = try Vectors.load()
        XCTAssertEqual(
            MessageFactory.helloText(deviceID: v.device.device_id, engineID: v.engine.engine_id, ts: 1_794_100_000_000),
            v.relay.device_hello_text)
    }

    func testFrameDecodingDecryptsThenVerifiesSignature() throws {
        let v = try Vectors.load()
        let verifier = try EngineVerifier(engineKey: try Codec.unbase64(v.engine.key))
        let agreement = try SoftwareAgreement(rawRepresentation: Data(hexString: v.envelope.device_kx_private_hex))
        let device = v.device.device_id
        // Python'un şifrelediği gerçek çerçeve.
        let frame = try Codec.json(["type": "from_engine", "msg": v.envelope.e2d.envelope.dictionary])
        guard case .snapshot(let snap) = try verifier.message(from: frame, agreement: agreement, deviceID: device)
        else { return XCTFail("özet bekleniyordu") }
        XCTAssertEqual(snap.data.positions?.first?.symbol, "BTCUSDT")
        // Saldırgan da telefonun açık anahtarına şifreleyebilir; imza yine de tutmaz.
        let info = Envelope.info(.engineToDevice, engineID: v.engine.engine_id, deviceID: device)
        let forgedEnvelope = try Envelope.sealJSON(v.engine.tampered_snapshot.dictionary, to: agreement.publicKeyX963, info: info)
        let forged = try Codec.json(["type": "from_engine", "msg": forgedEnvelope])
        XCTAssertThrowsError(try verifier.message(from: forged, agreement: agreement, deviceID: device)) { error in
            XCTAssertEqual(error as? ProtocolError, .badSignature)
        }
        // Şifresiz (eski biçim) ve başka cihaza ait çerçeve çözülemez.
        let plaintext = try Codec.json(["type": "from_engine", "msg": v.engine.snapshot.dictionary])
        XCTAssertThrowsError(try verifier.message(from: plaintext, agreement: agreement, deviceID: device)) { error in
            XCTAssertEqual(error as? ProtocolError, .undecryptable)
        }
        XCTAssertThrowsError(try verifier.message(from: frame, agreement: agreement, deviceID: "baska")) { error in
            XCTAssertEqual(error as? ProtocolError, .undecryptable)
        }
        XCTAssertThrowsError(try verifier.message(from: frame, agreement: SoftwareAgreement(), deviceID: device))
        XCTAssertNil(try verifier.message(from: #"{"type":"engine_offline"}"#, agreement: agreement, deviceID: device))
    }

    func testEnvelopeVectorsOpenAndReproduce() throws {
        let v = try Vectors.load()
        let cases: [(Vectors.EnvelopeCase, String)] = [
            (v.envelope.e2d, v.envelope.device_kx_private_hex),
            (v.envelope.d2e, v.envelope.engine_kx_private_hex),
        ]
        for (item, recipientHex) in cases {
            let recipient = try SoftwareAgreement(rawRepresentation: Data(hexString: recipientHex))
            let info = Data(item.info.utf8)
            let opened = try Envelope.open(item.envelope.dictionary, with: recipient, info: info)
            XCTAssertEqual(String(data: opened, encoding: .utf8), item.plaintext)
            let again = try Envelope.seal(
                Data(item.plaintext.utf8), to: recipient.publicKeyX963, info: info,
                ephemeral: try P256.KeyAgreement.PrivateKey(rawRepresentation: Data(hexString: item.ephemeral_private_hex)),
                nonce: try AES.GCM.Nonce(data: try Codec.unbase64(item.nonce)))
            XCTAssertEqual(again["e"] as? String, item.envelope.e)
            XCTAssertEqual(again["n"] as? String, item.envelope.n)
            XCTAssertEqual(again["c"] as? String, item.envelope.c)  // Python ile bayt bayt aynı
            var flipped = try Codec.unbase64(item.envelope.c)
            flipped[0] ^= 1
            var tampered = item.envelope.dictionary
            tampered["c"] = Codec.base64(flipped)
            XCTAssertThrowsError(try Envelope.open(tampered, with: recipient, info: info))
            XCTAssertThrowsError(try Envelope.open(item.envelope.dictionary, with: recipient, info: Data("x".utf8)))
        }
        XCTAssertEqual(
            try SoftwareAgreement(rawRepresentation: Data(hexString: v.envelope.device_kx_private_hex)).publicKeyX963,
            try Codec.unbase64(v.envelope.device_kx_public_x963))
    }
}

final class FactoryTests: XCTestCase {
    func code(relay: String = "wss://relay.example", expired: Bool = false) throws -> (PairingCode, String) {
        let engine = Curve25519.Signing.PrivateKey()
        let key = engine.publicKey.rawRepresentation
        let secret = Data(repeating: 7, count: 32).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        let exp = MessageFactory.nowMs() + (expired ? -1000 : 300_000)
        let text = try Codec.json([
            "v": 1, "relay": relay, "engine_id": Codec.keyID(key), "engine_key": Codec.base64(key),
            "engine_kx": Codec.base64(P256.KeyAgreement.PrivateKey().publicKey.x963Representation),
            "pair": secret, "exp": exp,
        ])
        return (try PairingCode.parse(text), text)
    }

    func testPairingCodeValidation() throws {
        let (parsed, _) = try code()
        XCTAssertEqual(parsed.relay, "wss://relay.example")
        XCTAssertThrowsError(try code(relay: "ws://relay.example"))
        XCTAssertThrowsError(try code(expired: true))
        XCTAssertThrowsError(try PairingCode.parse("çöp"))
        var dict = try JSONSerialization.jsonObject(with: Data(try code().1.utf8)) as! [String: Any]
        dict["engine_id"] = String(repeating: "0", count: 32)
        XCTAssertThrowsError(try PairingCode.parse(try Codec.json(dict)))
        // Şifreleme anahtarı eksik (eski masaüstü) veya geçersizse kod reddedilir.
        var noKX = try JSONSerialization.jsonObject(with: Data(try code().1.utf8)) as! [String: Any]
        noKX.removeValue(forKey: "engine_kx")
        XCTAssertThrowsError(try PairingCode.parse(try Codec.json(noKX)))
        noKX["engine_kx"] = Codec.base64(Data(repeating: 4, count: 65))
        XCTAssertThrowsError(try PairingCode.parse(try Codec.json(noKX)))
    }

    func testPairRequestCarriesProofAndSignature() throws {
        let (pairing, _) = try code()
        let signing = SoftwareSigner()
        let guarded = SoftwareSigner()
        let agreement = SoftwareAgreement()
        let msg = try MessageFactory.pairRequest(
            code: pairing, signing: signing, guardedKey: guarded.publicKeyX963,
            agreementKey: agreement.publicKeyX963, name: "iPhone", protection: "software")
        let data = Data(msg.p.utf8)
        XCTAssertTrue(P256Verifier.isValid(publicX963: signing.publicKeyX963, signature: try Codec.unbase64(msg.s), data: data))
        let key = SymmetricKey(data: try Codec.unbase64URL(pairing.pair))
        XCTAssertEqual(msg.proof, Codec.base64(Data(HMAC<SHA256>.authenticationCode(for: data, using: key))))
        let payload = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(payload["device_id"] as? String, Codec.keyID(signing.publicKeyX963))
        XCTAssertEqual(payload["guarded_key"] as? String, Codec.base64(guarded.publicKeyX963))
        XCTAssertEqual(payload["kx_key"] as? String, Codec.base64(agreement.publicKeyX963))
    }

    func testFramesToEngineAreEncryptedForEngineAndDevice() throws {
        let engineKX = SoftwareAgreement()
        let signing = SoftwareSigner()
        let deviceID = Codec.keyID(signing.publicKeyX963)
        let engineID = String(repeating: "c", count: 32)
        let message = try MessageFactory.command(
            .engageKillSwitch, engineID: engineID, deviceID: deviceID, signer: signing, key: .signing, seq: 1)
        let frame = try MessageFactory.toEngine(message, engineKX: engineKX.publicKeyX963, engineID: engineID, deviceID: deviceID)
        XCTAssertFalse(frame.contains("engage_kill_switch"))
        let object = try JSONSerialization.jsonObject(with: Data(frame.utf8)) as! [String: Any]
        XCTAssertEqual(object["type"] as? String, "to_engine")
        let info = Envelope.info(.deviceToEngine, engineID: engineID, deviceID: deviceID)
        let opened = try Envelope.openJSON(object["msg"], with: engineKX, info: info)
        XCTAssertEqual(opened["p"] as? String, message.p)
        XCTAssertThrowsError(
            try Envelope.openJSON(object["msg"], with: engineKX, info: Envelope.info(.engineToDevice, engineID: engineID, deviceID: deviceID)))
    }

    func testCommandIsSignedWithRequestedKey() throws {
        let signing = SoftwareSigner()
        var counter = SequenceCounter()
        let seq = counter.next()
        let msg = try MessageFactory.command(
            .closePosition, args: ["market": "usdm_futures", "symbol": "BTCUSDT"],
            engineID: String(repeating: "a", count: 32), deviceID: Codec.keyID(signing.publicKeyX963),
            signer: signing, key: .guarded, seq: seq)
        XCTAssertTrue(P256Verifier.isValid(publicX963: signing.publicKeyX963, signature: try Codec.unbase64(msg.s), data: Data(msg.p.utf8)))
        XCTAssertFalse(msg.p.contains(" "))
        let payload = try JSONSerialization.jsonObject(with: Data(msg.p.utf8)) as! [String: Any]
        XCTAssertEqual(payload["command"] as? String, "close_position")
        XCTAssertEqual(payload["key"] as? String, "guarded")
        XCTAssertEqual((payload["seq"] as? NSNumber)?.int64Value, seq)
        XCTAssertEqual((payload["args"] as? [String: String])?["symbol"], "BTCUSDT")
    }

    func testSequenceNeverGoesBackwards() {
        var counter = SequenceCounter(last: 5_000_000_000_000)  // gelecekteki bir değer
        let a = counter.next()
        let b = counter.next()
        XCTAssertEqual(b, a + 1)
        var fresh = SequenceCounter()
        let first = fresh.next(now: Date(timeIntervalSince1970: 1_794_100_000))
        XCTAssertEqual(first, 1_794_100_000_000)
        XCTAssertEqual(fresh.next(now: Date(timeIntervalSince1970: 1_000)), first + 1)
    }

    func testAllowlistMatchesEngine() {
        let guarded = Set(RemoteCommand.allCases.filter { $0.requiredKey == .guarded }.map(\.rawValue))
        XCTAssertEqual(guarded, ["resume_autotrade", "release_kill_switch", "close_position", "close_all"])
        XCTAssertEqual(RemoteCommand.engageKillSwitch.requiredKey, .signing)
        XCTAssertFalse(RemoteCommand.allCases.contains { $0.rawValue.contains("open") || $0.rawValue.contains("withdraw") })
    }

    func testHelloIsVerifiableByRelay() throws {
        let signer = SoftwareSigner()
        let engineID = String(repeating: "b", count: 32)
        let text = try MessageFactory.hello(engineID: engineID, signer: signer)
        let hello = try JSONSerialization.jsonObject(with: Data(text.utf8)) as! [String: Any]
        let ts = (hello["ts_ms"] as! NSNumber).int64Value
        let signed = MessageFactory.helloText(deviceID: hello["device_id"] as! String, engineID: engineID, ts: ts)
        XCTAssertTrue(P256Verifier.isValid(publicX963: signer.publicKeyX963, signature: try Codec.unbase64(hello["sig"] as! String), data: Data(signed.utf8)))
    }
}

final class SessionTests: XCTestCase {
    func snapshot(_ ts: Int64, device: String = "d1", kill: Bool = false) -> Snapshot {
        Snapshot(
            device_id: device, ts_ms: ts,
            data: SnapshotData(engine: EngineSummary(state: "running", trading_mode: "testnet", kill_switch: kill)),
            events: [EventItem(device_id: device, ts_ms: ts - 1, kind: "whale", title: "Balina", body: "x")])
    }

    func testOlderSnapshotIsIgnoredAndEventsDeduplicated() {
        var state = SessionState(deviceID: "d1")
        state.apply(.snapshot(snapshot(2000, kill: true)))
        state.apply(.snapshot(snapshot(1000, kill: false)))  // eski özet tekrar oynatıldı
        XCTAssertEqual(state.snapshot?.data.engine.kill_switch, true)
        state.apply(.snapshot(snapshot(2000, kill: true)))
        XCTAssertEqual(state.events.count, 1)  // eski özetin olayları da alınmaz
        XCTAssertEqual(state.events.first?.ts_ms, 1999)
    }

    func testMessagesForOtherDevicesAreIgnored() {
        var state = SessionState(deviceID: "d1")
        state.apply(.snapshot(snapshot(1000, device: "d2")))
        XCTAssertNil(state.snapshot)
        state.apply(.result(CommandResult(device_id: "d2", seq: 1, command: "close_all", ok: true, reason: "ok", message: "")))
        XCTAssertNil(state.lastResult)
        state.apply(.result(CommandResult(device_id: "d1", seq: 2, command: "engage_kill_switch", ok: true, reason: "ok", message: "Acil durdurma devrede")))
        XCTAssertEqual(state.lastResult?.message, "Acil durdurma devrede")
        state.apply(.engineOffline)
        XCTAssertFalse(state.engineOnline)
    }

    func testRelayStatusParsing() {
        XCTAssertEqual(RelayStatus.parse(#"{"type":"welcome","role":"device","engine_online":true}"#), .welcome(engineOnline: true))
        XCTAssertEqual(RelayStatus.parse(#"{"type":"engine_offline"}"#), .engineOffline)
        XCTAssertEqual(RelayStatus.parse(#"{"type":"error","reason":"rate_limited"}"#), .error("rate_limited"))
        XCTAssertEqual(ReasonText.text("biometric_required"), "Face ID onayı gerekli")
    }
}

extension Data {
    init(hexString: String) {
        var data = Data()
        var index = hexString.startIndex
        while index < hexString.endIndex {
            let next = hexString.index(index, offsetBy: 2)
            data.append(UInt8(hexString[index..<next], radix: 16)!)
            index = next
        }
        self = data
    }
}
