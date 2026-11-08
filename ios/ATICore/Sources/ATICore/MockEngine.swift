// Aktarma servisi + motor benzetimi (bellek içi). Arayüz testleri ve birim testleri için:
// gerçek motorla aynı kuralları uygular (HMAC kanıtı, P-256 imza, sıra numarası, izin listesi,
// korumalı anahtar) ve yanıtlarını Ed25519 ile imzalar.

import Foundation

#if canImport(CryptoKit)
    import CryptoKit
#else
    import Crypto
#endif

public actor MockEngine: FrameTransport {
    private var devices: [String: (signing: Data, guarded: Data, name: String)] = [:]
    private var lastSeq: [String: Int64] = [:]
    private var helloDevice: String?
    private var otherChannel = false
    private var queue: [String] = []
    private var waiters: [CheckedContinuation<String, Error>] = []
    private var closed = false
    private var clock: Int64 = MessageFactory.nowMs()

    public private(set) var killSwitch = false
    public private(set) var autotrade = false
    public private(set) var positions: [PositionSummary] = [
        PositionSummary(market: "usdm_futures", symbol: "BTCUSDT", quantity: "0.5", entry_price: "75000", realized_pnl: "0", protected: true),
        PositionSummary(market: "usdm_futures", symbol: "ETHUSDT", quantity: "-2", entry_price: "3500", realized_pnl: "12.5", protected: true),
    ]
    public private(set) var rejections: [String] = []
    public let relayURL = "ws://127.0.0.1:1"
    public nonisolated let engineID: String
    public nonisolated let pairingCode: String

    public init() {
        let key = Curve25519.Signing.PrivateKey()
        let secret = Data((0..<32).map { _ in UInt8.random(in: 0...255) })
        // Not: actor içindeki anahtarlar init'te ayarlanır; aşağıdaki değerler onlarla aynıdır.
        let publicRaw = key.publicKey.rawRepresentation
        engineID = Codec.keyID(publicRaw)
        let pair = secret.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        pairingCode = (try? Codec.json([
            "v": 1, "relay": "ws://127.0.0.1:1", "engine_id": Codec.keyID(publicRaw),
            "engine_key": Codec.base64(publicRaw), "pair": pair,
            "exp": MessageFactory.nowMs() + 600_000,
        ])) ?? ""
        _engineKey = key
        _pairSecret = secret
    }

    private let _engineKey: Curve25519.Signing.PrivateKey
    private let _pairSecret: Data

    // MARK: FrameTransport

    public func connect(to url: URL) async throws {
        closed = false
    }

    public func send(_ text: String) async throws {
        guard let frame = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { return }
        switch frame["type"] as? String {
        case "hello": hello(frame)
        case "to_engine":
            if otherChannel {
                push(#"{"type":"engine_offline"}"#)
            } else if let msg = frame["msg"] as? [String: Any], let device = helloDevice {
                fromDevice(msg, device: device)
            }
        default: break
        }
    }

    public func receive() async throws -> String {
        if !queue.isEmpty { return queue.removeFirst() }
        if closed { throw CancellationError() }
        return try await withCheckedThrowingContinuation { waiters.append($0) }
    }

    public func close() async {
        closed = true
        for waiter in waiters { waiter.resume(throwing: CancellationError()) }
        waiters.removeAll()
        helloDevice = nil
    }

    private func push(_ frame: String) {
        if !waiters.isEmpty {
            waiters.removeFirst().resume(returning: frame)
        } else {
            queue.append(frame)
        }
    }

    // MARK: Benzetilen motor

    private func hello(_ frame: [String: Any]) {
        // Gerçek aktarma servisi gibi: imza, cihazın kendi anahtarı ve bildirdiği kanal üzerinden
        // denetlenir. Başka bir motorun kanalına bağlanan cihaz kabul edilir ama motor çevrim dışıdır.
        guard let keyText = frame["key"] as? String, let key = try? Codec.unbase64(keyText),
            let deviceID = frame["device_id"] as? String, deviceID == Codec.keyID(key),
            let channel = frame["engine_id"] as? String,
            let ts = (frame["ts_ms"] as? NSNumber)?.int64Value, let sigText = frame["sig"] as? String,
            let sig = try? Codec.unbase64(sigText),
            P256Verifier.isValid(
                publicX963: key, signature: sig,
                data: Data(MessageFactory.helloText(deviceID: deviceID, engineID: channel, ts: ts).utf8))
        else {
            rejections.append("hello")
            return
        }
        guard channel == engineID else {
            otherChannel = true
            push(#"{"type":"welcome","role":"device","engine_online":false}"#)
            return
        }
        otherChannel = false
        helloDevice = deviceID
        push(#"{"type":"welcome","role":"device","engine_online":true}"#)
        if devices[deviceID] != nil { pushSnapshot(deviceID) }
    }

    private func fromDevice(_ msg: [String: Any], device: String) {
        guard let p = msg["p"] as? String, let s = msg["s"] as? String, let sig = try? Codec.unbase64(s),
            let payload = try? JSONSerialization.jsonObject(with: Data(p.utf8)) as? [String: Any]
        else { return reject(device, "malformed", nil) }
        let data = Data(p.utf8)
        if let proofText = msg["proof"] as? String {
            let proof = (try? Codec.unbase64(proofText)) ?? Data()
            let expected = Data(HMAC<SHA256>.authenticationCode(for: data, using: SymmetricKey(data: _pairSecret)))
            guard proof == expected, let signingText = payload["signing_key"] as? String,
                let signing = try? Codec.unbase64(signingText),
                let guardedText = payload["guarded_key"] as? String, let guarded = try? Codec.unbase64(guardedText),
                Codec.keyID(signing) == device, P256Verifier.isValid(publicX963: signing, signature: sig, data: data)
            else {
                rejections.append("pair")
                return
            }
            devices[device] = (signing, guarded, payload["name"] as? String ?? "iPhone")
            sign(["type": "pair_result", "device_id": device, "ok": true, "reason": "ok", "name": "Test Bilgisayarı"], to: device)
            pushSnapshot(device)
            return
        }
        guard let registered = devices[device] else { return reject(device, "unknown_device", nil) }
        let seq = (payload["seq"] as? NSNumber)?.int64Value ?? 0
        let command = payload["command"] as? String ?? ""
        let key = payload["key"] as? String
        let publicKey = key == "guarded" ? registered.guarded : registered.signing
        guard payload["engine_id"] as? String == engineID else { return reject(device, "wrong_engine", seq) }
        guard P256Verifier.isValid(publicX963: publicKey, signature: sig, data: data) else {
            return reject(device, "bad_signature", seq)
        }
        guard seq > lastSeq[device, default: 0] else { return reject(device, "replay", seq) }
        guard let allowed = RemoteCommand(rawValue: command) else { return reject(device, "not_allowed", seq) }
        guard allowed.requiredKey != .guarded || key == "guarded" else { return reject(device, "biometric_required", seq) }
        lastSeq[device] = seq
        let args = payload["args"] as? [String: String] ?? [:]
        let message: String
        switch allowed {
        case .engageKillSwitch: killSwitch = true; message = "Acil durdurma devrede"
        case .releaseKillSwitch: killSwitch = false; message = "Acil durdurma kaldırıldı"
        case .pauseAutotrade: autotrade = false; message = "Otomatik işlem durduruldu"
        case .resumeAutotrade: autotrade = true; message = "Otomatik işlem başlatıldı"
        case .closePosition:
            positions.removeAll { $0.symbol == args["symbol"] }
            message = "\(args["symbol"] ?? "") kapatıldı"
        case .closeAll:
            let count = positions.count
            positions.removeAll()
            message = "\(count) pozisyon kapatıldı"
        case .requestSnapshot: message = "Güncel durum gönderiliyor"
        }
        sign(["type": "result", "device_id": device, "seq": seq, "command": command, "ok": true, "reason": "ok", "message": message], to: device)
        pushSnapshot(device)
    }

    private func reject(_ device: String, _ reason: String, _ seq: Int64?) {
        rejections.append(reason)
        guard devices[device] != nil else { return }
        var payload: [String: Any] = ["type": "result", "device_id": device, "ok": false, "reason": reason, "message": reason]
        if let seq { payload["seq"] = seq }
        sign(payload, to: device)
    }

    private func signed(_ payload: [String: Any]) -> [String: Any] {
        clock = max(clock + 1, MessageFactory.nowMs())
        var body = payload
        body["v"] = 1
        body["engine_id"] = engineID
        body["ts_ms"] = clock
        let text = (try? Codec.json(body)) ?? "{}"
        let sig = (try? _engineKey.signature(for: Data(text.utf8))) ?? Data()
        return ["p": text, "s": Codec.base64(sig)]
    }

    private func sign(_ payload: [String: Any], to device: String) {
        guard device == helloDevice else { return }
        push((try? Codec.json(["type": "from_engine", "msg": signed(payload)])) ?? "{}")
    }

    private func snapshotPayload(_ device: String, kill: Bool? = nil) -> [String: Any] {
        let positionDicts: [[String: Any]] = positions.map {
            ["market": $0.market, "symbol": $0.symbol, "quantity": $0.quantity, "entry_price": $0.entry_price ?? "",
             "realized_pnl": $0.realized_pnl ?? "0", "protected": $0.protected ?? false]
        }
        return [
            "type": "snapshot", "device_id": device,
            "data": [
                "engine": ["state": (kill ?? killSwitch) ? "halted" : "running", "trading_mode": "testnet",
                           "kill_switch": kill ?? killSwitch, "uptime_s": 3600, "version": "0.13.0"],
                "risk": ["daily_loss_pct": 0.4, "halted": false, "equity": "10000"],
                "positions": positionDicts,
                "autotrade": ["enabled": autotrade, "opened": 3, "rejected": 1],
                "opportunities": [["market": "usdm_futures", "symbol": "SOLUSDT", "direction": "long", "score": 78, "reward_risk": 2.1]],
                "whales": [["ts_ms": MessageFactory.nowMs() - 60_000, "symbol": "BTCUSDT", "message": "BTCUSDT büyük alım: 2,5 Mn USDT"]],
                "paper": ["accounts": 28, "open_positions": 5, "trades": 41, "net_pnl": 123.45],
            ] as [String: Any],
            "events": [["ts_ms": MessageFactory.nowMs() - 30_000, "kind": "whale", "title": "Balina: BTCUSDT", "body": "Büyük alım"]],
        ]
    }

    private func pushSnapshot(_ device: String) {
        sign(snapshotPayload(device), to: device)
    }

    // MARK: Saldırı benzetimi (testler)

    /// Ele geçirilmiş aktarma servisinin sahte özet göndermesi: imza geçersiz.
    public func injectForgedSnapshot() {
        guard let device = helloDevice else { return }
        var msg = signed(snapshotPayload(device, kill: false))
        msg["p"] = (msg["p"] as? String ?? "").replacingOccurrences(of: "\"kill_switch\":false", with: "\"kill_switch\":true")
        push((try? Codec.json(["type": "from_engine", "msg": msg])) ?? "{}")
    }

    /// Aktarma servisinin yakaladığı mesajı tekrar göndermesi (geçerli imzalı ama eski özet).
    public func replayOldSnapshot(_ frame: String) { push(frame) }

    /// Telefonun gönderdiği son komutu aynen tekrar göndermek (tekrar oynatma) için.
    public func deliver(_ text: String) async throws { try await send(text) }
}
