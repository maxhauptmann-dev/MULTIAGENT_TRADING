# Hourly Options Trading Orchestrator

Production-ready hourly multi-timeframe options trading system with automated signal generation and Greeks-based risk management.

## System Architecture

```
Alpaca API Data
    ↓ DataFetcher
    ├─ Hourly candles (72h, 5-min cache)
    ├─ Daily candles (365d, 1-hour cache)
    ├─ IV (implied volatility)
    └─ Current prices with bid/ask
    ↓
AnalyticsEngine
    ├─ Technical indicators (RSI, MACD, ATR, EMA, Bollinger)
    ├─ Trend detection (hourly + daily)
    ├─ Volatility regime assessment
    └─ Quality scoring
    ↓
StrategyEngine
    ├─ Signal strength calculation
    ├─ Decision tree (7 strategies)
    ├─ Bull/Bear spreads, Calendar, Directional
    └─ Signal generation with confidence
    ↓
RiskManager
    ├─ Greeks calculation (Δ, Γ, Θ, Ν)
    ├─ Position validation
    ├─ Portfolio limit enforcement
    └─ Stop-loss/take-profit calculation
    ↓
TradingOrchestrator
    ├─ Hourly cycle orchestration
    ├─ APScheduler (10:00-20:00 UTC)
    ├─ Portfolio tracking
    └─ Cycle result logging
    ↓
Database + REST API
    ├─ Signal persistence
    ├─ Execution tracking
    ├─ /orchestrator/status
    ├─ /signals/last_hour
    ├─ /portfolio/greeks
    └─ Dashboard integration
```

## Installation

```bash
# Install dependencies
pip install apscheduler requests python-dotenv flask pandas pandas-ta

# Initialize database
python3 -c "
import sqlite3
conn = sqlite3.connect('trading.db')
with open('database_schema.sql', 'r') as f:
    conn.executescript(f.read())
conn.commit()
"

# Configure environment
cat > .env << EOF
APCA_API_KEY_ID=your_alpaca_key
APCA_API_SECRET_KEY=your_alpaca_secret
POSITION_DB_PATH=positions.db
EOF
```

## Usage

### Manual Hourly Cycle

```python
from trading_orchestrator import TradingOrchestrator

orchestrator = TradingOrchestrator(
    symbols=["AAPL", "MSFT", "GOOGL"],
    account_size=100000.0,
    schedule_enabled=False
)

result = orchestrator.run_hourly_cycle()
print(f"Signals generated: {result.signals_generated}")
print(f"Signals executed: {result.signals_executed}")
```

### Automated Scheduling

```python
orchestrator = TradingOrchestrator(
    symbols=["AAPL", "MSFT", "GOOGL"],
    account_size=100000.0,
    schedule_enabled=True  # Enable APScheduler
)

orchestrator.start()  # Runs hourly at 10:15-20:15 UTC
# ... keep running ...
orchestrator.stop()
```

### API Server

```python
from api_endpoints import OrchestratorAPI

api = OrchestratorAPI(orchestrator)
api.run(host="127.0.0.1", port=5000)
```

## REST API Endpoints

### `/orchestrator/status`
Last cycle result + portfolio state
```json
{
  "status": "running",
  "last_cycle": {
    "cycle_id": "cycle_1_2026-04-30T14:15:00",
    "symbols_analyzed": 3,
    "signals_generated": 2,
    "signals_executed": 1,
    "signals_rejected": 1,
    "duration_seconds": 4.23
  },
  "portfolio": {
    "positions": 3,
    "delta": 0.15,
    "theta_per_day": -125.50,
    "margin_used": "25.3%"
  }
}
```

### `/signals/last_hour`
Signals generated in last hour
```json
{
  "signals": [
    {
      "symbol": "AAPL",
      "strategy": "bull_call_spread",
      "direction": "bullish",
      "confidence": 0.80,
      "status": "executed"
    }
  ],
  "count": 5
}
```

