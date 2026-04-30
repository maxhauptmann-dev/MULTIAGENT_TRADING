import SwiftUI
import Charts

struct ContentView: View {
    @StateObject private var api = TradingBotAPI()
    @State private var showSettings = false
    @State private var showCredentialModal = false
    @State private var selectedTab: TabType = .pnl

    enum TabType {
        case pnl
        case positions
        case trades
        case settings
    }

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                // Top Header
                VStack(spacing: 16) {
                    // Header
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Trading Dashboard")
                                .font(.system(size: 20, weight: .bold))
                                .foregroundColor(.white)
                            HStack(spacing: 6) {
                                Circle()
                                    .fill(api.isConnected ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                                    .frame(width: 8, height: 8)
                                Text(api.isConnected ? "Connected to Alpaca" : "Disconnected")
                                    .font(.caption)
                                    .foregroundColor(api.isConnected ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                            }
                        }

                        Spacer()

                        VStack(alignment: .trailing, spacing: 4) {
                            Text(lastUpdateTime())
                                .font(.caption)
                                .foregroundColor(.gray)
                                .opacity(0.7)
                        }
                    }
                    .padding(16)
                    .background(Color(red: 0.08, green: 0.09, blue: 0.11))
                    .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
                    .cornerRadius(12)
                }
                .padding(16)

                // Tab Content
                VStack(spacing: 16) {

                    // Error banner
                    if let error = api.errorMessage {
                        HStack {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundColor(Color(red: 0.86, green: 0.27, blue: 0.27))
                            Text(error)
                                .font(.caption)
                                .foregroundColor(.white)
                            Spacer()
                        }
                        .frame(maxWidth: .infinity)
                        .padding(12)
                        .background(Color(red: 0.86, green: 0.27, blue: 0.27).opacity(0.15))
                        .border(Color(red: 0.86, green: 0.27, blue: 0.27), width: 1)
                        .cornerRadius(8)
                    }

                    if api.needsCredentials {
                        CredentialModalView(api: api, isPresented: $showCredentialModal)
                            .frame(maxHeight: 200)
                    } else {
                        ScrollView {
                            VStack(spacing: 16) {
                                // Tab-based content
                                switch selectedTab {
                                case .pnl:
                                    // Account Summary
                                    if let account = api.account {
                                        let totalUnrealizedPnL = api.positions.reduce(0) { $0 + $1.unrealized_pl }
                                        AccountSummaryCard(account: account, unrealizedPnL: totalUnrealizedPnL)
                                    }

                                    // Performance Stats
                                    if !api.historicalOrders.isEmpty || !api.portfolioHistory.isEmpty {
                                        PerformanceStatsView(historicalOrders: api.historicalOrders, portfolioHistory: api.portfolioHistory)
                                    }

                                    // P&L Chart
                                    if !api.portfolioHistory.isEmpty {
                                        OverallPnLChart(history: api.portfolioHistory)
                                    } else {
                                        PlaceholderChart(title: "Overall P&L", subtitle: "Loading portfolio data...")
                                    }

                                    // Daily P&L Chart
                                    if !api.portfolioHistory.isEmpty {
                                        DailyPnLChart(history: api.portfolioHistory)
                                    }

                                    // Equity Chart
                                    if !api.portfolioHistory.isEmpty {
                                        EquityChart(history: api.portfolioHistory)
                                    } else {
                                        PlaceholderChart(title: "Mark-to-Market Holdings", subtitle: "Loading portfolio data...")
                                    }

                                case .positions:
                                    // Positions overview
                                    if let account = api.account {
                                        let totalUnrealizedPnL = api.positions.reduce(0) { $0 + $1.unrealized_pl }
                                        AccountSummaryCard(account: account, unrealizedPnL: totalUnrealizedPnL)
                                    }

                                    // Position Pie Chart
                                    if !api.positions.isEmpty {
                                        PositionPieChart(positions: api.positions)
                                    } else {
                                        PlaceholderChart(title: "Position Distribution", subtitle: "No open positions")
                                    }

                                    // Positions Table
                                    PositionsTableView(positions: api.positions)

                                case .trades:
                                    // Trade Analytics
                                    if !api.historicalOrders.isEmpty || !api.trades.isEmpty {
                                        TradeAnalyticsView(historicalOrders: api.historicalOrders, trades: api.trades)
                                    }

                                    // Trades Today
                                    TradesView(trades: api.trades)

                                case .settings:
                                    SettingsView(api: api)
                                }
                            }
                        }
                    }

                    Spacer()
                }
                .padding(16)

