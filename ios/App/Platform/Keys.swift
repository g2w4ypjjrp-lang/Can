import ATICore
import CryptoKit
import Foundation
import LocalAuthentication
import Security

/// Anahtar Zinciri (yalnızca bu cihaz, kilit açıkken erişilebilir).
enum Keychain {
    static let service = "com.aitradingintelligence.ios"

    static func save(_ account: String, data: Data) throws {
        delete(account)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    static func load(_ account: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    static func delete(_ account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

/// Secure Enclave anahtarıyla imza. Anahtar cihazdan hiçbir zaman çıkmaz.
struct EnclaveSigner: DeviceSigner, @unchecked Sendable {
    let key: SecureEnclave.P256.Signing.PrivateKey
    var publicKeyX963: Data { key.publicKey.x963Representation }
    func signature(for data: Data) throws -> Data { try key.signature(for: data).rawRepresentation }
}

/// Telefon anahtarları Secure Enclave'de. Korumalı anahtar `.biometryCurrentSet` erişim
/// denetimiyle üretilir: Face ID/Touch ID olmadan imza atamaz (yeni parmak izi/yüz eklenirse
/// geçersiz olur ve yeniden eşleştirme gerekir).
final class EnclaveKeyProvider: KeyProvider, @unchecked Sendable {
    private let signingAccount = "ati.device.signing.se"
    private let guardedAccount = "ati.device.guarded.se"

    static var isAvailable: Bool { SecureEnclave.isAvailable }
    var protection: String { "secure_enclave" }

    func signingKey() throws -> DeviceSigner {
        EnclaveSigner(key: try loadOrCreate(signingAccount, biometric: false, context: nil))
    }

    func guardedPublicKey() throws -> Data {
        try loadOrCreate(guardedAccount, biometric: true, context: nil).publicKey.x963Representation
    }

    func guardedSigner(reason: String) async throws -> DeviceSigner {
        let context = LAContext()
        context.localizedCancelTitle = "Vazgeç"
        _ = try await context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason)
        return EnclaveSigner(key: try loadOrCreate(guardedAccount, biometric: true, context: context))
    }

    func reset() throws {
        Keychain.delete(signingAccount)
        Keychain.delete(guardedAccount)
    }

    private func loadOrCreate(
        _ account: String, biometric: Bool, context: LAContext?
    ) throws -> SecureEnclave.P256.Signing.PrivateKey {
        if let data = Keychain.load(account) {
            return try SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: data, authenticationContext: context)
        }
        var error: Unmanaged<CFError>?
        let flags: SecAccessControlCreateFlags = biometric ? [.privateKeyUsage, .biometryCurrentSet] : [.privateKeyUsage]
        guard
            let access = SecAccessControlCreateWithFlags(
                nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, flags, &error)
        else {
            throw error.map { $0.takeRetainedValue() as Error } ?? ProtocolError.signerFailed("erişim denetimi")
        }
        let key = try SecureEnclave.P256.Signing.PrivateKey(
            compactRepresentable: false, accessControl: access, authenticationContext: context)
        try Keychain.save(account, data: key.dataRepresentation)
        return key
    }
}

/// Secure Enclave olmayan ortam (simülatör): yazılım anahtarları Anahtar Zinciri'nde. Motora
/// "software" olarak bildirilir ve masaüstünde uyarıyla gösterilir.
final class KeychainSoftwareKeyProvider: KeyProvider, @unchecked Sendable {
    private let signingAccount = "ati.device.signing.sw"
    private let guardedAccount = "ati.device.guarded.sw"
    var protection: String { "software" }

    func signingKey() throws -> DeviceSigner { try load(signingAccount) }
    func guardedPublicKey() throws -> Data { try load(guardedAccount).publicKeyX963 }

    func guardedSigner(reason: String) async throws -> DeviceSigner {
        let context = LAContext()
        var error: NSError?
        if context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) {
            _ = try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)
        }
        return try load(guardedAccount)
    }

    func reset() throws {
        Keychain.delete(signingAccount)
        Keychain.delete(guardedAccount)
    }

    private func load(_ account: String) throws -> SoftwareSigner {
        if let raw = Keychain.load(account) { return try SoftwareSigner(rawRepresentation: raw) }
        let signer = SoftwareSigner()
        try Keychain.save(account, data: signer.rawRepresentation)
        return signer
    }
}
