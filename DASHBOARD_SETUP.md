# Mac Trading Dashboard - Complete Setup Guide

## Overview

You now have:
1. **Backend** (`api_server.py`): Flask API on your VPS
2. **Frontend** (`mac_dashboard/`): Native Swift app for your Mac

This guide walks you through getting everything running end-to-end.

---

## Part 1: VPS Setup (Linux)

### Step 1.1: Test Flask API Server Locally

First, verify the API works:

```bash
cd /path/to/AI_TRADING

# Check if positions.db exists
ls -la positions.db

# Run API server
python3 api_server.py
```

Expected output:
```
Starting Trading API on 0.0.0.0:5000
Database: positions.db
 * Running on http://0.0.0.0:5000
```

### Step 1.2: Test API Endpoints from VPS Terminal

In another SSH window, test each endpoint:

```bash
# Health check
curl http://localhost:5000/api/health

# Get positions
curl http://localhost:5000/api/positions | jq .

# Get market regime
curl http://localhost:5000/api/market-regime | jq .

# Get today's trades
curl http://localhost:5000/api/trades-today | jq .

# Get scanner status
curl http://localhost:5000/api/scanner-status | jq .

# Get logs
curl http://localhost:5000/api/logs/tail | jq '.data.logs[]'
```

All should return `"status":"ok"` in the JSON.

### Step 1.3: Make API Server Persistent (systemd)

So the API keeps running after you log out:

```bash
# Create systemd service file
sudo nano /etc/systemd/system/trading-api.service
```

Copy this content (adjust paths and user):

```ini
[Unit]
Description=Trading Bot API Server
After=network.target
Wants=trading-bot.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/Projekte/PycharmProjects/AI_TRADING
ExecStart=/usr/bin/python3 /home/your-username/Projekte/PycharmProjects/AI_TRADING/api_server.py
Environment="PYTHONUNBUFFERED=1"
Restart=always
RestartSec=5

StandardOutput=append:/var/log/trading-api.log
StandardError=append:/var/log/trading-api.log

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-api
sudo systemctl start trading-api

# Check status
sudo systemctl status trading-api

# Watch logs
sudo journalctl -u trading-api -f
```

### Step 1.4: Find Your VPS IP

You'll need this for the Mac app:

```bash
# Public IP (what Mac sees from outside)
curl ifconfig.me

# Or
hostname -I
```

Make note of this — you'll enter it in the Mac app settings.

---

## Part 2: Mac Setup

### Step 2.1: Open Xcode

1. Launch Xcode
2. Create new macOS App project:
   - Product Name: `Trading Dashboard`
   - Language: Swift
   - SwiftUI selected
   - Save in your preferred location

### Step 2.2: Add Swift Files

In Xcode:
1. Right-click on project in sidebar
2. Add Files to "Trading Dashboard"
3. Select these files from `mac_dashboard/`:
   - `TradingBotAPI.swift`
   - `ContentView.swift`
   - `TradingDashboardApp.swift`

Make sure they're added to the right target.

### Step 2.3: Replace App.swift

Xcode creates a default `App.swift`. Replace it with `TradingDashboardApp.swift`:

1. Delete the auto-generated `TradingDashboardApp.swift` (or rename to backup)
2. Use the one from `mac_dashboard/TradingDashboardApp.swift`

### Step 2.4: Build and Run

```bash
# In Xcode
Product → Run (Cmd+R)
```

The app should launch. You'll see "🔴 Disconnected" because you haven't configured the VPS IP yet.

---

## Part 3: Connect Mac to VPS

### Step 3.1: Configure VPS Address

In the app:
1. Click the ⚙️ gear icon (top right)
2. Enter your VPS public IP (from Step 1.4)
3. Enter port `5000` (default)
4. Click "Save"

The app will test the connection. You should see:
- 🟢 Connected in the header
- Market regime card populates (BULL/BEAR/NEUTRAL)
- Positions table shows open trades
- Portfolio stats update

### Step 3.2: Test Full Data Flow

Wait 60 seconds for the first refresh (or close/reopen app to refresh immediately).

Check all sections populate:

