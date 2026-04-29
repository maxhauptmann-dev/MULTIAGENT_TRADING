import Foundation
import SwiftUI
import Combine

// MARK: - Data Models

struct APIResponse<T: Codable>: Codable, Sendable {
    let status: String
    let timestamp: String
    let data: T
}

// Alpaca Account Info
struct AlpacaAccount: Codable, Sendable {
    let account_number: String
    let portfolio_value: Double
    let cash: Double
    let buying_power: Double
    let equity: Double

    enum CodingKeys: String, CodingKey {
        case account_number
        case portfolio_value
        case cash
        case buying_power
        case equity
    }
}

// Portfolio History Response
struct PortfolioHistoryResponse: Codable {
    let timestamp: [TimeInterval]
    let equity: [Double]
    let profit_loss: [Double]
    let profit_loss_pct: [Double]
    let base_value: Double
    let timeframe: String
}

// Portfolio History Point
struct PortfolioHistoryPoint: Identifiable, Sendable {
    let id = UUID()
    let date: Date
    let equity: Double
    let profitLoss: Double
    let profitLossPct: Double
}

// Alpaca Position
struct AlpacaPosition: Identifiable, Sendable {
    let symbol: String
    let qty: Double
    let avg_entry_price: Double
    let current_price: Double
    let unrealized_pl: Double
    let unrealized_plpc: Double

    var id: String { symbol }

    var directionLabel: String {
        qty > 0 ? "LONG" : "SHORT"
    }

    var direction: String {
        qty > 0 ? "long" : "short"
    }

    enum CodingKeys: String, CodingKey {
        case symbol
        case qty
        case avg_entry_price
        case current_price
        case unrealized_pl
        case unrealized_plpc
    }
}

extension AlpacaPosition: Decodable {
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        symbol = try container.decode(String.self, forKey: .symbol)
        qty = Double(try container.decode(String.self, forKey: .qty)) ?? 0
        avg_entry_price = Double(try container.decode(String.self, forKey: .avg_entry_price)) ?? 0
        current_price = Double(try container.decode(String.self, forKey: .current_price)) ?? 0
        unrealized_pl = Double(try container.decode(String.self, forKey: .unrealized_pl)) ?? 0
        unrealized_plpc = Double(try container.decode(String.self, forKey: .unrealized_plpc)) ?? 0
    }
}

// Alpaca Order (for trades)
struct AlpacaOrder: Codable, Identifiable, Sendable {
    let id: String
    let symbol: String
    let qty: Double
    let side: String
    let filled_at: String?
    let filled_avg_price: Double?
    let status: String
    let created_at: String

    var isOpen: Bool {
        status == "pending_new" || status == "pending_cancel" || status == "pending_replace"
    }

    var isClosed: Bool {
        status == "filled" || status == "canceled" || status == "expired" || status == "rejected"
    }

    enum CodingKeys: String, CodingKey {
        case id
        case symbol
        case qty
        case side
        case filled_at
        case filled_avg_price
        case status
        case created_at
    }
}

// MARK: - API Client

class TradingBotAPI: NSObject, ObservableObject, URLSessionDelegate {
    @Published var account: AlpacaAccount?
    @Published var positions: [AlpacaPosition] = []
    @Published var trades: [AlpacaOrder] = []
    @Published var historicalOrders: [AlpacaOrder] = []
    @Published var portfolioHistory: [PortfolioHistoryPoint] = []
    @Published var isConnected: Bool = false
    @Published var errorMessage: String?
    @Published var needsCredentials: Bool = false

    private let alpacaBaseURL = "https://paper-api.alpaca.markets"
    private let refreshInterval: TimeInterval = 60
    private var refreshTimer: Timer?
    private var session: URLSession!

    private var alpacaKey: String?
    private var alpacaSecret: String?

    override init() {
        super.init()

        // Configure URLSession
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 20
        config.timeoutIntervalForResource = 60

        self.session = URLSession(configuration: config, delegate: self, delegateQueue: .main)

        // Load credentials from Keychain
        loadCredentials()
    }

    // MARK: - Credential Management

    func loadCredentials() {
        if let (key, secret) = KeychainManager.shared.loadAlpacaCredentials() {
            self.alpacaKey = key
            self.alpacaSecret = secret
            self.needsCredentials = false
            print("✅ Credentials loaded from Keychain")
            testConnection()
        } else {
            self.needsCredentials = true
            self.isConnected = false
            print("⚠️  No Alpaca credentials in Keychain")
        }
    }

