#!/bin/bash
#
# Deploy Hourly Options Trading System to Linux Server
# Target: root@87.106.167.252:/opt/trading_bot/
#

set -e

SERVER="root@87.106.167.252"
REMOTE_PATH="/opt/trading_bot"
LOCAL_PATH="$(pwd)"

echo "=========================================="
echo "Deploying AI Trading System to Linux"
echo "=========================================="
echo "Local:  $LOCAL_PATH"
echo "Remote: $SERVER:$REMOTE_PATH"
echo ""

# Step 1: Backup current positions database
echo "[1/5] Backing up positions database..."
ssh $SERVER "cd $REMOTE_PATH && cp -f positions.db positions.db.backup.$(date +%Y%m%d_%H%M%S)" || true

# Step 2: Sync code to server
echo "[2/5] Syncing code files..."
ssh $SERVER "mkdir -p $REMOTE_PATH"
rsync -avz \
  --exclude='*.pyc' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='*.db' \
  "$LOCAL_PATH/" "$SERVER:$REMOTE_PATH/"

# Step 3: Install dependencies (if needed)
echo "[3/5] Ensuring Python dependencies..."
ssh $SERVER "cd $REMOTE_PATH && python3 -m pip install -q apscheduler requests dotenv flask pandas pandas-ta" || true

# Step 4: Initialize database schema
echo "[4/5] Initializing database schema..."
ssh $SERVER "cd $REMOTE_PATH && python3 -c \"
import sqlite3
conn = sqlite3.connect('trading.db')
cursor = conn.cursor()
with open('database_schema.sql', 'r') as f:
    cursor.executescript(f.read())
conn.commit()
conn.close()
print('Database initialized')
\""

# Step 5: Restart systemd services
echo "[5/5] Restarting services..."
ssh $SERVER "systemctl restart trading-scheduler.service && systemctl restart trading-api.service" || true

# Health check
echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Health Check:"
ssh $SERVER "systemctl status trading-scheduler.service --no-pager | head -3"
echo ""
echo "Last 5 log entries:"
ssh $SERVER "journalctl -u trading-scheduler.service -n 5 --no-pager" || echo "(No logs yet)"
echo ""
echo "Deployment successful! ✓"