✓ Market Regime Card — shows regime and VIX  
✓ Portfolio Stats — shows count, P&L, win rate  
✓ Positions Table — lists open trades  
✓ Today's Trades — shows trades opened today  
✓ Scanner Status — shows last scan time  
✓ Live Logs — shows last 50 log lines  

---

## Part 4: Test Features

### Test: Manual Scan Trigger

1. Click "Scan Now" button in Scanner Status
2. App shows "Scan triggered (results in 30-60s)"
3. Check VPS logs:
   ```bash
   sudo journalctl -u trading-api -f
   ```
   Should see: `[INFO] Manual scan completed: X setups found`

### Test: Live P&L Updates

1. Open a new position via the bot (or let it trade normally)
2. Watch the app — positions update every 60 seconds
3. P&L should change as price moves

### Test: Connection Loss

1. Stop the API server: `sudo systemctl stop trading-api`
2. App shows 🔴 Disconnected and error banner
3. Restart server: `sudo systemctl start trading-api`
4. Wait 60s or refresh — should reconnect

---

## Troubleshooting

### Problem: "Cannot connect to trading bot"

**Checklist:**
- [ ] API server running on VPS: `sudo systemctl status trading-api`
- [ ] Correct IP in app settings (not `localhost`)
- [ ] Correct port (default `5000`)
- [ ] VPS firewall allows port 5000:
  ```bash
  sudo ufw allow 5000
  ```
- [ ] Test from Mac terminal:
  ```bash
  curl http://YOUR_VPS_IP:5000/api/health
  ```

### Problem: API returns error

Check VPS logs:
```bash
sudo journalctl -u trading-api -n 50
```

Common issues:
- `positions.db` doesn't exist → run bot once to create it
- Missing Python modules → `pip install flask`
- Permissions → ensure user has read access to `positions.db`

### Problem: App shows old data (not updating)

1. Close and reopen app
2. Or click settings ⚙️ to force reconnect
3. Check VPS is still running: `sudo systemctl status trading-api`

### Problem: "Scan Now" doesn't work

1. Check bot can still run:
   ```bash
   python3 -c "from DEF_SCANNER_MODE import run_scanner_mode; print('OK')"
   ```
2. Check universe files exist:
   ```bash
   ls -la universes/
   ```
3. Check bot has access to positions.db (write permission)

---

## Optional: Refinements

### HTTPS Encryption (Production)

If you want encrypted API calls:

1. Generate self-signed cert on VPS:
   ```bash
   openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365
   ```

2. Modify `api_server.py`:
   ```python
   app.run(host="0.0.0.0", port=5000, ssl_context=('cert.pem', 'key.pem'))
   ```

3. In Mac app, update `baseURL` to use `https://` instead of `http://`

### Custom Refresh Interval

Edit `TradingBotAPI.swift`, change:
```swift
init(vpsIP: String = "localhost", vpsPort: Int = 5000, refreshInterval: TimeInterval = 60)
```

Change `60` to desired seconds (e.g., `30` for 30-second updates).

### Dark Mode Support

Modify `ContentView.swift` colors to use `@Environment(\.colorScheme)`.

---

## Next Steps

1. ✅ API server running on VPS
2. ✅ Mac app built in Xcode
3. ✅ App connected to VPS
4. ✅ All data displaying

**You're done!** The dashboard is ready to use.

---

## Monitoring Checklist (Daily)

- [ ] API server still running: `sudo systemctl status trading-api`
- [ ] Mac app shows 🟢 Connected
- [ ] Market regime makes sense
- [ ] No errors in banner
- [ ] Positions and P&L update correctly

---

## Support

If issues persist:

1. Check all logs:
   ```bash
   # VPS API logs
   sudo journalctl -u trading-api -n 100
   
   # Bot logs
   tail -f trading_bot.log
   ```

2. Test API directly:
   ```bash
   curl -s http://vps-ip:5000/api/positions | python3 -m json.tool
   ```

3. Restart everything:
   ```bash
   sudo systemctl restart trading-api
   # Restart bot if needed
   ```

Good luck! 🚀
