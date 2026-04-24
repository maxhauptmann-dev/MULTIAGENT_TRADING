import Foundation
import Foundation
import SwiftUI
import Combine
// MARK: - Data Models

struct APIResponse<T: Codable>: Codable {
    let status: String
    let timestamp: String
    let data: T
}

struct Position: Codable, Identifiable {
    let id: UUID = UUID()
    let symbol: String
    let direction: String  // "long" or "short"
    let entry_price: Double
    let quantity: Double
    let current_price: Double
    let pnl_dollar: Double
    let pnl_percent: Double
    let stop_loss: Double?
    let take_profit: Double?
    let opened_at: String
    let highest_price: Double?
    let lowest_price: Double?
    let atr_14: Double?
    let kelly_fraction: Double?

    var pnlColor: Color {
        pnl_dollar >= 0 ? .green : .red
    }

    var directionLabel: String {
        direction.uppercased()
    }
}

struct PositionsResponse: Codable {
    let positions: [Position]
}

struct MarketRegime: Codable {
    let regime: String  // "bull", "bear", "neutral"
    let spy_vs_ema20_pct: Double
    let qqq_vs_ema20_pct: Double
    let vix: Double

    var regimeColor: Color {
        switch regime {
        case "bull": return .green
        case "bear": return .red
        default: return .gray
        }
    }
}

struct MarketRegimeResponse: Codable {
    let regime: String
    let spy_vs_ema20_pct: Double
    let qqq_vs_ema20_pct: Double
    let vix: Double
}

struct Trade: Codable, Identifiable {
    let id: UUID = UUID()
    let symbol: String
    let direction: String
    let entry_price: Double?
    let quantity: Double
    let opened_at: String
    let closed_at: String?
    let close_price: Double?
    let pnl: Double?
    let reason: String

    var isOpen: Bool {
        closed_at == nil
    }

    var pnlColor: Color {
        guard let pnl = pnl else { return .gray }
        return pnl >= 0 ? .green : .red
    }
}

struct TradesResponse: Codable {
    let trades: [Trade]
}

struct ScannerStatus: Codable {
    let last_scan: String?
    let trades_opened_today: Int
    let status: String
}

struct ScannerStatusResponse: Codable {
    let last_scan: String?
    let trades_opened_today: Int
    let status: String
}

struct LogsResponse: Codable {
    let logs: [String]
}

// MARK: - API Client

class TradingBotAPI: NSObject, ObservableObject {
    @Published var positions: [Position] = []
    @Published var marketRegime: MarketRegime?
    @Published var tradestoday: [Trade] = []
    @Published var scannerStatus: ScannerStatus?
    @Published var logs: [String] = []
    @Published var isConnected: Bool = false
    @Published var errorMessage: String?

    private var vpsIP: String
    private var vpsPort: Int
    private let refreshInterval: TimeInterval
    private var refreshTimer: Timer?

    init(vpsIP: String = "localhost", vpsPort: Int = 5000, refreshInterval: TimeInterval = 60) {
        self.vpsIP = vpsIP
        self.vpsPort = vpsPort
        self.refreshInterval = refreshInterval
        super.init()

        // Test connection on init
        testConnection()
    }

    func setVPSAddress(ip: String, port: Int) {
        self.vpsIP = ip
        self.vpsPort = port
    }

    private var baseURL: String {
        "http://\(vpsIP):\(vpsPort)"
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
        let url = URL(string: "\(baseURL)/api/health")!
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)

        print("Testing connection to: \(url.absoluteString)")

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    let nsError = error as NSError
                    let errorMsg = "Error: \(nsError.domain) [\(nsError.code)] - \(error.localizedDescription)"
                    print(errorMsg)
                    self?.isConnected = false
                    self?.errorMessage = errorMsg
                    return
                }

                if let httpResponse = response as? HTTPURLResponse {
                    self?.isConnected = (httpResponse.statusCode == 200)
                    if httpResponse.statusCode == 200 {
                        print("✓ Connected to API")
                    } else {
                        print("API returned status \(httpResponse.statusCode)")
                        self?.errorMessage = "API returned status \(httpResponse.statusCode)"
                    }
                } else {
                    self?.isConnected = false
                    self?.errorMessage = "No response from API"
                }
            }
        }.resume()
    }

    func fetchAll() {
        testConnection()
        fetchPositions()
        fetchMarketRegime()
        fetchTradesToday()
        fetchScannerStatus()
        fetchLogs()
    }

    func fetchPositions() {
        fetch(endpoint: "/api/positions") { (response: APIResponse<PositionsResponse>) in
            DispatchQueue.main.async {
                self.positions = response.data.positions
                self.errorMessage = nil
            }
        }
    }

    func fetchMarketRegime() {
        fetch(endpoint: "/api/market-regime") { (response: APIResponse<MarketRegimeResponse>) in
            DispatchQueue.main.async {
                self.marketRegime = MarketRegime(
                    regime: response.data.regime,
                    spy_vs_ema20_pct: response.data.spy_vs_ema20_pct,
                    qqq_vs_ema20_pct: response.data.qqq_vs_ema20_pct,
                    vix: response.data.vix
                )
                self.errorMessage = nil
            }
        }
    }

    func fetchTradesToday() {
        fetch(endpoint: "/api/trades-today") { (response: APIResponse<TradesResponse>) in
            DispatchQueue.main.async {
                self.tradestoday = response.data.trades
                self.errorMessage = nil
            }
        }
    }

    func fetchScannerStatus() {
        fetch(endpoint: "/api/scanner-status") { (response: APIResponse<ScannerStatusResponse>) in
            DispatchQueue.main.async {
                self.scannerStatus = ScannerStatus(
                    last_scan: response.data.last_scan,
                    trades_opened_today: response.data.trades_opened_today,
                    status: response.data.status
                )
                self.errorMessage = nil
            }
        }
    }

    func fetchLogs() {
        fetch(endpoint: "/api/logs/tail") { (response: APIResponse<LogsResponse>) in
            DispatchQueue.main.async {
                self.logs = response.data.logs
                self.errorMessage = nil
            }
        }
    }

    func triggerManualScan() {
        let url = URL(string: "\(baseURL)/api/trigger-scan")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            DispatchQueue.main.async {
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                    self?.errorMessage = "Scan triggered (results in 30-60s)"
                } else {
                    self?.errorMessage = error?.localizedDescription ?? "Failed to trigger scan"
                }
            }
        }.resume()
    }

    // MARK: - Private Helper

    private func fetch<T: Codable>(endpoint: String, completion: @escaping (T) -> Void) {
        let url = URL(string: "\(baseURL)\(endpoint)")!
        let request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let data = data, error == nil else {
                DispatchQueue.main.async {
                    self?.errorMessage = error?.localizedDescription ?? "Network error"
                }
                return
            }

            do {
                let decoded = try JSONDecoder().decode(T.self, from: data)
                completion(decoded)
            } catch {
                DispatchQueue.main.async {
                    self?.errorMessage = "Decode error: \(error.localizedDescription)"
                }
            }
        }.resume()
    }
}
