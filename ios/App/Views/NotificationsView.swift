import ATICore
import SwiftUI

struct NotificationsView: View {
    @Environment(RemoteController.self) private var controller

    var body: some View {
        NavigationStack {
            List {
                let events = controller.session?.events ?? []
                if events.isEmpty { Text("Bildirim yok").foregroundStyle(.secondary) }
                ForEach(events) { event in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.title).bold()
                        Text(event.body)
                        Text(Fmt.time(event.ts_ms)).font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityIdentifier("event-\(event.kind)")
                }
            }
            .navigationTitle("Bildirimler")
        }
    }
}