    func setAlpacaCredentials(apiKey: String, apiSecret: String) {
        if KeychainManager.shared.saveAlpacaCredentials(apiKey: apiKey, apiSecret: apiSecret) {
            self.alpacaKey = apiKey
            self.alpacaSecret = apiSecret
            self.needsCredentials = false
            testConnection()
        } else {
            self.errorMessage = "Failed to save credentials to Keychain"
        }
    }

    // MARK: - Public Methods

    func startRefreshTimer() {
        refreshTimer = Timer.scheduledTimer(withTimeInterval: refreshInterval, repeats: true) { [weak self] _ in
            self?.fetchAll()
        }
        // Fetch immediately
        fetchAll()
    }

    func stopRefreshTimer() {
        refreshTimer?.invalidate()
        refreshTimer = nil
    }

    func testConnection() {
        guard let key = alpacaKey, let secret = alpacaSecret else {
            self.isConnected = false
            self.needsCredentials = true
            return
        }

        let url = URL(string: "\(alpacaBaseURL)/v2/account")!
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        print("Testing connection to Alpaca API...")

        self.session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    print("❌ Connection error: \(error.localizedDescription)")
                    self?.isConnected = false
                    self?.errorMessage = "Connection error: \(error.localizedDescription)"
                    return
                }

                if let httpResponse = response as? HTTPURLResponse {
                    if httpResponse.statusCode == 200 {
                        print("✅ Connected to Alpaca API")
                        self?.isConnected = true
                        self?.errorMessage = nil
                    } else if httpResponse.statusCode == 401 {
                        print("❌ Invalid Alpaca credentials (401)")
                        self?.isConnected = false
                        self?.errorMessage = "Invalid credentials. Please re-enter."
                        self?.needsCredentials = true
                    } else {
                        print("❌ Alpaca API returned status \(httpResponse.statusCode)")
                        self?.isConnected = false
                        self?.errorMessage = "API error: \(httpResponse.statusCode)"
                    }
                }
            }
        }.resume()
    }

    func fetchAll() {
        guard isConnected else { return }
        fetchAccount()
        fetchPositions()
        fetchTrades()
        fetchHistoricalOrders()
        fetchPortfolioHistory()
    }

    // MARK: - Alpaca Endpoints

    func fetchAccount() {
        guard let key = alpacaKey, let secret = alpacaSecret else { return }

        let url = URL(string: "\(alpacaBaseURL)/v2/account")!
        var request = URLRequest(url: url)
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.errorMessage = "Failed to fetch account: \(error.localizedDescription)"
                    return
                }

                guard let data = data else { return }

                do {
                    let account = try JSONDecoder().decode(AlpacaAccount.self, from: data)
                    self?.account = account
                    self?.errorMessage = nil
                } catch {
                    self?.errorMessage = "Failed to decode account data"
                    print("Decode error: \(error)")
                }
            }
        }.resume()
    }

    func fetchPositions() {
        guard let key = alpacaKey, let secret = alpacaSecret else { return }

        let url = URL(string: "\(alpacaBaseURL)/v2/positions")!
        var request = URLRequest(url: url)
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.errorMessage = "Failed to fetch positions: \(error.localizedDescription)"
                    return
                }

                guard let data = data else { return }

                do {
                    let positions = try JSONDecoder().decode([AlpacaPosition].self, from: data)
                    self?.positions = positions.sorted { $0.unrealized_pl > $1.unrealized_pl }
                    print("✅ Loaded \(positions.count) positions")
                    self?.errorMessage = nil
                } catch {
                    self?.errorMessage = "Failed to decode positions"
                    print("❌ Position decode error: \(error)")
                    if let data = String(data: data, encoding: .utf8) {
                        print("Response: \(data.prefix(500))")
                    }
                }
            }
        }.resume()
    }

    func fetchTrades() {
        guard let key = alpacaKey, let secret = alpacaSecret else { return }

        // Get today's date
        let todayStart = Calendar.current.startOfDay(for: Date())
        let dateFormatter = ISO8601DateFormatter()
        let todayISO = dateFormatter.string(from: todayStart)

        var urlComponents = URLComponents(string: "\(alpacaBaseURL)/v2/orders")!
        urlComponents.queryItems = [
            URLQueryItem(name: "status", value: "closed"),
            URLQueryItem(name: "limit", value: "20"),
            URLQueryItem(name: "after", value: todayISO)
        ]

        guard let url = urlComponents.url else { return }

        var request = URLRequest(url: url)
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.errorMessage = "Failed to fetch trades: \(error.localizedDescription)"
                    return
                }

                guard let data = data else { return }

                do {
                    let trades = try JSONDecoder().decode([AlpacaOrder].self, from: data)
                    self?.trades = trades.sorted {
                        let date1 = ISO8601DateFormatter().date(from: $0.created_at) ?? Date.distantPast
                        let date2 = ISO8601DateFormatter().date(from: $1.created_at) ?? Date.distantPast
                        return date1 > date2
                    }
                    self?.errorMessage = nil
                } catch {
                    self?.errorMessage = "Failed to decode trades"
                    print("Decode error: \(error)")
                }
            }
        }.resume()
    }

    func fetchHistoricalOrders() {
        guard let key = alpacaKey, let secret = alpacaSecret else { return }

        var urlComponents = URLComponents(string: "\(alpacaBaseURL)/v2/orders")!
        urlComponents.queryItems = [
            URLQueryItem(name: "status", value: "closed"),
            URLQueryItem(name: "limit", value: "100")
        ]

        guard let url = urlComponents.url else { return }

        var request = URLRequest(url: url)
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    print("Failed to fetch historical orders: \(error.localizedDescription)")
                    return
                }

                guard let data = data else { return }

                do {
                    let orders = try JSONDecoder().decode([AlpacaOrder].self, from: data)
                    self?.historicalOrders = orders
                    print("✅ Loaded \(orders.count) historical orders")
                } catch {
                    print("Failed to decode historical orders: \(error)")
                }
            }
        }.resume()
    }

    func fetchPortfolioHistory() {
        guard let key = alpacaKey, let secret = alpacaSecret else {
            print("⚠️ No credentials for portfolio history")
            return
        }

        var urlComponents = URLComponents(string: "\(alpacaBaseURL)/v2/account/portfolio/history")!
        urlComponents.queryItems = [
            URLQueryItem(name: "period", value: "1M"),
            URLQueryItem(name: "timeframe", value: "1D"),
            URLQueryItem(name: "intraday_reporting", value: "market_hours")
        ]

        guard let url = urlComponents.url else {
            print("⚠️ Invalid portfolio history URL")
            return
        }

        print("📊 Fetching portfolio history from: \(url.absoluteString)")

        var request = URLRequest(url: url)
        request.setValue(key, forHTTPHeaderField: "APCA-API-KEY-ID")
        request.setValue(secret, forHTTPHeaderField: "APCA-API-SECRET-KEY")

        session.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    print("❌ Failed to fetch portfolio history: \(error.localizedDescription)")
                    return
                }

                if let httpResponse = response as? HTTPURLResponse {
                    print("📊 Portfolio history response code: \(httpResponse.statusCode)")
                }

                guard let data = data else {
                    print("⚠️ No data in portfolio history response")
                    return
                }

                do {
                    let response = try JSONDecoder().decode(PortfolioHistoryResponse.self, from: data)
                    let history = zip(response.timestamp, response.equity).enumerated().map { index, values in
                        let (timestamp, equity) = values
                        let profitLoss = response.profit_loss[index]
                        let profitLossPct = response.profit_loss_pct[index]
                        return PortfolioHistoryPoint(
                            date: Date(timeIntervalSince1970: timestamp),
                            equity: equity,
                            profitLoss: profitLoss,
                            profitLossPct: profitLossPct
                        )
                    }
                    print("✅ Loaded portfolio history: \(history.count) data points")
                    self?.portfolioHistory = history
                } catch {
                    print("❌ Failed to decode portfolio history: \(error)")
                    if let data = String(data: data, encoding: .utf8) {
                        print("Response data: \(data.prefix(200))")
                    }
                }
            }
        }.resume()
    }

    // MARK: - URLSessionDelegate

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard let trust = challenge.protectionSpace.serverTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }
        let credential = URLCredential(trust: trust)
        completionHandler(.useCredential, credential)
    }
}
