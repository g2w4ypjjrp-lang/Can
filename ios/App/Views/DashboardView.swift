import ATICore
import SwiftUI

struct DashboardView: View {
    @Environment(RemoteController.self) private var controller
    @State private var confirmKill = false
    @State private var confirmRelease = false
    @State private var confirmResume = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    BannerView()
                    HStack {
                        ConnectionBadge()
                        Spacer()
                        if let age = controller.session?.snapshotAge(), age > 60 {
                            Text("\(age) sn önce").font(.caption).foregroundStyle(.orange)
                        }
                    }
                }
                if let data = controller.session?.snapshot?.data {
                    engineSection(data)
                    killSection(data.engine)
                    botSection(data.autotrade)
                    if let paper = data.paper {
                        Section("Sanal işlem yarışması") {
                            LabeledContent("Hesap", value: "\(paper.accounts)")
                            LabeledContent("Açık pozisyon", value: "\(paper.open_positions)")
                            LabeledContent("Kapanmış işlem", value: "\(paper.trades)")
                            LabeledContent("Net K/Z (sanal)", value: Fmt.number(paper.net_pnl) + " USDT")
                        }
                    }
                } else {
                    Section { Text("Bilgisayardan durum bekleniyor…").foregroundStyle(.secondary) }
                }
                Section { Disclaimer() }
            }
            .navigationTitle(controller.paired?.engineName ?? "Özet")
            .refreshable { await controller.send(.requestSnapshot) }
            .alert("Acil durdurma", isPresented: $confirmKill) {
                Button("Vazgeç", role: .cancel) {}
                Button("Durdur", role: .destructive) { Task { await controller.send(.engageKillSwitch, args: ["reason": "telefondan acil durdurma"]) } }
            } message: {
                Text("Yeni işlem açılması hemen durdurulacak. Borsadaki stoplar yerinde kalır.")
            }
            .alert("Acil durdurmayı kaldır", isPresented: $confirmRelease) {
                Button("Vazgeç", role: .cancel) {}
                Button("Kaldır (Face ID)") { Task { await controller.send(.releaseKillSwitch) } }
            } message: {
                Text("Motor güvenlik koşulları sağlanınca yeniden işlem açabilir.")
            }
            .alert("Botu başlat", isPresented: $confirmResume) {
                Button("Vazgeç", role: .cancel) {}
                Button("Başlat (Face ID)") { Task { await controller.send(.resumeAutotrade) } }
            } message: {
                Text("Otomatik işlem yalnızca test ağında ve risk kapısından geçerek çalışır.")
            }
        }
    }

    @ViewBuilder
    private func engineSection(_ data: SnapshotData) -> some View {
        Section("Motor") {
            ValueRow(
                title: "Durum", value: Fmt.stateText(data.engine.state), id: "engine-state",
                color: data.engine.state == "running" ? Theme.up : Theme.down)
            LabeledContent("İşlem modu", value: Fmt.modeText(data.engine.trading_mode))
            if let risk = data.risk {
                LabeledContent("Günlük zarar", value: "%" + Fmt.number(risk.daily_loss_pct))
                LabeledContent("Özsermaye", value: Fmt.number(risk.equity) + " USDT")
                if risk.halted { Text("Günlük zarar sınırı: bugün yeni işlem açılmaz").foregroundStyle(Theme.down) }
            }
        }
    }

    @ViewBuilder
    private func killSection(_ engine: EngineSummary) -> some View {
        Section {
            if engine.kill_switch {
                Text("Acil durdurma devrede" + (engine.kill_reason.map { ": \($0)" } ?? ""))
                    .foregroundStyle(Theme.down)
                Button("Acil durdurmayı kaldır") { confirmRelease = true }
                    .accessibilityIdentifier("kill-release")
            } else {
                Button {
                    confirmKill = true
                } label: {
                    Text("ACİL DURDUR").font(.title3.bold()).frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.down)
                .accessibilityIdentifier("kill-switch")
            }
        } footer: {
            Text("Acil durdurma her zaman tek dokunuştur. Kaldırmak Face ID ister.")
        }
    }

    @ViewBuilder
    private func botSection(_ auto: AutotradeSummary?) -> some View {
        if let auto {
            Section("Otomatik işlem (test ağı)") {
                ValueRow(title: "Durum", value: auto.enabled ? "Açık" : "Kapalı", id: "bot-state")
                LabeledContent("Açılan / risk reddi", value: "\(auto.opened) / \(auto.rejected)")
                if auto.enabled {
                    Button("Botu durdur") { Task { await controller.send(.pauseAutotrade) } }
                        .accessibilityIdentifier("bot-pause")
                } else {
                    Button("Botu başlat") { confirmResume = true }
                        .accessibilityIdentifier("bot-resume")
                }
            }
        }
    }
}
