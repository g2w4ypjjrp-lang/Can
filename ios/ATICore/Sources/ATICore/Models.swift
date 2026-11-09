// Motordan gelen imzalı mesajların modelleri (özet, sonuç, bildirim, eşleştirme sonucu).

import Foundation

public struct EngineSummary: Codable, Equatable, Sendable {
    public var state: String
    public var reason: String?
    public var trading_mode: String
    public var kill_switch: Bool
    public var kill_reason: String?
    public var uptime_s: Int?
    public var version: String?
}

public struct RiskSummary: Codable, Equatable, Sendable {
    public var daily_loss_pct: Double
    public var halted: Bool
    public var equity: String
}

public struct PositionSummary: Codable, Equatable, Sendable, Identifiable {
    public var market: String
    public var symbol: String
    public var quantity: String
    public var entry_price: String?
    public var realized_pnl: String?
    public var protected: Bool?
    public var id: String { "\(market)-\(symbol)" }
}

public struct AutotradeSummary: Codable, Equatable, Sendable {
    public var enabled: Bool
    public var opened: Int
    public var rejected: Int
}

public struct OpportunityItem: Codable, Equatable, Sendable, Identifiable {
    public var market: String
    public var symbol: String
    public var direction: String
    public var score: Int
    public var reward_risk: Double?
    public var id: String { "\(market)-\(symbol)" }
}

public struct WhaleItem: Codable, Equatable, Sendable, Identifiable {
    public var ts_ms: Int64
    public var symbol: String
    public var message: String
    public var id: String { "\(ts_ms)-\(symbol)" }
}

public struct PaperSummary: Codable, Equatable, Sendable {
    public var accounts: Int
    public var open_positions: Int
    public var trades: Int
    public var net_pnl: Double
}

/// Bilgisayardaki lisansın özeti (Aşama 15). Anahtar veya cihaz kimliği içermez.
public struct LicenseSummary: Codable, Equatable, Sendable {
    public var state: String
    public var valid: Bool
    public var enforced: Bool
    public var plan_name: String?
    public var expires_at: Int64?
    public var message: String

    /// Lisans zorunlu ve geçersizse motor yeni işlem açmaz.
    public var blocksTrading: Bool { enforced && !valid }
}

public struct SnapshotData: Codable, Equatable, Sendable {
    public var engine: EngineSummary
    public var risk: RiskSummary?
    public var positions: [PositionSummary]?
    public var autotrade: AutotradeSummary?
    public var opportunities: [OpportunityItem]?
    public var whales: [WhaleItem]?
    public var paper: PaperSummary?
    public var license: LicenseSummary?
}

public struct EventItem: Codable, Equatable, Sendable, Identifiable {
    public var device_id: String?
    public var ts_ms: Int64
    public var kind: String
    public var title: String
    public var body: String
    public var id: String { "\(ts_ms)-\(kind)-\(title)" }
}

public struct Snapshot: Codable, Equatable, Sendable {
    public var device_id: String
    public var ts_ms: Int64
    public var data: SnapshotData
    public var events: [EventItem]
}

public struct CommandResult: Codable, Equatable, Sendable {
    public var device_id: String
    public var seq: Int64?
    public var command: String?
    public var ok: Bool
    public var reason: String
    public var message: String
}

public struct PairResult: Codable, Equatable, Sendable {
    public var device_id: String
    public var ok: Bool
    public var reason: String
    public var name: String?
}

public enum EngineMessage: Equatable, Sendable {
    case snapshot(Snapshot)
    case result(CommandResult)
    case event(EventItem)
    case paired(PairResult)
}

extension EngineVerifier {
    /// Aktarma servisinden gelen çerçeveyi çözer: imza doğrulanmadan hiçbir içerik kullanılmaz.
    public func message(from frame: String) throws -> EngineMessage? {
        guard let object = try JSONSerialization.jsonObject(with: Data(frame.utf8)) as? [String: Any],
            object["type"] as? String == "from_engine",
            let msg = object["msg"] as? [String: Any],
            let p = msg["p"] as? String, let s = msg["s"] as? String
        else { return nil }
        let signed = SignedMessage(p: p, s: s)
        let payload = try open(signed)
        let data = Data(p.utf8)
        let decoder = JSONDecoder()
        switch payload["type"] as? String {
        case "snapshot": return .snapshot(try decoder.decode(Snapshot.self, from: data))
        case "result": return .result(try decoder.decode(CommandResult.self, from: data))
        case "event": return .event(try decoder.decode(EventItem.self, from: data))
        case "pair_result": return .paired(try decoder.decode(PairResult.self, from: data))
        default: return nil
        }
    }
}

/// Aktarma servisinin imzasız durum çerçeveleri (yalnızca bilgi; komut değildir).
public enum RelayStatus: Equatable, Sendable {
    case welcome(engineOnline: Bool)
    case engineOffline
    case error(String)

    public static func parse(_ frame: String) -> RelayStatus? {
        guard let object = try? JSONSerialization.jsonObject(with: Data(frame.utf8)) as? [String: Any] else {
            return nil
        }
        switch object["type"] as? String {
        case "welcome": return .welcome(engineOnline: object["engine_online"] as? Bool ?? false)
        case "engine_offline": return .engineOffline
        case "error": return .error(object["reason"] as? String ?? "")
        default: return nil
        }
    }
}

/// Komut sonuçlarının kullanıcıya gösterilen Türkçe açıklaması.
public enum ReasonText {
    public static func text(_ reason: String) -> String {
        switch reason {
        case "ok": return "Uygulandı"
        case "replay": return "Bu komut daha önce işlendi"
        case "stale": return "Telefon saati yanlış veya komut gecikti"
        case "bad_signature": return "İmza geçersiz"
        case "biometric_required": return "Face ID onayı gerekli"
        case "revoked_device": return "Bu telefonun eşleştirmesi kaldırılmış"
        case "unknown_device": return "Telefon eşleştirilmemiş"
        case "not_allowed": return "Bu işlem uzaktan yapılamaz"
        case "failed": return "Motor işlemi uygulayamadı"
        case "device_limit":
            return "Lisansınızın telefon sınırına ulaşıldı. Bilgisayarda kullanmadığınız bir telefonun eşleştirmesini kaldırın."
        default: return reason
        }
    }
}
