import SwiftUI

struct ContentView: View {
    @StateObject private var api = TradingBotAPI()
    @State private var showSettings = false

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                // Header
                HStack {
                    VStack(alignment: .leading) {
                        Text("Trading Bot")
                            .font(.title2)
                            .fontWeight(.bold)
                        Text(api.isConnected ? "🟢 Connected" : "🔴 Disconnected")
                            .font(.caption)
                            .foregroundColor(api.isConnected ? .green : .red)
                    }

                    Spacer()

                    VStack(alignment: .trailing) {
                        Text(lastUpdateTime())
                            .font(.caption)
                            .foregroundColor(.gray)
                        Button(action: { showSettings = true }) {
                            Image(systemName: "gear")
                        }
                        .popover(isPresented: $showSettings) {
                            SettingsView(api: api)
                        }
                    }
                }
                .padding()
                .background(Color(.controlBackgroundColor))
                .cornerRadius(8)

                // Error banner
                if let error = api.errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding(8)
                        .background(Color.orange)
                        .cornerRadius(4)
                }

                // Market Regime
                if let regime = api.marketRegime {
                    MarketRegimeCard(regime: regime)
                }

                // Portfolio Stats
                PortfolioStatsView(positions: api.positions)

                // Positions Table
                PositionsTableView(positions: api.positions)

                // Trades Today
                TradesView(trades: api.tradestoday)

                // Scanner & Logs
                ScannerLogsView(status: api.scannerStatus, logs: api.logs, onScanTapped: {
                    api.triggerManualScan()
                })

                Spacer()
            }
            .padding()
            .navigationTitle("Trading Dashboard")
            .onAppear {
                api.startRefreshTimer()
            }
            .onDisappear {
                api.stopRefreshTimer()
            }
        }
    }

    private func lastUpdateTime() -> String {
        let now = Date()
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return "Updated: \(formatter.string(from: now))"
    }
}

// MARK: - Market Regime Card

struct MarketRegimeCard: View {
    let regime: MarketRegime

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(regime.regime.uppercased())
                .font(.headline)
                .fontWeight(.bold)
                .foregroundColor(.white)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(regime.regimeColor)
                .cornerRadius(8)

