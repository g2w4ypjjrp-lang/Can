// Oturum durumu: motordan gelen (imzası doğrulanmış) mesajların ekrana yansıması.
//
// Ek savunma: aktarma servisi eski ama geçerli imzalı bir özeti tekrar gönderebilir. Bu yüzden
// yalnızca daha yeni özetler kabul edilir. Başka bir cihaza ait mesajlar yok sayılır.

import Foundation

public struct SessionState: Equatable, Sendable {
    public let deviceID: String
    public private(set) var snapshot: Snapshot?
    public private(set) var events: [EventItem] = []
    public private(set) var lastResult: CommandResult?
    public private(set) var pairResult: PairResult?
    public private(set) var engineOnline = false
    public private(set) var relayError: String?
    public static let maxEvents = 100

    public init(deviceID: String) { self.deviceID = deviceID }

    public mutating func apply(_ message: EngineMessage) {
        switch message {
        case .snapshot(let snap):
            guard snap.device_id == deviceID else { return }
            if let current = snapshot, snap.ts_ms < current.ts_ms { return }  // eski özet
            snapshot = snap
            engineOnline = true
            for event in snap.events { insert(event) }
        case .event(let event):
            guard event.device_id == nil || event.device_id == deviceID else { return }
            insert(event)
        case .result(let result):
            guard result.device_id == deviceID else { return }
            lastResult = result
        case .paired(let result):
            guard result.device_id == deviceID else { return }
            pairResult = result
        }
    }

    public mutating func apply(_ status: RelayStatus) {
        switch status {
        case .welcome(let online):
            engineOnline = online
            relayError = nil
        case .engineOffline:
            engineOnline = false
        case .error(let reason):
            relayError = reason
        }
    }

    private mutating func insert(_ event: EventItem) {
        guard !events.contains(where: { $0.id == event.id }) else { return }
        events.append(event)
        events.sort { $0.ts_ms > $1.ts_ms }
        if events.count > Self.maxEvents { events.removeLast(events.count - Self.maxEvents) }
    }

    /// Özetin yaşı (sn); bağlantı koptuysa kullanıcıya gösterilir.
    public func snapshotAge(now: Date = Date()) -> Int? {
        guard let snapshot else { return nil }
        return max(0, Int((MessageFactory.nowMs(now) - snapshot.ts_ms) / 1000))
    }
}