                // Bottom Navigation Bar
                BottomNavigationBar(selectedTab: $selectedTab)
            }
            .navigationTitle("")
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

// MARK: - Credential Modal

struct CredentialModalView: View {
    @ObservedObject var api: TradingBotAPI
    @Binding var isPresented: Bool
    @State private var apiKey = ""
    @State private var apiSecret = ""

    var body: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Alpaca API Credentials")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.white)
                Text("Enter your API keys to connect")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("API Key")
                    .font(.caption)
                    .foregroundColor(.gray)
                    .opacity(0.8)
                TextField("APCA-API-KEY-ID", text: $apiKey)
                    .padding(10)
                    .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                    .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                    .cornerRadius(6)
                    .font(.caption)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("API Secret")
                    .font(.caption)
                    .foregroundColor(.gray)
                    .opacity(0.8)
                SecureField("APCA-API-SECRET-KEY", text: $apiSecret)
                    .padding(10)
                    .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                    .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                    .cornerRadius(6)
                    .font(.caption)
            }

            HStack(spacing: 12) {
                Button("Cancel") {
                    isPresented = false
                }
                .keyboardShortcut(.cancelAction)
                .frame(maxWidth: .infinity)
                .padding(10)
                .background(Color(red: 0.15, green: 0.18, blue: 0.25))
                .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                .cornerRadius(6)
                .foregroundColor(.gray)
                .font(.caption)

                Button("Connect") {
                    if !apiKey.isEmpty && !apiSecret.isEmpty {
                        api.setAlpacaCredentials(apiKey: apiKey, apiSecret: apiSecret)
                        isPresented = false
                    }
                }
                .keyboardShortcut(.defaultAction)
                .frame(maxWidth: .infinity)
                .padding(10)
                .background(Color(red: 0.4, green: 0.6, blue: 1.0))
                .cornerRadius(6)
                .foregroundColor(.white)
                .font(.caption)
                .fontWeight(.semibold)
                .disabled(apiKey.isEmpty || apiSecret.isEmpty)
                .opacity(apiKey.isEmpty || apiSecret.isEmpty ? 0.5 : 1.0)
            }

            Spacer()
        }
        .padding(16)
    }
}

// MARK: - Account Summary Card

struct AccountSummaryCard: View {
    let account: AlpacaAccount
    let unrealizedPnL: Double

    var pnlColor: Color {
        unrealizedPnL >= 0 ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Equity")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.gray)
                    Text(String(format: "$%.0f", account.equity))
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("Today's P&L")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.gray)
                    HStack(spacing: 4) {
                        Image(systemName: unrealizedPnL >= 0 ? "arrow.up.right" : "arrow.down.left")
                            .font(.system(size: 12, weight: .semibold))
                        Text(String(format: "$%.2f", abs(unrealizedPnL)))
                            .font(.system(size: 16, weight: .semibold, design: .monospaced))
                    }
                    .foregroundColor(pnlColor)
                }
            }

            Divider()
                .opacity(0.2)

            HStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Buying Power")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.gray)
                    Text(String(format: "$%.0f", account.buying_power))
                        .font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
                Spacer()
                VStack(alignment: .leading, spacing: 4) {
                    Text("Cash")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.gray)
                    Text(String(format: "$%.0f", account.cash))
                        .font(.system(size: 13, weight: .semibold, design: .monospaced))
                }
            }
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Placeholder Chart

struct PlaceholderChart: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

            VStack(alignment: .center, spacing: 12) {
                ProgressView()
                    .scaleEffect(1.2, anchor: .center)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.gray)
                    .opacity(0.7)
            }
            .frame(height: 150)
            .frame(maxWidth: .infinity)
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Overall P&L Chart

struct OverallPnLChart: View {
    let history: [PortfolioHistoryPoint]

    var latestPnL: Double {
        history.last?.profitLoss ?? 0
    }

    var latestPnLPct: Double {
        history.last?.profitLossPct ?? 0
    }

