# Design: Mac Trading Dashboard

**Date**: 2026-04-24  
**Status**: Approved  
**Scope**: Monitoring-only dashboard for real-time trading status on macOS

---

## Overview

Build a native Swift app for macOS that displays real-time trading status, open positions, P&L, and market regime from the VPS-based trading bot. The app provides a graphical overview of bot activity without interfering with automated trading.

**User Goals:**
- See open positions, P&L, and market regime at a glance
- Review what trades bot made today
- View last few scanner runs
- Optionally trigger a manual scan

---

## Architecture

### Backend (VPS Linux)

A lightweight Flask server provides HTTP API endpoints for the Mac app to query.

**Server Details:**
- Framework: Flask (minimal, ~60 lines)
- Port: 5000 (configurable via `.env`)
- Data source: SQLite `positions.db` (existing bot database)
- Polling frequency: Mac app requests every 60 seconds
- Update strategy: Read-only from existing bot DB (no writes)

**Endpoints:**

| Endpoint | Method | Returns | Source |
|----------|--------|---------|--------|
| `/api/positions` | GET | Open positions with P&L | `positions.db` table |
| `/api/market-regime` | GET | BULL/BEAR/NEUTRAL + VIX | Latest from scanner logs |
| `/api/trades-today` | GET | List of trades opened/closed today | `positions.db` filtered by date |
| `/api/scanner-status` | GET | Last scan time, symbols scanned | Scanner logs |
| `/api/logs/tail` | GET | Last 50 lines of bot logs | `trading_bot.log` or similar |
| `/api/trigger-scan` | POST | Enqueue manual scan | Async task to DEF_SCANNER_MODE |

**Response Format (JSON):**
All responses include `timestamp` and error handling:
```json
{
  "status": "ok" | "error",
  "timestamp": "2026-04-24T14:30:00Z",
  "data": {...}
}
```

### Frontend (Mac)

Native Swift app using SwiftUI framework.

**Architecture:**
- **Model**: `TradingBotAPI` (URLSession-based HTTP client)
- **Views**: Organized by section (Positions, Market Regime, Trades, Scanner, Logs)
- **State Management**: `@ObservedObject` for reactive updates
- **Refresh**: Timer fires every 60 seconds, fetches all endpoints
- **Error Handling**: Show toast/banner for API failures, retry logic

**Data Flow:**
```
Timer (60s)
  ↓ triggers
TradingBotAPI.fetchAll()
  ↓ HTTP GET to each endpoint
VPS Flask Server
  ↓ HTTP response (JSON)
SwiftUI @State updates
  ↓ UI re-renders
Display updated data
```

---

## UI Layout

**Priority order (top to bottom):**

### 1. Header Bar
- **Left**: App name + connection status (🟢 Connected / 🔴 Error)
- **Center**: Market Regime badge (BULL/BEAR/NEUTRAL)
- **Right**: Last update timestamp

### 2. Market Regime Card
- Regime status (large, color-coded)
- SPY vs EMA20 percentage
- VIX value
- Background color: green (bull), red (bear), gray (neutral)

### 3. Portfolio Stats (3 Cards)
- **Card 1**: Total Open Positions (count)
- **Card 2**: Total P&L ($ amount, green/red)
- **Card 3**: Win Rate (% of closed trades today)

### 4. Offene Positionen (Main Table)
- Columns: Symbol | Direction | Entry $ | Current $ | P&L $ | P&L %
- Sortable by P&L
- Color-coded rows: green (profit), red (loss)
- Click row for details (SL/TP, ATR, Kelly fraction)

### 5. Heute's Trades (Expandable Section)
- List: Time | Symbol | Action (BUY/SELL) | Reason | Result ($)
- Max 10 most recent trades visible, expandable for more
- Green for winners, red for losers

### 6. Scanner Status (Collapsible)
- Last scan: Date + Time + Duration
- Symbols scanned (list)
- Setups found (count)
- "Scan Now" button (triggers `/api/trigger-scan`)

### 7. Live Logs (Collapsible)
- Last 50 lines of bot output (monospace font)
- Auto-scroll to latest
- Search/filter optional

---

## Data Structures

### GET /api/positions Response
```json
{
  "status": "ok",
  "data": {
    "positions": [
      {
        "symbol": "AAPL",
        "direction": "long",
        "entry_price": 150.50,
        "quantity": 10,
        "current_price": 151.75,
        "pnl_dollar": 125.00,
        "pnl_percent": 0.83,
        "stop_loss": 148.00,
        "take_profit": 155.00,
        "opened_at": "2026-04-24T09:30:00Z",
        "highest_price": 152.10,
        "lowest_price": 150.25,
        "atr_14": 2.50,
        "kelly_fraction": 0.15
      }
    ],
    "timestamp": "2026-04-24T14:30:00Z"
  }
}
```

### GET /api/market-regime Response
```json
{
  "status": "ok",
  "data": {
    "regime": "bull",
    "spy_vs_ema20_pct": 2.45,
    "qqq_vs_ema20_pct": 1.80,
    "vix": 18.5,
    "timestamp": "2026-04-24T14:30:00Z"
  }
}
```

### GET /api/trades-today Response
```json
{
  "status": "ok",
  "data": {
    "trades": [
      {
        "symbol": "MSFT",
        "action": "BUY",
        "price": 420.00,
        "quantity": 5,
        "opened_at": "2026-04-24T10:15:00Z",
        "closed_at": null,
        "pnl": null,
        "reason": "regime_agent + bullish_signal"
      }
    ]
  }
}
```

---

## Error Handling

**Network Failures:**
- Show red banner: "Cannot connect to trading bot"
- Disable "Scan Now" button
- Keep showing last known data (stale, but better than nothing)
- Auto-retry on next timer tick

**Malformed Data:**
- Log to system console
- Show safe defaults (e.g., "N/A" for unknown values)
- Continue rendering other sections

**API Timeout (>5s):**
- Cancel request
- Show "Timeout" in banner
- Try again next tick

---

## Implementation Sequence

**Phase 1: Backend (VPS)**
1. Create `api_server.py` (Flask endpoints)
2. Add to systemd service or startup script
3. Test endpoints with `curl`

**Phase 2: Frontend (Mac)**
1. Create Xcode project (Swift + SwiftUI)
2. Implement `TradingBotAPI` HTTP client
3. Build UI views (top-to-bottom)
4. Add timer refresh logic
5. Test on Mac, debug API calls

**Phase 3: Integration & Polish**
1. Test end-to-end (VPS + Mac)
2. Handle edge cases (no open positions, offline, etc.)
3. Add configuration (VPS IP, port, refresh interval)
4. Deploy to VPS, build Mac app

---

## Testing Strategy

**Backend Tests:**
- `curl http://vps-ip:5000/api/positions` → returns valid JSON
- Verify data matches SQLite contents
- Test offline DB (positions.db missing) → graceful error

**Frontend Tests:**
- Simulator: Connect to VPS, check all data displays
- Real Mac: Connect to VPS via IP
- Manual: Trigger trade on bot, verify Mac updates within 60s
- Error case: Disconnect VPS, app shows error banner, recovers on reconnect

---

## Configuration

**VPS (.env):**
```
FLASK_API_PORT=5000
FLASK_API_DEBUG=false
```

**Mac (in-app settings, future):**
```
VPS_IP=<user-entered>
VPS_PORT=5000
REFRESH_INTERVAL_SECONDS=60
```

---

## Notes

- Read-only API: Bot data is never modified from Mac app
- Graceful degradation: If API unavailable, app shows last known state
- Future enhancements: WebSocket for real-time (Phase 2), chart history (Phase 3)
