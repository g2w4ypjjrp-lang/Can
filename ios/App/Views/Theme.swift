import ATICore
import SwiftUI

enum Theme {
    static let accent = Color(red: 0.94, green: 0.73, blue: 0.04)
    static let up = Color(red: 0.09, green: 0.78, blue: 0.52)
    static let down = Color(red: 0.92, green: 0.22, blue: 0.26)
}

enum Fmt {
    static func number(_ text: String?, digits: Int = 2) -> String {
        guard let text, let value = Double(text) else { return "—" }
        return number(value, digits: digits)
    }

    static func number(_ value: Double, digits: Int = 2) -> String {
        value.formatted(.number.precision(.fractionLength(0...digits)).locale(Locale(identifier: "tr_TR")))
    }

    static func time(_ ms: Int64) -> String {
        Date(timeIntervalSince1970: Double(ms) / 1000).formatted(date: .abbreviated, time: .shortened)
    }

    static func stateText(_ state: String) -> String {
        switch state {
        case "running": return "Çalışıyor"
        case "safe_mode": return "Güvenli mod"
        case "halted": return "Acil durdurma"
        case "starting": return "Başlıyor"
        default: return state
        }
    }

    static func modeText(_ mode: String) -> String {
        switch mode {
        case "paper": return "Sanal işlem"
        case "testnet": return "Test ağı"
        case "live": return "Gerçek hesap"
        default: return mode
        }
    }

    static func market(_ market: String) -> String { market == "spot" ? "Spot" : "Futures" }
}

struct ConnectionBadge: View {
    @Environment(RemoteController.self) private var controller

    var body: some View {
        let (text, color): (String, Color) = {
            switch controller.status {
            case .connected:
                return controller.session?.engineOnline == true ? ("Bağlı", Theme.up) : ("Bilgisayar çevrim dışı", .orange)
            case .connecting: return ("Bağlanıyor…", .orange)
            case .failed: return ("Bağlantı yok", Theme.down)
            case .idle: return ("Bağlı değil", .gray)
            }
        }()
        Label(text, systemImage: "circle.fill")
            .font(.caption)
            .foregroundStyle(color)
            .accessibilityIdentifier("connection")
    }
}

struct BannerView: View {
    @Environment(RemoteController.self) private var controller

    var body: some View {
        if let banner = controller.banner {
            Text(banner)
                .font(.callout)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
                .accessibilityIdentifier("banner")
                .onTapGesture { controller.clearBanner() }
        }
    }
}

struct Disclaimer: View {
    var body: some View {
        Text("Yatırım tavsiyesi değildir; kazanç garantisi yoktur. Gerçek hesapla işlem kullanıcı onayı olmadan açılmaz.")
            .font(.caption2)
            .foregroundStyle(.secondary)
    }
}
