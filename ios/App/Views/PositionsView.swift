import ATICore
import SwiftUI

struct PositionsView: View {
    @Environment(RemoteController.self) private var controller
    @State private var closing: PositionSummary?
    @State private var confirmAll = false

    var body: some View {
        NavigationStack {
            List {
                Section { BannerView() }
                let positions = controller.session?.snapshot?.data.positions ?? []
                if positions.isEmpty {
                    Text("Açık pozisyon yok").foregroundStyle(.secondary).accessibilityIdentifier("no-positions")
                }
                ForEach(positions) { position in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(position.symbol).bold()
                            Text(Fmt.market(position.market)).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            let qty = Double(position.quantity) ?? 0
                            Text(qty >= 0 ? "Long" : "Short").foregroundStyle(qty >= 0 ? Theme.up : Theme.down)
                        }
                        HStack {
                            Text("Miktar \(Fmt.number(position.quantity, digits: 4))")
                            Spacer()
                            Text("Giriş \(Fmt.number(position.entry_price, digits: 4))")
                        }
                        .font(.footnote)
                        HStack {
                            Text("Gerçekleşen K/Z \(Fmt.number(position.realized_pnl))")
                            Spacer()
                            if position.protected == true {
                                Label("Stop var", systemImage: "shield.lefthalf.filled").foregroundStyle(Theme.up)
                            } else {
                                Label("Stop yok", systemImage: "exclamationmark.shield").foregroundStyle(Theme.down)
                            }
                        }
                        .font(.caption)
                        Button("Kapat") { closing = position }
                            .buttonStyle(.bordered)
                            .accessibilityIdentifier("close-\(position.symbol)")
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("position-\(position.symbol)")
                }
                if !positions.isEmpty {
                    Button("Tümünü kapat", role: .destructive) { confirmAll = true }
                        .accessibilityIdentifier("close-all")
                }
                Section { Disclaimer() }
            }
            .navigationTitle("Pozisyonlar")
            .refreshable { await controller.send(.requestSnapshot) }
            .alert(
                "\(closing?.symbol ?? "") kapatılsın mı?",
                isPresented: Binding(get: { closing != nil }, set: { if !$0 { closing = nil } })
            ) {
                Button("Vazgeç", role: .cancel) { closing = nil }
                Button("Kapat (Face ID)", role: .destructive) {
                    if let position = closing {
                        Task { await controller.send(.closePosition, args: ["market": position.market, "symbol": position.symbol]) }
                    }
                    closing = nil
                }
            } message: {
                Text("Pozisyon piyasa fiyatından kapatılır, koruma emirleri iptal edilir.")
            }
            .alert("Tüm pozisyonlar kapatılsın mı?", isPresented: $confirmAll) {
                Button("Vazgeç", role: .cancel) {}
                Button("Tümünü kapat (Face ID)", role: .destructive) { Task { await controller.send(.closeAll) } }
            }
        }
    }
}
