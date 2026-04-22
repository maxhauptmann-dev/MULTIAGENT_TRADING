#!/bin/bash
# setup_scheduler.sh – Automated Trading Scheduler Setup für Linux VPS
#
# Verwendung:
#   chmod +x setup_scheduler.sh
#   sudo ./setup_scheduler.sh

set -e  # Exit on any error

echo "================================"
echo "Trading Scheduler Setup"
echo "================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
   echo "Fehler: Dieses Skript muss mit sudo ausgeführt werden"
   exit 1
fi

# 1. Create working directory
echo ""
echo "1/5: Erstelle Verzeichnisse..."
mkdir -p /opt/trading_bot
mkdir -p /opt/trading_bot/logs
echo "✓ Verzeichnisse erstellt"

# 2. Install Python dependencies
echo ""
echo "2/5: Installiere Python-Abhängigkeiten..."
pip3 install -q apscheduler pandas pandas-ta yfinance python-dotenv 2>/dev/null || {
    pip3 install --break-system-packages -q apscheduler pandas pandas-ta yfinance python-dotenv
}
echo "✓ Dependencies installiert"

# 3. Copy .env.sample to .env if not exists
echo ""
echo "3/5: Konfiguriere .env..."
if [ -f "/opt/trading_bot/.env" ]; then
    echo "⚠ .env existiert bereits – überspringe"
else
    cp /opt/trading_bot/.env.sample /opt/trading_bot/.env
    echo "✓ .env erstellt (bitte noch Alpaca-Schlüssel eintragen!)"
    echo "  Bearbeite: nano /opt/trading_bot/.env"
fi

# 4. Create systemd service
echo ""
echo "4/5: Erstelle systemd Service..."
cat > /etc/systemd/system/trading-scheduler.service << 'EOF'
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
EOF

systemctl daemon-reload
systemctl enable trading-scheduler
echo "✓ systemd Service erstellt und aktiviert"

# 5. Start service
echo ""
echo "5/5: Starte Service..."
systemctl start trading-scheduler
sleep 2

if systemctl is-active --quiet trading-scheduler; then
    echo "✓ Service läuft!"
else
    echo "⚠ Service konnte nicht gestartet werden"
    echo "  Prüfe: journalctl -u trading-scheduler -n 20"
fi

# Summary
echo ""
echo "================================"
echo "Setup abgeschlossen! ✓"
echo "================================"
echo ""
echo "Nächste Schritte:"
echo "1. Bearbeite .env mit deinen Alpaca-Schlüsseln:"
echo "   nano /opt/trading_bot/.env"
echo ""
echo "2. Prüfe Logs:"
echo "   journalctl -u trading-scheduler -f"
echo ""
echo "3. Backtest-Ergebnisse anschauen:"
echo "   tail -100 /opt/trading_bot/logs/backtest_*.txt"
echo ""
echo "Service-Kommandos:"
echo "  systemctl status trading-scheduler"
echo "  systemctl restart trading-scheduler"
echo "  systemctl stop trading-scheduler"
echo ""
echo "Mehr Infos: SETUP_AUTOMATED_SCHEDULER.md"
echo ""
