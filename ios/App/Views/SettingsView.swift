import ATICore
import SwiftUI

struct SettingsView: View {
    @Environment(RemoteController.self) private var controller
    let mockEngine: MockEngine?
    @State private var confirmUnpair = false

    var body: some View {
        NavigationStack {
            List {
                if let paired = controller.paired {
                    Section("Eşleştirilen bilgisayar") {
                        LabeledContent("Ad", value: paired.engineName)
                        LabeledContent("Motor kimliği", value: String(paired.engineID.prefix(12)) + "…")
                        LabeledContent("Eşleşme", value: Fmt.time(paired.pairedAtMs))
                        LabeledContent("Aktarma servisi", value: paired.relay)
                        ConnectionBadge()
                    }
                }
                Section("Güvenlik") {
                    LabeledContent("Cihaz kimliği", value: String((controller.deviceID ?? "").prefix(12)) + "…")
                    ValueRow(title: "Doğrulanamayan mesaj", value: "\(controller.rejectedFrames)", id: "rejected-count")
                    Text("Bilgisayardan gelen her mesaj imzasından doğrulanır; doğrulanamayan mesajlar yok sayılır ve burada sayılır.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if let mockEngine {
                        Button("Sahte mesaj gönder (test)") { Task { await mockEngine.injectForgedSnapshot() } }
                            .accessibilityIdentifier("inject-forgery")
                    }
                }
                Section("Hesap ve lisans") {
                    Text("Lisans, bilgisayardaki masaüstü uygulamasında etkinleştirilir. Hesap girişi ve lisans durumu, bulut hesabı (Aşama 15) ile bu ekrana eklenecek.")
                        .font(.footnote)
                }
                Section {
                    Button("Eşleştirmeyi kaldır", role: .destructive) { confirmUnpair = true }
                        .accessibilityIdentifier("unpair")
                } footer: {
                    Text("Telefondaki anahtarlar silinir. Bilgisayarda da Ayarlar → Telefon bölümünden eşleştirmeyi kaldırın.")
                }
                Section { Disclaimer() }
            }
            .navigationTitle("Ayarlar")
            .alert("Eşleştirme kaldırılsın mı?", isPresented: $confirmUnpair) {
                Button("Vazgeç", role: .cancel) {}
                Button("Kaldır", role: .destructive) { Task { await controller.unpair() } }
            }
        }
    }
}