### `/portfolio/greeks`
Current portfolio Greeks
```json
{
  "delta": 0.15,
  "gamma": 0.08,
  "theta_per_day": -125.50,
  "vega": 45.20
}
```

### `/portfolio/limit_status`
Risk limit utilization
```json
{
  "max_delta": 0.30,
  "current_delta": 0.15,
  "delta_utilization": 0.50,
  
  "max_theta_day": 500.0,
  "current_theta": -125.50,
  "theta_utilization": 0.25,
  
  "max_positions": 5,
  "current_positions": 3,
  "position_utilization": 0.60
}
```

## Configuration

### Portfolio Limits (risk_manager.py)

```python
MAX_PORTFOLIO_DELTA = 0.30      # ±30% delta exposure
MAX_THETA_BLEED_DAY = 500.0     # $500/day theta decay
MAX_CONCURRENT_POSITIONS = 5     # 5 open positions max
MIN_DTE = 14                      # 14 days minimum
MAX_DELTA_PER_POSITION = 0.20    # ±20% per position
MAX_GAMMA_PER_POSITION = 0.10    # 10% gamma per position
```

### Market Hours (trading_orchestrator.py)

APScheduler runs hourly at:
- **Time**: 10:00-20:00 UTC
- **Minute**: 15 (i.e., 10:15, 11:15, ..., 20:15)
- **Misfire grace**: 300 seconds (5 min buffer)

## Linux Deployment

### Systemd Service Setup

Create `/etc/systemd/system/trading-scheduler.service`:
```ini
[Unit]
Description=AI Trading Hourly Scheduler
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/opt/trading_bot
ExecStart=/usr/bin/python3 trading_orchestrator.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Deploy:
```bash
bash deploy_to_linux.sh
```

## Monitoring

### Check Service Status
```bash
systemctl status trading-scheduler.service
```

### View Recent Logs
```bash
journalctl -u trading-scheduler.service -n 50 -f
```

### Check Portfolio Health
```bash
curl http://localhost:5000/portfolio/limit_status
```

## Performance

- **Cycle time**: < 5 seconds (10 symbols)
- **Data fetch**: < 1 second (with caching)
- **Analysis**: < 2 seconds (all indicators)
- **Strategy generation**: < 1 second
- **Risk validation**: < 0.5 seconds

## Testing

Run test suites:
```bash
# DataFetcher tests
python -m unittest test_data_fetcher -v

# AnalyticsEngine tests
python -m unittest test_analytics_engine -v

# RiskManager tests
python -m unittest test_risk_manager -v
```

Total: **46 tests, 100% passing**

## Database

SQLite schema includes:
- `hourly_signals`: Generated signals (with status tracking)
- `executed_strategies`: Executed trades
- `strategy_legs`: Multi-leg option details
- `portfolio_history`: Daily P&L + Greeks
- `cycle_history`: Hourly cycle logs

Query example:
```sql
-- Recent signals
SELECT symbol, strategy, direction, confidence, status
FROM hourly_signals
WHERE created_at > datetime('now', '-1 hour')
ORDER BY created_at DESC;

-- Portfolio performance
SELECT date, daily_pnl, cumulative_pnl, margin_used_pct
FROM portfolio_history
ORDER BY date DESC
LIMIT 30;
```

## Error Handling

- **Network errors**: 3-retry logic with exponential backoff
- **Missing data**: Safe defaults (IV = 0.25, fallback to manual indicators)
- **API outages**: Skip cycle gracefully, log error
- **Invalid signals**: Rejected at validation step with reason

## Paper Trading

Run 2 weeks of paper trading before live:
1. Use Alpaca paper trading account
2. Monitor signals and execution quality
3. Verify Greeks calculations
4. Check portfolio limit enforcement
5. Validate daily P&L and statistics

## Support

Issues or questions? Check:
- `progress.md` - Implementation status
- `database_schema.sql` - Database structure
- Module docstrings - Implementation details

---

**Version:** 1.0  
**Status:** Production-ready (Phases 1-6 complete)  
**Last Updated:** 2026-04-30