    var pnlColor: Color {
        latestPnL >= 0 ? .green : .red
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Overall P&L")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.gray)
                    HStack(spacing: 6) {
                        Image(systemName: latestPnL >= 0 ? "arrow.up.right" : "arrow.down.left")
                            .font(.system(size: 13, weight: .semibold))
                        Text(String(format: "$%.2f", abs(latestPnL)))
                            .font(.system(size: 18, weight: .semibold, design: .monospaced))
                    }
                    .foregroundColor(pnlColor)
                }
                Spacer()
                Text(String(format: "%.2f%%", latestPnLPct * 100))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(pnlColor.opacity(0.8))
                    .padding(6)
                    .background(pnlColor.opacity(0.1))
                    .cornerRadius(6)
            }

            Chart(history) { point in
                LineMark(
                    x: .value("Date", point.date),
                    y: .value("P&L", point.profitLoss)
                )
                .foregroundStyle(pnlColor)
                .lineStyle(StrokeStyle(lineWidth: 2.5))

                AreaMark(
                    x: .value("Date", point.date),
                    y: .value("P&L", point.profitLoss)
                )
                .foregroundStyle(pnlColor.opacity(0.15))
            }
            .chartYAxis {
                AxisMarks(position: .trailing, values: .automatic(desiredCount: 4))
            }
            .chartXAxis {
                AxisMarks(position: .bottom, values: .automatic(desiredCount: 4))
            }
            .frame(height: 180)
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Equity Chart (Mark-to-Market Holdings)

struct EquityChart: View {
    let history: [PortfolioHistoryPoint]

    var latestEquity: Double {
        history.last?.equity ?? 0
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Mark-to-Market Holdings")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.gray)
                    Text(String(format: "$%.0f", latestEquity))
                        .font(.system(size: 18, weight: .semibold, design: .monospaced))
                        .foregroundColor(Color(red: 0.4, green: 0.6, blue: 1.0))
                }

                Spacer()
            }

            Chart(history) { point in
                AreaMark(
                    x: .value("Date", point.date),
                    y: .value("Equity", point.equity)
                )
                .foregroundStyle(Color(red: 0.4, green: 0.6, blue: 1.0).opacity(0.15))

                LineMark(
                    x: .value("Date", point.date),
                    y: .value("Equity", point.equity)
                )
                .foregroundStyle(Color(red: 0.4, green: 0.6, blue: 1.0))
                .lineStyle(StrokeStyle(lineWidth: 2.5))
            }
            .chartYAxis {
                AxisMarks(position: .trailing, values: .automatic(desiredCount: 4))
            }
            .chartXAxis {
                AxisMarks(position: .bottom, values: .automatic(desiredCount: 4))
            }
            .frame(height: 180)
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

struct StatCard: View {
    let label: String
    let value: String
    let color: Color?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.gray)
                .opacity(0.8)
            Text(value)
                .font(.system(size: 16, weight: .semibold, design: .monospaced))
                .foregroundColor(color ?? Color(red: 0.4, green: 0.6, blue: 1.0))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(red: 0.12, green: 0.14, blue: 0.18))
        .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
        .cornerRadius(8)
    }
}

// MARK: - Performance Stats

struct PerformanceStatsView: View {
    let historicalOrders: [AlpacaOrder]
    let portfolioHistory: [PortfolioHistoryPoint]

    var winRate: Double {
        guard !historicalOrders.isEmpty else { return 0 }
        let filledOrders = historicalOrders.filter { $0.status == "filled" }
        guard !filledOrders.isEmpty else { return 0 }
        let sellOrders = filledOrders.filter { $0.side == "sell" }
        return Double(sellOrders.count) / Double(filledOrders.count) * 100
    }

    var maxDrawdown: Double {
        guard portfolioHistory.count > 1 else { return 0 }
        var peak = portfolioHistory[0].equity
        var maxDD = 0.0
        for point in portfolioHistory {
            if point.equity > peak {
                peak = point.equity
            }
            let dd = peak - point.equity
            if dd > maxDD {
                maxDD = dd
            }
        }
        return maxDD
    }

