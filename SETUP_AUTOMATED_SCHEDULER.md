# Automated Trading Scheduler Setup – Linux VPS

Dieses Dokument beschreibt, wie du den Trading-Scheduler auf deinem Linux VPS einrichtest, damit er 24/7 läuft und automatisch:
- **Täglich beim US-Marktöffnung (9:31 ET)** Symbole scannt
- **Täglich nach Marktschluss (21:00 UTC)** Backtest durchführt
- **Positions-Monitor** im Hintergrund läuft (Stop-Loss/Take-Profit Überwachung)

---

## 1. Installation auf Linux VPS (einmalig)

### 1.1 SSH auf VPS verbinden
```bash
ssh root@87.106.167.252
# oder mit SSH-Schlüssel
ssh -i /path/to/key root@87.106.167.252
```

### 1.2 Repository klonen / Code synchronisieren
```bash
cd /opt/trading_bot
# Falls noch nicht vorhanden:
git clone https://github.com/yourusername/ai-trading.git .
# Falls bereits vorhanden:
git pull origin main
```

### 1.3 Dependencies installieren
```bash
cd /opt/trading_bot
pip3 install -r requirements.txt
# oder manuell:
pip3 install apscheduler pandas pandas-ta yfinance python-dotenv
```

### 1.4 .env Datei erstellen
```bash
cp .env.sample .env
# Dann mit deinem Editor bearbeiten:
nano .env
```

**Wichtige .env Einstellungen:**
```bash
# Alpaca Paper Trading (empfohlen für Test)
APCA_API_KEY_ID=your_alpaca_key
APCA_API_SECRET_KEY=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Account
ACCOUNT_SIZE=100000
MAX_RISK_PER_TRADE=0.01
BROKER_PREFERENCE=alpaca

# Scheduler
SCHEDULER_MARKETS=US
SCHEDULER_UNIVERSE=sp500
SCHEDULER_TIMEFRAME=1D
SCHEDULER_AUTO_EXECUTE=1          # 1 = echte Paper-Orders senden
SCHEDULER_FLATTEN_INTRADAY=0

# Backtesting (läuft täglich um 21:00 UTC)
BACKTEST_ENABLED=1
BACKTEST_HOUR=21
BACKTEST_MINUTE=0
BACKTEST_SYMBOLS=AAPL,MSFT,GOOGL,NVDA,TSLA
```

---

## 2. Scheduler als systemd Service einrichten

### 2.1 Systemd Service-Datei erstellen
```bash
sudo nano /etc/systemd/system/trading-scheduler.service
```

**Inhalt der Datei:**
```ini
[Unit]
Description=AI Trading Scheduler (24/7 Autonomous Trading Bot)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading_bot
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 /opt/trading_bot/scheduler.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=trading-scheduler

[Install]
WantedBy=multi-user.target
```

### 2.2 Service aktivieren und starten
```bash
# Systemd neu laden
sudo systemctl daemon-reload

# Service beim Boot aktivieren
sudo systemctl enable trading-scheduler

# Service starten
sudo systemctl start trading-scheduler

# Status prüfen
sudo systemctl status trading-scheduler

# Logs anschauen (live)
sudo journalctl -u trading-scheduler -f
```

---

## 3. Backtesting-Ergebnisse abrufen

Die Backtest-Ergebnisse werden täglich um 21:00 UTC in Dateien gespeichert:

```bash
# Logs anschauen
cd /opt/trading_bot
ls -lh logs/backtest_*.txt

# Letzte Backtest-Ergebnisse anzeigen
cat logs/backtest_*.txt | tail -100
```

Beispiel-Output:
```
Backtest Report – 2026-04-22T21:00:15.123456

AAPL:
  Trades: 28 | Win Rate: 57.1%
  Return: +15.32% | Final Equity: €115,320.00
  Profit Factor: 1.89 | Sharpe: 1.456
  Max Drawdown: 8.45% | Avg Win: €412.50

MSFT:
  Trades: 22 | Win Rate: 54.5%
  Return: +12.75% | Final Equity: €112,750.00
  ...
```

---

## 4. Überwachung und Diagnostik

### 4.1 Service-Status prüfen
```bash
systemctl status trading-scheduler
systemctl is-active trading-scheduler
```