            HStack {
                VStack(alignment: .leading) {
                    Text("SPY vs EMA20")
                        .font(.caption)
                        .foregroundColor(.gray)
                    Text(String(format: "%.2f%%", regime.spy_vs_ema20_pct))
                        .font(.body)
                        .fontWeight(.semibold)
                }

                Spacer()

                VStack(alignment: .leading) {
                    Text("QQQ vs EMA20")
                        .font(.caption)
                        .foregroundColor(.gray)
                    Text(String(format: "%.2f%%", regime.qqq_vs_ema20_pct))
                        .font(.body)
                        .fontWeight(.semibold)
                }

                Spacer()

                VStack(alignment: .leading) {
                    Text("VIX")
                        .font(.caption)
                        .foregroundColor(.gray)
                    Text(String(format: "%.1f", regime.vix))
                        .font(.body)
                        .fontWeight(.semibold)
                }
            }
            .padding(8)
        }
        .padding()
        .background(Color(.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Portfolio Stats

struct PortfolioStatsView: View {
    let positions: [Position]

    var totalPnL: Double {
        positions.reduce(0) { $0 + $1.pnl_dollar }
    }

    var totalPnLPercent: Double {
        guard !positions.isEmpty else { return 0 }
        return positions.map { $0.pnl_percent }.reduce(0, +) / Double(positions.count)
    }

    var body: some View {
        HStack(spacing: 12) {
            StatCard(label: "Open Positions", value: String(positions.count), color: nil)
            StatCard(label: "Total P&L", value: String(format: "$%.2f", totalPnL), color: totalPnL >= 0 ? .green : .red)
            StatCard(label: "Avg P&L %", value: String(format: "%.2f%%", totalPnLPercent), color: totalPnLPercent >= 0 ? .green : .red)
        }
    }
}

struct StatCard: View {
    let label: String
    let value: String
    let color: Color?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundColor(.gray)
            Text(value)
                .font(.headline)
                .fontWeight(.bold)
                .foregroundColor(color ?? .primary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Positions Table

struct PositionsTableView: View {
    let positions: [Position]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Open Positions")
                .font(.headline)
                .fontWeight(.bold)

            if positions.isEmpty {
                Text("No open positions")
                    .font(.caption)
                    .foregroundColor(.gray)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding()
            } else {
                ScrollView(.horizontal) {
                    VStack(spacing: 1) {
                        // Header
                        HStack(spacing: 12) {
                            Text("Symbol").font(.caption2).fontWeight(.bold).frame(width: 60, alignment: .leading)
                            Text("Dir").font(.caption2).fontWeight(.bold).frame(width: 40, alignment: .center)
                            Text("Entry").font(.caption2).fontWeight(.bold).frame(width: 70, alignment: .trailing)
                            Text("Current").font(.caption2).fontWeight(.bold).frame(width: 70, alignment: .trailing)
                            Text("P&L $").font(.caption2).fontWeight(.bold).frame(width: 70, alignment: .trailing)
                            Text("P&L %").font(.caption2).fontWeight(.bold).frame(width: 70, alignment: .trailing)
                        }
                        .padding(8)
                        .background(Color(.controlBackgroundColor))

                        // Rows
                        ForEach(positions) { pos in
                            HStack(spacing: 12) {
                                Text(pos.symbol).font(.caption).frame(width: 60, alignment: .leading)
                                Text(pos.directionLabel).font(.caption).fontWeight(.semibold).frame(width: 40, alignment: .center)
                                Text(String(format: "$%.2f", pos.entry_price)).font(.caption).frame(width: 70, alignment: .trailing)
                                Text(String(format: "$%.2f", pos.current_price)).font(.caption).frame(width: 70, alignment: .trailing)
                                Text(String(format: "$%.2f", pos.pnl_dollar))
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundColor(pos.pnlColor)
                                    .frame(width: 70, alignment: .trailing)
                                Text(String(format: "%.2f%%", pos.pnl_percent))
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundColor(pos.pnlColor)
                                    .frame(width: 70, alignment: .trailing)
                            }
                            .padding(8)
                            .background(pos.pnlColor.opacity(0.05))
                        }
                    }
                }
            }
        }
        .padding()
        .background(Color(.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Trades Today

struct TradesView: View {
    let trades: [Trade]
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: { isExpanded.toggle() }) {
                HStack {
                    Text("Today's Trades")
                        .font(.headline)
                        .fontWeight(.bold)
                    Spacer()
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                }
            }

            if isExpanded && !trades.isEmpty {
                VStack(spacing: 8) {
                    ForEach(trades.prefix(10)) { trade in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("\(trade.symbol) \(trade.direction.uppercased())")
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                Text(trade.opened_at)
                                    .font(.caption2)
                                    .foregroundColor(.gray)
                                Text(trade.reason)
                                    .font(.caption2)
                                    .foregroundColor(.gray)
                            }

                            Spacer()

                            if let pnl = trade.pnl {
                                Text(String(format: "$%.2f", pnl))
                                    .font(.caption)
                                    .fontWeight(.bold)
                                    .foregroundColor(trade.pnlColor)
                            } else {
                                Text("Open")
                                    .font(.caption2)
                                    .foregroundColor(.orange)
                            }
                        }
                        .padding(8)
                        .background(Color(.controlBackgroundColor))
                        .cornerRadius(4)
                    }
                }
            }
        }
        .padding()
        .background(Color(.controlBackgroundColor))
        .cornerRadius(8)
    }
}

// MARK: - Scanner & Logs

struct ScannerLogsView: View {
    let status: ScannerStatus?
    let logs: [String]
    let onScanTapped: () -> Void
    @State private var logsExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Scanner Status
            if let status = status {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Scanner Status")
                            .font(.headline)
                            .fontWeight(.bold)
                        if let lastScan = status.last_scan {
                            Text("Last: \(lastScan)")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                        Text("Today: \(status.trades_opened_today) trades")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }

                    Spacer()

                    Button(action: onScanTapped) {
                        Text("Scan Now")
                            .font(.caption)
                            .fontWeight(.semibold)
                            .padding(8)
                            .background(Color.blue)
                            .foregroundColor(.white)
                            .cornerRadius(4)
                    }
                }
                .padding(8)
                .background(Color(.controlBackgroundColor))
                .cornerRadius(8)
            }

            // Logs
            VStack(alignment: .leading, spacing: 8) {
                Button(action: { logsExpanded.toggle() }) {
                    HStack {
                        Text("Live Logs")
                            .font(.headline)
                            .fontWeight(.bold)
                        Spacer()
                        Image(systemName: logsExpanded ? "chevron.up" : "chevron.down")
                    }
                }

                if logsExpanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(logs, id: \.self) { log in
                                Text(log)
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundColor(.gray)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 200)
                    .padding(8)
                    .background(Color.black.opacity(0.05))
                    .cornerRadius(4)
                }
            }
            .padding(8)
            .background(Color(.controlBackgroundColor))
            .cornerRadius(8)
        }
        .padding()
    }
}

// MARK: - Settings View

struct SettingsView: View {
    @ObservedObject var api: TradingBotAPI
    @Environment(\.presentationMode) var presentationMode
    @State private var vpsIP = ""
    @State private var vpsPort = ""

    var body: some View {
        VStack(spacing: 16) {
            Text("Settings")
                .font(.headline)
                .fontWeight(.bold)

            VStack(alignment: .leading, spacing: 8) {
                Text("VPS IP Address")
                    .font(.caption)
                    .foregroundColor(.gray)
                TextField("localhost", text: $vpsIP)
                    .textFieldStyle(.roundedBorder)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("VPS Port")
                    .font(.caption)
                    .foregroundColor(.gray)
                TextField("5000", text: $vpsPort)
                    .textFieldStyle(.roundedBorder)
            }

            HStack(spacing: 12) {
                Button("Cancel") {
                    presentationMode.wrappedValue.dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Save") {
                    if let port = Int(vpsPort) {
                        api.setVPSAddress(ip: vpsIP, port: port)
                        UserDefaults.standard.set(vpsIP, forKey: "vpsIP")
                        UserDefaults.standard.set(port, forKey: "vpsPort")
                        api.testConnection()
                    }
                    presentationMode.wrappedValue.dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }

            Spacer()
        }
        .padding()
        .frame(width: 300)
        .onAppear {
            vpsIP = UserDefaults.standard.string(forKey: "vpsIP") ?? "87.106.167.252"
            let savedPort = UserDefaults.standard.integer(forKey: "vpsPort")
            vpsPort = savedPort > 0 ? String(savedPort) : "5000"
        }
    }
}

#Preview {
    ContentView()
}
