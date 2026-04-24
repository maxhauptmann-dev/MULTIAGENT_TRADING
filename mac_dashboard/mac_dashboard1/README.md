# Trading Dashboard - Mac App

Native SwiftUI app for macOS to monitor your trading bot running on the VPS.

## Prerequisites

- macOS 12.0 or later
- Xcode 14.0 or later
- VPS with Flask API server running (`api_server.py`)

## Setup Instructions

### Step 1: Create Xcode Project

1. Open Xcode
2. Create a new macOS App project
   - Product Name: `Trading Dashboard`
   - Organization: Your choice
   - Team: Your choice
   - Bundle Identifier: `com.trading.dashboard`
   - Language: Swift
   - SwiftUI selected

### Step 2: Add Swift Files

1. Copy these files into your Xcode project:
   - `TradingBotAPI.swift` → API client and data models
   - `ContentView.swift` → Main UI
   - `TradingDashboardApp.swift` → App entry point

2. In Xcode:
   - Right-click on project → Add Files to "Trading Dashboard"
   - Select all `.swift` files and add

### Step 3: Configure VPS Connection

When you first launch the app:

1. Click the ⚙️ settings button (top right)
2. Enter your VPS IP address (e.g., `192.168.1.100` or your VPS's public IP)
3. Enter VPS Port (default: `5000`)
4. Click "Save"

The app will test the connection immediately.

### Step 4: Build and Run

```bash
# In Xcode
Product → Run  (Cmd+R)
```

Or build for distribution:

```bash
# Build archive
Product → Archive

# Export app
Window → Organizer → Select archive → Distribute App
```

## Configuration

### On VPS

Ensure `api_server.py` is running:

```bash
cd /path/to/AI_TRADING
python3 api_server.py
```

Or add to systemd service (persists across reboots):

```bash
# Create systemd unit
sudo nano /etc/systemd/system/trading-api.service
```

```ini
[Unit]
Description=Trading Bot API Server
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/home/trading/AI_TRADING
ExecStart=/usr/bin/python3 /home/trading/AI_TRADING/api_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-api
sudo systemctl start trading-api
sudo systemctl status trading-api
```

### On Mac (App Settings)

- **VPS IP**: Your VPS's IP address (not `localhost` unless running VPS on same Mac)
- **VPS Port**: 5000 (or whatever you set in `.env` on VPS)
- **Refresh Interval**: 60 seconds (hardcoded, can customize in `TradingBotAPI.swift`)

## Data Displayed

### Header
- Connection status (🟢 green = connected, 🔴 red = disconnected)
- Last update timestamp
- Settings button

### Market Regime Card
- Current regime: BULL (green) / BEAR (red) / NEUTRAL (gray)
- SPY vs EMA20 percentage
- QQQ vs EMA20 percentage
- Current VIX level

### Portfolio Stats (3 Cards)
- Number of open positions
- Total P&L in dollars
- Average P&L percentage

### Open Positions (Table)
- Symbol, Direction (LONG/SHORT)
- Entry price, Current price
- P&L in dollars and percent (color-coded: green = profit, red = loss)
- Sortable by any column

### Today's Trades
- Expandable list of trades opened today
- Time, Symbol, Action, Reason, Result
- Shows up to 10 most recent

### Scanner Status
- Last scan timestamp
- Number of trades opened today
- **Scan Now** button to manually trigger a scan on VPS

### Live Logs
- Expandable section with last 50 lines of bot logs
- Monospace font for readability
- Shows what bot is doing in real-time

## Troubleshooting

### "Cannot connect to trading bot"

1. Check Flask API is running on VPS:
   ```bash
   curl http://vps-ip:5000/api/health
   ```
   Should return `{"status":"ok", ...}`

2. Verify VPS IP in app settings (Settings ⚙️)

3. Check firewall:
   ```bash
   sudo ufw allow 5000
   ```

4. Check VPS `.env`:
   ```
   FLASK_API_PORT=5000
   POSITION_DB_PATH=/path/to/positions.db
   ```

### "Decode error" in logs

- API response format changed
- Check `api_server.py` is up to date
- Check bot `positions.db` exists and is readable

### App freezes when clicking "Scan Now"

- Normal: scan takes 30-60 seconds, app queues it asynchronously
- Check VPS logs:
  ```bash
  tail -f trading_bot.log
  ```

## Development

To modify the app:

1. Open in Xcode
2. Edit `ContentView.swift` for UI changes
3. Edit `TradingBotAPI.swift` for data fetching
4. Press Cmd+R to rebuild and run

### Adding new endpoints

If you add a new endpoint to `api_server.py`:

1. Add data model in `TradingBotAPI.swift`
2. Add `@Published` property to `TradingBotAPI` class
3. Add fetch function (e.g., `fetchMyData()`)
4. Call it from `fetchAll()` or `startRefreshTimer()`
5. Display in `ContentView.swift`

## Support

If you encounter issues:

1. Check VPS logs:
   ```bash
   journalctl -u trading-api -f
   ```

2. Check Flask API directly:
   ```bash
   curl -s http://vps-ip:5000/api/positions | jq .
   ```

3. Check Mac Console.app for app logs

## Privacy & Security

- All communication is HTTP (not HTTPS)
- For production, add SSL certificate to Flask
- VPS IP/port stored in app, not synced to iCloud

## Future Enhancements

- [ ] WebSocket for real-time updates (faster than polling)
- [ ] Chart history (P&L over time)
- [ ] Position details popup (SL/TP, Kelly fraction, etc.)
- [ ] Trading alerts (sound, notifications)
- [ ] Dark mode support
- [ ] Export logs to file
- [ ] iOS companion app
