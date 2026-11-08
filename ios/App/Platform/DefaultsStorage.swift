import ATICore
import Foundation

/// Eşleştirme bilgisi (yalnızca açık anahtarlar ve adres) ve sıra numarası.
@MainActor
final class DefaultsStorage: ControllerStorage {
    private let defaults = UserDefaults.standard

    var pairedEngine: PairedEngine? {
        get {
            guard let data = defaults.data(forKey: "ati.paired") else { return nil }
            return try? JSONDecoder().decode(PairedEngine.self, from: data)
        }
        set {
            if let newValue, let data = try? JSONEncoder().encode(newValue) {
                defaults.set(data, forKey: "ati.paired")
            } else {
                defaults.removeObject(forKey: "ati.paired")
            }
        }
    }

    var lastSeq: Int64 {
        get { Int64(defaults.integer(forKey: "ati.lastSeq")) }
        set { defaults.set(Int(newValue), forKey: "ati.lastSeq") }
    }
}
