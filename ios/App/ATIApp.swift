import ATICore
import SwiftUI
import UserNotifications

@main
struct ATIApp: App {
    @State private var controller: RemoteController
    private let mockEngine: MockEngine?

    init() {
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("-UITestMockEngine") {
            // Arayüz testleri: bellek içi motor + aktarma benzetimi (gerçek imza kurallarıyla).
            let engine = MockEngine()
            mockEngine = engine
            _controller = State(
                initialValue: RemoteController(
                    transport: { engine }, keys: SoftwareKeyProvider(), storage: MemoryStorage()))
        } else {
            mockEngine = nil
            let keys: KeyProvider = EnclaveKeyProvider.isAvailable ? EnclaveKeyProvider() : KeychainSoftwareKeyProvider()
            _controller = State(
                initialValue: RemoteController(
                    transport: { WebSocketTransport() }, keys: keys, storage: DefaultsStorage()))
        }
    }

    var body: some Scene {
        WindowGroup {
            RootView(mockEngine: mockEngine)
                .environment(controller)
                .task { await controller.start() }
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
        }
    }
}

struct RootView: View {
    @Environment(RemoteController.self) private var controller
    let mockEngine: MockEngine?

    var body: some View {
        if controller.paired == nil {
            PairingView(mockEngine: mockEngine)
        } else {
            MainTabs(mockEngine: mockEngine)
        }
    }
}

struct MainTabs: View {
    @Environment(RemoteController.self) private var controller
    @Environment(\.scenePhase) private var scenePhase
    let mockEngine: MockEngine?
    @State private var notified: Set<String> = []

    var body: some View {
        TabView {
            DashboardView().tabItem { Label("Özet", systemImage: "gauge.with.dots.needle.50percent") }
            PositionsView().tabItem { Label("Pozisyonlar", systemImage: "list.bullet.rectangle") }
            MarketView().tabItem { Label("Sinyaller", systemImage: "waveform.path.ecg") }
            NotificationsView().tabItem { Label("Bildirimler", systemImage: "bell") }
            SettingsView(mockEngine: mockEngine).tabItem { Label("Ayarlar", systemImage: "gearshape") }
        }
        .task {
            _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
        }
        .onChange(of: controller.session?.events.first?.id) { _, _ in
            postLocalNotifications()
        }
    }

    /// Uygulama arka plandayken yeni olayları yerel bildirim olarak gösterir. Uygulama kapalıyken
    /// gelen anlık bildirimler (APNs) bulut dağıtımı ve Apple Developer hesabıyla eklenecek.
    private func postLocalNotifications() {
        guard scenePhase != .active, let events = controller.session?.events else { return }
        for event in events.prefix(5) where !notified.contains(event.id) {
            notified.insert(event.id)
            let content = UNMutableNotificationContent()
            content.title = event.title
            content.body = event.body
            UNUserNotificationCenter.current().add(
                UNNotificationRequest(identifier: event.id, content: content, trigger: nil))
        }
    }
}