    var profitFactor: Double {
        guard !historicalOrders.isEmpty else { return 0 }
        var gains = 0.0
        var losses = 0.0
        for order in historicalOrders where order.status == "filled" {
            if let price = order.filled_avg_price {
                if order.side == "buy" {
                    losses += price * order.qty
                } else {
                    gains += price * order.qty
                }
            }
        }
        return losses != 0 ? gains / losses : 0
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Performance Metrics")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

            HStack(spacing: 12) {
                StatCard(label: "Win Rate", value: String(format: "%.1f%%", winRate), color: winRate > 50 ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                StatCard(label: "Max Drawdown", value: String(format: "$%.0f", maxDrawdown), color: maxDrawdown > 0 ? Color(red: 0.86, green: 0.27, blue: 0.27) : Color(red: 0.34, green: 0.85, blue: 0.34))
                StatCard(label: "Profit Factor", value: String(format: "%.2f", profitFactor), color: profitFactor > 1 ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                StatCard(label: "Total Trades", value: String(historicalOrders.count), color: Color(red: 0.4, green: 0.6, blue: 1.0))
            }
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Daily P&L Chart

struct DailyPnLChart: View {
    let history: [PortfolioHistoryPoint]

    var dailyPnL: [(date: Date, pnl: Double)] {
        guard history.count > 1 else { return [] }
        var result: [(Date, Double)] = []
        for i in 1..<history.count {
            let date = history[i].date
            let pnl = history[i].equity - history[i-1].equity
            result.append((date, pnl))
        }
        return result
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Daily P&L")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

            Chart(dailyPnL, id: \.date) { item in
                BarMark(
                    x: .value("Date", item.date),
                    y: .value("P&L", item.pnl)
                )
                .foregroundStyle(item.pnl >= 0 ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
            }
            .chartYAxis {
                AxisMarks(position: .trailing, values: .automatic(desiredCount: 4))
            }
            .chartXAxis {
                AxisMarks(position: .bottom, values: .automatic(desiredCount: 5))
            }
            .frame(height: 150)
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Position Pie Chart

struct PositionPieChart: View {
    let positions: [AlpacaPosition]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Position Distribution")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

            Chart(positions) { pos in
                SectorMark(
                    angle: .value("Market Value", abs(pos.qty) * pos.current_price)
                )
                .foregroundStyle(by: .value("Symbol", pos.symbol))
            }
            .frame(height: 150)
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Trade Analytics

struct TradeAnalyticsView: View {
    let historicalOrders: [AlpacaOrder]
    let trades: [AlpacaOrder]

    var totalTrades: Int {
        historicalOrders.count
    }

    var todayTrades: Int {
        trades.count
    }

    var bestTrade: Double {
        guard !trades.isEmpty else { return 0 }
        var best = 0.0
        for trade in trades {
            if trade.status == "filled", let price = trade.filled_avg_price {
                let value = price * trade.qty
                if value > best {
                    best = value
                }
            }
        }
        return best
    }

    var winStreak: Int {
        // Win streak from recent orders (simplified: count of recent orders)
        guard !historicalOrders.isEmpty else { return 0 }
        return historicalOrders.filter { $0.status == "filled" }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Trade Analytics")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

            HStack(spacing: 12) {
                StatCard(label: "Total Trades", value: String(totalTrades), color: Color(red: 0.4, green: 0.6, blue: 1.0))
                StatCard(label: "Today", value: String(todayTrades), color: todayTrades > 0 ? Color(red: 0.4, green: 0.6, blue: 1.0) : .gray)
                StatCard(label: "Win Streak", value: String(winStreak), color: winStreak > 0 ? Color(red: 0.34, green: 0.85, blue: 0.34) : .gray)
                StatCard(label: "Best Trade", value: String(format: "$%.0f", bestTrade), color: bestTrade > 0 ? Color(red: 0.34, green: 0.85, blue: 0.34) : .gray)
            }
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Positions Table

struct PositionsTableView: View {
    let positions: [AlpacaPosition]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Open Positions")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.gray)

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
                            Text("Symbol").font(.caption2).fontWeight(.semibold).frame(width: 60, alignment: .leading)
                            Text("Dir").font(.caption2).fontWeight(.semibold).frame(width: 40, alignment: .center)
                            Text("Qty").font(.caption2).fontWeight(.semibold).frame(width: 50, alignment: .trailing)
                            Text("Entry").font(.caption2).fontWeight(.semibold).frame(width: 70, alignment: .trailing)
                            Text("Current").font(.caption2).fontWeight(.semibold).frame(width: 70, alignment: .trailing)
                            Text("P&L $").font(.caption2).fontWeight(.semibold).frame(width: 70, alignment: .trailing)
                            Text("P&L %").font(.caption2).fontWeight(.semibold).frame(width: 70, alignment: .trailing)
                        }
                        .padding(10)
                        .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                        .foregroundColor(.gray)

                        // Rows
                        ForEach(positions) { pos in
                            let pnlColor: Color = pos.unrealized_pl >= 0 ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27)
                            HStack(spacing: 12) {
                                Text(pos.symbol).font(.caption).frame(width: 60, alignment: .leading)
                                Text(pos.directionLabel).font(.caption).fontWeight(.semibold).frame(width: 40, alignment: .center).foregroundColor(Color(red: 0.4, green: 0.6, blue: 1.0))
                                Text(String(format: "%.0f", pos.qty)).font(.caption).frame(width: 50, alignment: .trailing)
                                Text(String(format: "$%.2f", pos.avg_entry_price)).font(.caption).frame(width: 70, alignment: .trailing)
                                Text(String(format: "$%.2f", pos.current_price)).font(.caption).frame(width: 70, alignment: .trailing)
                                Text(String(format: "$%.2f", pos.unrealized_pl))
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundColor(pnlColor)
                                    .frame(width: 70, alignment: .trailing)
                                Text(String(format: "%.2f%%", pos.unrealized_plpc * 100))
                                    .font(.caption)
                                    .fontWeight(.semibold)
                                    .foregroundColor(pnlColor)
                                    .frame(width: 70, alignment: .trailing)
                            }
                            .padding(10)
                            .background(pnlColor.opacity(0.08))
                        }
                    }
                }
            }
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Trades Today

struct TradesView: View {
    let trades: [AlpacaOrder]
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button(action: { isExpanded.toggle() }) {
                HStack {
                    Text("Today's Trades (\(trades.count))")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.white)
                    Spacer()
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .foregroundColor(.gray)
                }
            }
            .buttonStyle(PlainButtonStyle())

            if isExpanded {
                if trades.isEmpty {
                    Text("No trades today")
                        .font(.caption)
                        .foregroundColor(.gray)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding()
                } else {
                    VStack(spacing: 8) {
                        ForEach(trades.prefix(20)) { trade in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(spacing: 6) {
                                        Text(trade.symbol)
                                            .font(.caption)
                                            .fontWeight(.semibold)
                                            .foregroundColor(Color(red: 0.4, green: 0.6, blue: 1.0))
                                        Text(trade.side.uppercased())
                                            .font(.caption2)
                                            .fontWeight(.semibold)
                                            .foregroundColor(trade.side == "buy" ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                                            .padding(.horizontal, 6)
                                            .padding(.vertical, 2)
                                            .background(trade.side == "buy" ? Color(red: 0.34, green: 0.85, blue: 0.34).opacity(0.15) : Color(red: 0.86, green: 0.27, blue: 0.27).opacity(0.15))
                                            .cornerRadius(3)
                                    }
                                    Text(trade.created_at)
                                        .font(.caption2)
                                        .foregroundColor(.gray)
                                    Text("Qty: \(Int(trade.qty)) @ \(String(format: "$%.2f", trade.filled_avg_price ?? 0))")
                                        .font(.caption2)
                                        .foregroundColor(.gray)
                                }

                                Spacer()

                                VStack(alignment: .trailing, spacing: 2) {
                                    Text(trade.status.uppercased())
                                        .font(.caption2)
                                        .fontWeight(.semibold)
                                        .foregroundColor(trade.isClosed ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 1.0, green: 0.7, blue: 0.0))
                                }
                            }
                            .padding(10)
                            .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                            .cornerRadius(6)
                        }
                    }
                }
            }
        }
        .padding(16)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
        .cornerRadius(12)
    }
}

// MARK: - Settings View

struct SettingsView: View {
    @ObservedObject var api: TradingBotAPI
    @Environment(\.presentationMode) var presentationMode
    @State private var apiKey = ""
    @State private var apiSecret = ""
    @State private var showUpdateForm = false