### 4.2 Letzte 50 Zeilen von Logs anschauen
```bash
journalctl -u trading-scheduler -n 50
```

### 4.3 Nur Fehler filtern
```bash
journalctl -u trading-scheduler -p err
```

### 4.4 Logs für einen bestimmten Zeitraum
```bash
# Heute
journalctl -u trading-scheduler --since today

# Letzte Stunde
journalctl -u trading-scheduler --since "1 hour ago"

# Spezifisches Datum
journalctl -u trading-scheduler --since "2026-04-22 00:00:00"
```

---

## 5. Service-Verwaltung

### Service neu starten
```bash
sudo systemctl restart trading-scheduler
```

### Service stoppen
```bash
sudo systemctl stop trading-scheduler
```

### Service deaktivieren (nicht mehr beim Boot starten)
```bash
sudo systemctl disable trading-scheduler
```

### Logs anschauen und in Datei speichern
```bash
journalctl -u trading-scheduler > scheduler_logs.txt
```

---

## 6. Konfiguration anpassen (ohne Neustart)

Falls du die .env-Datei änderst (z.B. andere Symbole, andere Backtestzeit):

```bash
# .env bearbeiten
nano /opt/trading_bot/.env

# Service neu starten (lädt neue Config)
sudo systemctl restart trading-scheduler

# Status prüfen
sudo systemctl status trading-scheduler
```

---

## 7. Troubleshooting

### Problem: Service läuft nicht
```bash
# Status prüfen
systemctl status trading-scheduler

# Letzte Fehler anschauen
journalctl -u trading-scheduler -n 100

# Manuell starten um Fehler zu sehen
python3 /opt/trading_bot/scheduler.py
```

### Problem: Backtest lädt keine Daten
- Prüfe Internetverbindung: `ping -c 1 8.8.8.8`
- Prüfe yfinance: `python3 -c "import yfinance; yf.Ticker('AAPL').history(period='1d')"`
- Prüfe logs: `journalctl -u trading-scheduler | grep -i backtest`

### Problem: Positionen werden nicht gescannt
- Prüfe Broker-API-Schlüssel in .env
- Prüfe SCHEDULER_AUTO_EXECUTE (sollte 0 oder 1 sein)
- Logs anschauen: `journalctl -u trading-scheduler | grep -i scan`

---

## 8. Cronjob Alternative (wenn systemd nicht möglich)

Falls systemd nicht verfügbar ist, kannst du auch einen cron-Job verwenden:

```bash
# Crontab öffnen
crontab -e

# Folgende Zeile hinzufügen (täglich um 21:00 UTC):
0 21 * * * /usr/bin/python3 /opt/trading_bot/scheduler.py >> /opt/trading_bot/logs/cron_scheduler.log 2>&1
```

---

## 9. Performance-Überwachung

### Ressourcennutzung prüfen
```bash
# CPU und Memory anschauen
ps aux | grep scheduler

# Python-Prozess-Details
ps aux | grep python3 | grep scheduler
```

### Diskplatz für Logs prüfen
```bash
du -sh /opt/trading_bot/logs/
df -h
```

### Logs rotieren (ältere Logs archivieren)
```bash
# Alle Logs älter als 30 Tage löschen
find /opt/trading_bot/logs -name "backtest_*.txt" -mtime +30 -delete
```

---

## 10. Remote Zugriff zur Überwachung

Du kannst von deinem Mac aus die Logs anschauen:

```bash
# Von deinem Mac:
ssh root@87.106.167.252 "journalctl -u trading-scheduler -n 50"

# Oder Backtest-Ergebnisse abrufen:
scp root@87.106.167.252:/opt/trading_bot/logs/backtest_*.txt ~/Desktop/
```

---

## Nächste Schritte

1. **Scheduler starten:** `systemctl start trading-scheduler`
2. **Logs überwachen:** `journalctl -u trading-scheduler -f`
3. **Backtest-Ergebnisse anschauen:** `cat logs/backtest_*.txt`
4. **Bei Bedarf anpassen:** .env bearbeiten und `systemctl restart` durchführen

Dein Bot läuft dann 24/7 automatisch! 🚀
