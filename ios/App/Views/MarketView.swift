import ATICore
import SwiftUI

struct MarketView: View {
    @Environment(RemoteController.self) private var controller

    var body: some View {
        NavigationStack {
            List {
                let data = controller.session?.snapshot?.data
                Section("Fırsatlar (AI destekli açıklanabilir puan)") {
                    let items = data?.opportunities ?? []
                    if items.isEmpty { Text("Eşik üstü fırsat yok").foregroundStyle(.secondary) }
                    ForEach(items) { item in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(item.symbol).bold()
                                Text(Fmt.market(item.market)).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(item.direction == "long" ? "Long" : "Short")
                                .foregroundStyle(item.direction == "long" ? Theme.up : Theme.down)
                            Text("\(item.score)").bold().frame(minWidth: 32)
                            if let rr = item.reward_risk { Text("R/R \(Fmt.number(rr))").font(.caption) }
                        }
                        .accessibilityIdentifier("opportunity-\(item.symbol)")
                    }
                }
                Section("Balina hareketleri") {
                    let whales = data?.whales ?? []
                    if whales.isEmpty { Text("Uyarı yok").foregroundStyle(.secondary) }
                    ForEach(whales) { whale in
                        VStack(alignment: .leading) {
                            Text(whale.message)
                            Text(Fmt.time(whale.ts_ms)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Section { Disclaimer() }
            }
            .navigationTitle("Sinyaller")
            .refreshable { await controller.send(.requestSnapshot) }
        }
    }
}