    var body: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Settings")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.white)
                Text("Manage your Alpaca connection")
                    .font(.caption)
                    .foregroundColor(.gray)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            VStack(alignment: .leading, spacing: 12) {
                Text("Alpaca API Status")
                    .font(.caption)
                    .foregroundColor(.gray)
                    .opacity(0.8)
                HStack {
                    Circle()
                        .fill(api.isConnected ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                        .frame(width: 10, height: 10)
                    Text(api.isConnected ? "Connected to Alpaca" : "Disconnected")
                        .font(.caption)
                        .foregroundColor(api.isConnected ? Color(red: 0.34, green: 0.85, blue: 0.34) : Color(red: 0.86, green: 0.27, blue: 0.27))
                }
            }
            .padding(12)
            .background(Color(red: 0.1, green: 0.12, blue: 0.16))
            .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
            .cornerRadius(8)

            if showUpdateForm {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Update API Credentials")
                        .font(.caption)
                        .foregroundColor(.gray)
                        .opacity(0.8)
                    TextField("API Key", text: $apiKey)
                        .padding(10)
                        .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                        .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                        .cornerRadius(6)
                        .font(.caption)
                    SecureField("API Secret", text: $apiSecret)
                        .padding(10)
                        .background(Color(red: 0.1, green: 0.12, blue: 0.16))
                        .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                        .cornerRadius(6)
                        .font(.caption)
                }
            }

