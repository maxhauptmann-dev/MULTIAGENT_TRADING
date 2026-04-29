import Foundation
import Security

class KeychainManager {
    static let shared = KeychainManager()

    private let serviceName = "com.trading.alpaca"

    // MARK: - Save Credentials
    func saveAlpacaCredentials(apiKey: String, apiSecret: String) -> Bool {
        // Delete old credentials first
        deleteAlpacaCredentials()

        // Save API Key
        let keyQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: "alpaca_api_key",
            kSecValueData as String: apiKey.data(using: .utf8) ?? Data()
        ]

        let keyStatus = SecItemAdd(keyQuery as CFDictionary, nil)
        guard keyStatus == errSecSuccess else {
            print("❌ Failed to save API Key: \(keyStatus)")
            return false
        }

        // Save API Secret
        let secretQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: "alpaca_api_secret",
            kSecValueData as String: apiSecret.data(using: .utf8) ?? Data()
        ]

        let secretStatus = SecItemAdd(secretQuery as CFDictionary, nil)
        guard secretStatus == errSecSuccess else {
            print("❌ Failed to save API Secret: \(secretStatus)")
            return false
        }

        print("✅ Alpaca credentials saved to Keychain")
        return true
    }

    // MARK: - Load Credentials
    func loadAlpacaCredentials() -> (apiKey: String, apiSecret: String)? {
        guard let apiKey = retrieveCredential(account: "alpaca_api_key"),
              let apiSecret = retrieveCredential(account: "alpaca_api_secret") else {
            return nil
        }

        return (apiKey, apiSecret)
    }

    // MARK: - Delete Credentials
    func deleteAlpacaCredentials() {
        let keyQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: "alpaca_api_key"
        ]
        SecItemDelete(keyQuery as CFDictionary)

        let secretQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: "alpaca_api_secret"
        ]
        SecItemDelete(secretQuery as CFDictionary)

        print("✅ Alpaca credentials deleted from Keychain")
    }

    // MARK: - Helper
    private func retrieveCredential(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: serviceName,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let credential = String(data: data, encoding: .utf8) else {
            return nil
        }

        return credential
    }

    // MARK: - Check if Credentials Exist
    func hasAlpacaCredentials() -> Bool {
        return loadAlpacaCredentials() != nil
    }
}
