import ATICore
import SwiftUI
import UIKit

struct PairingView: View {
    @Environment(RemoteController.self) private var controller
    let mockEngine: MockEngine?
    @State private var codeText = ""
    @State private var scanning = false
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Bilgisayarınızdaki AI Trading Intelligence uygulamasında **Ayarlar → Telefon (iOS) eşleştirme → Yeni telefon eşleştir** adımını açın ve QR kodu okutun.")
                    Text("Telefonunuz güvenli donanımında bir anahtar üretir. Her komut bu anahtarla imzalanır; bilgisayar imzayı doğrulamadan hiçbir komutu uygulamaz.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section {
                    Button {
                        scanning = true
                    } label: {
                        Label("QR kodu tara", systemImage: "qrcode.viewfinder")
                    }
                    .accessibilityIdentifier("scan-button")
                }
                Section("Veya kodu yapıştırın") {
                    TextField("Eşleştirme kodu", text: $codeText, axis: .vertical)
                        .lineLimit(3...6)
                        .font(.footnote.monospaced())
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .accessibilityIdentifier("code-field")
                    if let mockEngine {
                        Button("Test kodunu kullan") { codeText = mockEngine.pairingCode }
                            .accessibilityIdentifier("use-test-code")
                    }
                    Button {
                        Task { await pair(codeText) }
                    } label: {
                        if working { ProgressView() } else { Text("Eşleştir").bold() }
                    }
                    .disabled(codeText.isEmpty || working)
                    .accessibilityIdentifier("pair-button")
                }
                if let error {
                    Section {
                        Text(error).foregroundStyle(Theme.down).accessibilityIdentifier("pair-error")
                    }
                }
                Section { Disclaimer() }
            }
            .navigationTitle("Bilgisayarı eşleştir")
            .sheet(isPresented: $scanning) {
                QRScannerView { text in
                    scanning = false
                    Task { await pair(text) }
                }
                .ignoresSafeArea()
            }
        }
    }

    private func pair(_ text: String) async {
        working = true
        error = nil
        defer { working = false }
        do {
            try await controller.pair(code: text.trimmingCharacters(in: .whitespacesAndNewlines), deviceName: UIDevice.current.name)
        } catch let protocolError as ProtocolError {
            if case .invalidPairingCode(let message) = protocolError { error = message } else { error = "Kod geçersiz" }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