            HStack(spacing: 12) {
                Button("Cancel") {
                    presentationMode.wrappedValue.dismiss()
                }
                .keyboardShortcut(.cancelAction)
                .frame(maxWidth: .infinity)
                .padding(10)
                .background(Color(red: 0.15, green: 0.18, blue: 0.25))
                .border(Color(red: 0.2, green: 0.3, blue: 0.6), width: 0.5)
                .cornerRadius(6)
                .foregroundColor(.gray)
                .font(.caption)

                if showUpdateForm {
                    Button("Save") {
                        if !apiKey.isEmpty && !apiSecret.isEmpty {
                            api.setAlpacaCredentials(apiKey: apiKey, apiSecret: apiSecret)
                            presentationMode.wrappedValue.dismiss()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .frame(maxWidth: .infinity)
                    .padding(10)
                    .background(Color(red: 0.4, green: 0.6, blue: 1.0))
                    .cornerRadius(6)
                    .foregroundColor(.white)
                    .font(.caption)
                    .fontWeight(.semibold)
                    .disabled(apiKey.isEmpty || apiSecret.isEmpty)
                    .opacity(apiKey.isEmpty || apiSecret.isEmpty ? 0.5 : 1.0)
                } else {
                    Button("Update Credentials") {
                        showUpdateForm = true
                    }
                    .frame(maxWidth: .infinity)
                    .padding(10)
                    .background(Color(red: 0.4, green: 0.6, blue: 1.0))
                    .cornerRadius(6)
                    .foregroundColor(.white)
                    .font(.caption)
                    .fontWeight(.semibold)
                }
            }

            Spacer()
        }
        .padding(16)
        .frame(width: 380)
    }
}

// MARK: - Bottom Navigation Bar

struct BottomNavigationBar: View {
    @Binding var selectedTab: ContentView.TabType

    var body: some View {
        HStack(spacing: 0) {
            TabBarItem(
                icon: "chart.line.uptrend.xyaxis",
                label: "P&L",
                isSelected: selectedTab == .pnl,
                action: { selectedTab = .pnl }
            )

            TabBarItem(
                icon: "square.grid.2x2",
                label: "Positions",
                isSelected: selectedTab == .positions,
                action: { selectedTab = .positions }
            )

            TabBarItem(
                icon: "arrow.left.arrow.right",
                label: "Trades",
                isSelected: selectedTab == .trades,
                action: { selectedTab = .trades }
            )

            TabBarItem(
                icon: "gear",
                label: "Settings",
                isSelected: selectedTab == .settings,
                action: { selectedTab = .settings }
            )
        }
        .frame(height: 60)
        .background(Color(red: 0.08, green: 0.09, blue: 0.11))
        .border(Color(red: 0.15, green: 0.25, blue: 0.55), width: 1)
    }
}

struct TabBarItem: View {
    let icon: String
    let label: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                Text(label)
                    .font(.caption2)
            }
            .frame(maxWidth: .infinity)
            .foregroundColor(isSelected ? Color(red: 0.4, green: 0.6, blue: 1.0) : .gray)
            .contentShape(Rectangle())
        }
        .buttonStyle(PlainButtonStyle())
        .background(isSelected ? Color(red: 0.12, green: 0.15, blue: 0.22) : Color.clear)
    }
}

// #Preview {
//     ContentView()
// }
