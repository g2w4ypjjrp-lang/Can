import ATICore
import Foundation

/// Aktarma servisine WebSocket bağlantısı (URLSession).
final class WebSocketTransport: FrameTransport, @unchecked Sendable {
    private let session = URLSession(configuration: .default)
    private let lock = NSLock()
    private var task: URLSessionWebSocketTask?

    private var current: URLSessionWebSocketTask? { lock.withLock { task } }

    func connect(to url: URL) async throws {
        let socket = session.webSocketTask(with: url)
        socket.maximumMessageSize = 256 * 1024
        lock.withLock { task = socket }
        socket.resume()
    }

    func send(_ text: String) async throws {
        guard let socket = current else { throw URLError(.networkConnectionLost) }
        try await socket.send(.string(text))
    }

    func receive() async throws -> String {
        guard let socket = current else { throw URLError(.networkConnectionLost) }
        switch try await socket.receive() {
        case .string(let text): return text
        case .data(let data): return String(decoding: data, as: UTF8.self)
        @unknown default: throw URLError(.cannotParseResponse)
        }
    }

    func close() async {
        let socket = lock.withLock { () -> URLSessionWebSocketTask? in
            defer { task = nil }
            return task
        }
        socket?.cancel(with: .goingAway, reason: nil)
    }
}
