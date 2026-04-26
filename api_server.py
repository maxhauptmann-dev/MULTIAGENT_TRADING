"""
api_server.py

Lightweight Flask API for Mac dashboard.
Serves trading bot data from positions.db and logs.

Run: python3 api_server.py
Or via systemd: systemctl start trading-api
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Dict, Any, List, Optional

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logger = logging.getLogger("TradingAPI")
logging.basicConfig(level=logging.INFO)

DB_PATH = os.getenv("POSITION_DB_PATH", "positions.db")
API_PORT = int(os.getenv("FLASK_API_PORT", "5000"))
LOG_PATH = os.getenv("LOG_PATH", "trading_bot.log")

# ── Helpers ────────────────────────────────────────────────────────────────

def _connect_db():
    """Thread-safe SQLite connection."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _json_response(data: Any, status: str = "ok") -> dict:
    """Standard API response format."""
    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data
    }


def _get_current_price(symbol: str) -> Optional[float]:
    """Fetch current price via yfinance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"Could not fetch price for {symbol}: {e}")
    return None


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/api/positions", methods=["GET"])
def get_positions():
    """GET /api/positions - Open positions with live P&L."""
    try:
        conn = _connect_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, symbol, direction, entry_price, quantity, stop_loss, take_profit,
                opened_at, highest_price, atr_14, highest_locked_profit_pct
            FROM positions
            WHERE status = 'open'
            ORDER BY opened_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()

        positions = []
        for row in rows:
            symbol = row["symbol"]
            current_price = _get_current_price(symbol)

            if current_price is None:
                continue  # Skip if we can't fetch price

            entry = float(row["entry_price"])
            qty = float(row["quantity"])
            direction = row["direction"]

            if direction == "long":
                pnl_dollar = (current_price - entry) * qty
                pnl_pct = ((current_price - entry) / entry * 100) if entry > 0 else 0
            else:  # short
                pnl_dollar = (entry - current_price) * qty
                pnl_pct = ((entry - current_price) / entry * 100) if entry > 0 else 0

            highest_locked = float(row["highest_locked_profit_pct"]) if row["highest_locked_profit_pct"] else None

            # Calculate hard stop loss (-5%) if not explicitly set
            hard_sl = entry * 0.95 if entry > 0 else None

            positions.append({
                "symbol": symbol,
                "direction": direction,
                "entry_price": round(entry, 2),
                "quantity": qty,
                "current_price": round(current_price, 2),
                "pnl_dollar": round(pnl_dollar, 2),
                "pnl_percent": round(pnl_pct, 2),
                "stop_loss": float(row["stop_loss"]) if row["stop_loss"] else None,
                "take_profit": float(row["take_profit"]) if row["take_profit"] else None,
                "hard_stop_loss": round(hard_sl, 2) if hard_sl else None,
                "opened_at": row["opened_at"],
                "highest_price": float(row["highest_price"]) if row["highest_price"] else current_price,
                "atr_14": float(row["atr_14"]) if row["atr_14"] else None,
                "highest_locked_profit_pct": round(highest_locked * 100, 1) if highest_locked else None,
            })

        return jsonify(_json_response({"positions": positions}))

    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/market-regime", methods=["GET"])
def get_market_regime():
    """GET /api/market-regime - Current market regime (bull/bear/neutral) + VIX."""
    try:
        from DEF_INDICATORS import compute_market_regime
        regime_data = compute_market_regime()

        return jsonify(_json_response({
            "regime": regime_data.get("regime", "neutral"),
            "spy_vs_ema20_pct": regime_data.get("spy_vs_ema20", 0.0),
            "qqq_vs_ema20_pct": regime_data.get("qqq_vs_ema20", 0.0),
            "vix": regime_data.get("vix", 20.0),
        }))

    except Exception as e:
        logger.error(f"Error fetching market regime: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/trades-today", methods=["GET"])
def get_trades_today():
    """GET /api/trades-today - List of trades opened/closed today."""
    try:
        conn = _connect_db()
        cursor = conn.cursor()

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        cursor.execute("""
            SELECT
                symbol, direction, entry_price, quantity, stop_loss, take_profit,
                opened_at, closed_at, pnl, close_price, trade_plan_json
            FROM positions
            WHERE DATE(opened_at) = ?
            ORDER BY opened_at DESC
            LIMIT 20
        """, (str(today),))

        rows = cursor.fetchall()
        conn.close()

        trades = []
        for row in rows:
            try:
                trade_plan = json.loads(row["trade_plan_json"]) if row["trade_plan_json"] else {}
                reason = trade_plan.get("reason", "unknown")
            except:
                reason = "unknown"

            trades.append({
                "symbol": row["symbol"],
                "direction": row["direction"],
                "entry_price": float(row["entry_price"]) if row["entry_price"] else None,
                "quantity": float(row["quantity"]),
                "opened_at": row["opened_at"],
                "closed_at": row["closed_at"],
                "close_price": float(row["close_price"]) if row["close_price"] else None,
                "pnl": float(row["pnl"]) if row["pnl"] else None,
                "reason": reason,
            })

        return jsonify(_json_response({"trades": trades}))

    except Exception as e:
        logger.error(f"Error fetching today's trades: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/scanner-status", methods=["GET"])
def get_scanner_status():
    """GET /api/scanner-status - Last scanner run info."""
    try:
        conn = _connect_db()
        cursor = conn.cursor()

        # Get count of positions opened today
        today = datetime.now().date()
        cursor.execute("""
            SELECT COUNT(*) as count FROM positions
            WHERE DATE(opened_at) = ?
        """, (str(today),))

        today_count = cursor.fetchone()["count"]

        # Get last opened position as proxy for last scan
        cursor.execute("""
            SELECT opened_at FROM positions
            WHERE status = 'open' OR status = 'closed'
            ORDER BY opened_at DESC
            LIMIT 1
        """)

        last_row = cursor.fetchone()
        conn.close()

        last_scan_time = last_row["opened_at"] if last_row else None

        return jsonify(_json_response({
            "last_scan": last_scan_time,
            "trades_opened_today": today_count,
            "status": "running"
        }))

    except Exception as e:
        logger.error(f"Error fetching scanner status: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/logs/tail", methods=["GET"])
def get_logs_tail():
    """GET /api/logs/tail - Last 50 lines of bot logs."""
    try:
        lines = []

        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "r") as f:
                all_lines = f.readlines()
                # Get last 50 lines
                lines = all_lines[-50:] if len(all_lines) > 50 else all_lines

        return jsonify(_json_response({
            "logs": [line.rstrip("\n") for line in lines]
        }))

    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/trigger-scan", methods=["POST"])
def trigger_scan():
    """POST /api/trigger-scan - Enqueue a manual scanner run."""
    try:
        # Async task: spawn scanner in background thread
        def run_scan():
            try:
                from DEF_SCANNER_MODE import run_scanner_mode
                from universe_manager import load_universe

                # Get account info (from env or defaults)
                account_info = {
                    "account_size": float(os.getenv("ACCOUNT_SIZE", "100000")),
                    "max_risk_per_trade": float(os.getenv("MAX_RISK_PER_TRADE", "0.01")),
                    "broker_preference": "alpaca",
                }

                watchlist = load_universe("sp500")  # Use default universe
                result = run_scanner_mode(
                    watchlist=watchlist,
                    account_info=account_info,
                    timeframe="1D",
                    asset_type="stock",
                    market_hint="US",
                    auto_execute=False,  # Manual scan: review before execution
                )

                logger.info(f"Manual scan completed: {len(result.get('setups', []))} setups found")

            except Exception as e:
                logger.error(f"Manual scan failed: {e}")

        # Start in background thread (don't block API response)
        scan_thread = Thread(target=run_scan, daemon=True)
        scan_thread.start()

        return jsonify(_json_response({
            "status": "scan_queued",
            "message": "Manual scan enqueued (results in 30-60s)"
        }))

    except Exception as e:
        logger.error(f"Error triggering scan: {e}")
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


@app.route("/api/health", methods=["GET"])
def health():
    """GET /api/health - Server health check."""
    try:
        conn = _connect_db()
        conn.execute("SELECT 1")
        conn.close()
        return jsonify(_json_response({"status": "healthy"}))
    except Exception as e:
        return jsonify(_json_response({"error": str(e)}, status="error")), 500


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Starting Trading API on 0.0.0.0:{API_PORT} (HTTP)")
    logger.info(f"Database: {DB_PATH}")

    app.run(host="0.0.0.0", port=API_PORT, debug=False, threaded=True)
