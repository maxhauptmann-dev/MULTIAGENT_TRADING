"""
position_monitor.py

Verwaltet offene Positionen in SQLite und schließt sie automatisch
wenn Stop-Loss oder Take-Profit erreicht wird.

Preisquellen (Fallback-Kette):
  1. Finnhub /quote  (FINNHUB_API_KEY)
  2. Alpaca Data API (ALPACA_API_KEY + ALPACA_API_SECRET)
"""

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("PositionMonitor")

DB_PATH = os.getenv("POSITION_DB_PATH", "positions.db")
TRAILING_ATR_MULT = float(os.getenv("TRAILING_STOP_ATR_MULT", "2.0"))

# ── DB-Helpers ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Neue Verbindung pro Aufruf – thread-safe."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol           TEXT    NOT NULL,
                direction        TEXT    NOT NULL,
                entry_price      REAL,
                quantity         REAL    NOT NULL,
                stop_loss        REAL,
                take_profit      REAL,
                instrument_type  TEXT    DEFAULT 'stock',
                broker           TEXT    DEFAULT 'ibkr',
                opened_at        TEXT    NOT NULL,
                status           TEXT    DEFAULT 'open',
                close_price      REAL,
                closed_at        TEXT,
                pnl              REAL,
                trade_plan_json  TEXT,
                highest_price    REAL,
                lowest_price     REAL,
                atr_14           REAL,
                atr_multiplier_used REAL,
                kelly_fraction_used REAL,
                profit_locked_at_pct REAL,
                correlation_check_json TEXT
            )
        """)

        # New tables for V3 Risk Management
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                daily_high_water_mark REAL,
                monthly_high_water_mark REAL,
                drawdown_status TEXT DEFAULT 'open',
                drawdown_triggered_at TIMESTAMP,
                status_reset_at TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS correlation_matrix (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol_a TEXT NOT NULL,
                symbol_b TEXT NOT NULL,
                correlation REAL,
                calculated_at TIMESTAMP,
                UNIQUE(symbol_a, symbol_b)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT,
                decision TEXT,
                details TEXT,
                outcome TEXT
            )
        """)

        # Migration: Add missing columns if they don't exist
        migration_cols = [
            ("highest_price", "REAL"),
            ("lowest_price", "REAL"),
            ("atr_14", "REAL"),
            ("atr_multiplier_used", "REAL"),
            ("kelly_fraction_used", "REAL"),
            ("profit_locked_at_pct", "REAL"),
            ("correlation_check_json", "TEXT"),
            ("quantity_remaining", "REAL"),
            ("profit_levels_hit", "TEXT"),
            ("last_profit_pct", "REAL"),
            ("highest_locked_profit_pct", "REAL"),
            ("profit_lock_levels", "TEXT")
        ]
        for col, typedef in migration_cols:
            try:
                conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {typedef}")
            except Exception:
                pass

        conn.commit()


# ── PositionMonitor ───────────────────────────────────────────────────────────

class PositionMonitor:
    """
    Kernklasse:
      open_position()  – beim Trade-Entry aufrufen
      check_positions() – prüft SL/TP aller offenen Positionen
      close_position() – schließt Position via ExecutionAgent + DB-Update
      start() / stop() – Hintergrund-Thread
      stats()          – P&L-Übersicht
    """

    def __init__(
        self,
        execution_agent,
        circuit_breaker=None,
        check_interval_seconds: int = 60,
        hard_stop_loss_pct: float = 0.05,
    ) -> None:
        self.execution_agent = execution_agent
        self.circuit_breaker = circuit_breaker
        self.check_interval = check_interval_seconds
        self.hard_stop_loss_pct = hard_stop_loss_pct  # 5% default hard stop
        self._finnhub_key = os.getenv("FINNHUB_API_KEY")
        self._alpaca_key = os.getenv("ALPACA_API_KEY")
        self._alpaca_secret = os.getenv("ALPACA_API_SECRET")
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        _init_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def open_position(
        self,
        trade_plan: Dict[str, Any],
        execution_result: Dict[str, Any],
    ) -> Optional[int]:
        """
        Nach erfolgreicher Execution aufrufen.
        Gibt die neue Position-ID zurück oder None.
        """
        if not isinstance(trade_plan, dict):
            return None
        if trade_plan.get("action") != "open_position":
            return None
        if not isinstance(execution_result, dict):
            return None
        if execution_result.get("status") not in {"sent", "simulated"}:
            return None

        symbol = trade_plan.get("symbol")
        direction = (trade_plan.get("direction") or "long").lower()
        entry_price = (trade_plan.get("entry") or {}).get("trigger_price")
        sl = (trade_plan.get("stop_loss") or {}).get("price")
        tp = (trade_plan.get("take_profit") or {}).get("target_price")
        qty = float((trade_plan.get("position_sizing") or {}).get("contracts_or_shares") or 0)
        instrument_type = (trade_plan.get("instrument_type") or "stock").lower()
        broker = execution_result.get("broker", "ibkr")
        atr_14 = trade_plan.get("_atr_14")

        if not symbol or qty <= 0:
            return None

        now = datetime.now(timezone.utc).isoformat()
        try:
            with _connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO positions
                      (symbol, direction, entry_price, quantity, stop_loss, take_profit,
                       instrument_type, broker, opened_at, status, trade_plan_json,
                       highest_price, atr_14)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (symbol, direction, entry_price, qty, sl, tp,
                     instrument_type, broker, now, "open", json.dumps(trade_plan),
                     entry_price, atr_14),
                )
                conn.commit()
                pid = cur.lastrowid

            logger.info(
                "[PositionMonitor] #%d eröffnet: %s %s x%.2f | SL=%.4f TP=%.4f",
                pid, direction.upper(), symbol, qty, sl or 0, tp or 0,
            )
            return pid
        except Exception as exc:
            logger.error("[PositionMonitor] open_position Fehler: %s", exc)
            return None

    def close_position(
        self,
        position_id: int,
        reason: str,
        close_price: float,
    ) -> Dict[str, Any]:
        """
        Schließt eine offene Position.
        reason: 'stop_loss' | 'take_profit' | 'manual'
        """
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE id=? AND status='open'",
                (position_id,),
            ).fetchone()

        if not row:
            return {"status": "not_found", "position_id": position_id}

        pos = dict(row)

        # Richtung umkehren um Position zu schließen:
        # Long-Position schließen = SELL → direction "short" durch ExecutionAgent
        close_direction = "short" if pos["direction"] == "long" else "long"
        close_plan = {
            "action": "close_position",
            "symbol": pos["symbol"],
            "direction": close_direction,
            "instrument_type": pos["instrument_type"],
            "position_sizing": {"contracts_or_shares": pos["quantity"]},
            "order_type": "MKT",
        }
        exec_result = self.execution_agent.execute_trade_plan(close_plan, pos["broker"])

        # P&L berechnen
        entry = float(pos.get("entry_price") or 0.0)
        qty = float(pos.get("quantity") or 0.0)
        pnl = (close_price - entry) * qty if pos["direction"] == "long" \
              else (entry - close_price) * qty

        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                """
                UPDATE positions
                SET status=?, close_price=?, closed_at=?, pnl=?
                WHERE id=?
                """,
                (f"closed_{reason}", close_price, now, round(pnl, 4), position_id),
            )
            conn.commit()

        logger.info(
            "[PositionMonitor] #%d geschlossen (%s): %s @ %.4f | P&L: %+.2f",
            position_id, reason.upper(), pos["symbol"], close_price, pnl,
        )

        if self.circuit_breaker and pnl < 0:
            self.circuit_breaker.record_loss()

        return {
            "status": "closed",
            "position_id": position_id,
            "symbol": pos["symbol"],
            "reason": reason,
            "pnl": round(pnl, 4),
            "exec_result": exec_result,
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def check_positions(self) -> List[Dict[str, Any]]:
        """
        Prüft alle offenen Positionen gegen SL/TP mit adaptiven Trailing Stops.
        Nutzt VIX-basierte ATR Multiplikatoren und Profit Lock-In.
        """
        from DEF_INDICATORS import get_vix_level, get_adaptive_atr_multiplier

        open_pos = self.get_open_positions()
        if not open_pos:
            return []

        # Get VIX once per check cycle
        vix_level = get_vix_level()
        atr_mult_adaptive = get_adaptive_atr_multiplier(vix_level)

        actions: List[Dict[str, Any]] = []
        for pos in open_pos:
            symbol = pos["symbol"]
            price = self._get_price(symbol)
            if price is None:
                logger.warning("[PositionMonitor] Kein Preis für %s – überspringe.", symbol)
                continue

            direction = pos["direction"]
            pid = pos["id"]
            entry = float(pos.get("entry_price") or 0.0)
            tp = pos.get("take_profit")
            atr_14 = pos.get("atr_14")
            reason = None

            # ── HARD STOP-LOSS CHECK (5% Verlust-Limit) ──────────────────────
            if entry > 0:
                if direction == "long":
                    loss_pct = (entry - price) / entry
                    if loss_pct >= self.hard_stop_loss_pct:
                        reason = "hard_stop_loss"
                else:  # short
                    loss_pct = (price - entry) / entry
                    if loss_pct >= self.hard_stop_loss_pct:
                        reason = "hard_stop_loss"

            if reason == "hard_stop_loss":
                result = self.close_position(pid, reason, price)
                actions.append(result)
                continue  # Skip weitere Checks für diese Position

            # ── Trailing Stop mit adaptivem ATR Multiplikator (Swing Trading) ─
            if atr_14 and float(atr_14) > 0:
                # For swing trading: use tighter multiplier (1.2x instead of 1.5-3.0x)
                trailing_mult = 1.2

                if direction == "long":
                    # Update highest price for long positions
                    highest = float(pos.get("highest_price") or entry or price)
                    if price > highest:
                        highest = price
                        with _connect() as conn:
                            conn.execute(
                                "UPDATE positions SET highest_price=? WHERE id=?",
                                (highest, pid),
                            )
                            conn.commit()

                    # Calculate trailing SL (tight for swing trading)
                    trailing_sl = highest - (trailing_mult * float(atr_14))

                    # ── AGGRESSIVE Profit Lock-In with Ratchet (Swing Trading) ─────
                    profit_pct = (price - entry) / entry if entry > 0 else 0
                    peak_price = highest

                    # Profit ratchet levels: 10%, 12%, 15%, 18%
                    profit_lock_levels = [0.10, 0.12, 0.15, 0.18]
                    highest_locked = float(pos.get("highest_locked_profit_pct") or 0.0)

                    # Update locked profit levels if new milestone reached
                    for level in profit_lock_levels:
                        if profit_pct >= level and level > highest_locked:
                            highest_locked = level
                            with _connect() as conn:
                                conn.execute(
                                    "UPDATE positions SET highest_locked_profit_pct=? WHERE id=?",
                                    (highest_locked, pid),
                                )
                                conn.commit()
                            logger.info(
                                "[PositionMonitor] #%d locked profit at +%.1f%% (%s)",
                                pid, level*100, symbol
                            )

                    # KEY FEATURE: Ratchet stop - if profit falls below locked level, close
                    if highest_locked > 0 and profit_pct < highest_locked:
                        sl = price + 0.01
                        reason = "profit_ratchet_breach"
                    else:
                        trailing_sl = highest - (trailing_mult * float(atr_14))
                        sl = trailing_sl
                        reason = None
                else:  # short
                    # Update lowest price for short positions
                    lowest = float(pos.get("lowest_price") or entry or price)
                    if price < lowest:
                        lowest = price
                        with _connect() as conn:
                            conn.execute(
                                "UPDATE positions SET lowest_price=? WHERE id=?",
                                (lowest, pid),
                            )
                            conn.commit()

                    # Calculate trailing SL for shorts (tight)
                    trailing_sl = lowest + (trailing_mult * float(atr_14))

                    # ── AGGRESSIVE Profit Lock-In with Ratchet for Shorts ─────────
                    profit_pct = (entry - price) / entry if entry > 0 else 0

                    # Profit ratchet levels: 10%, 12%, 15%, 18%
                    profit_lock_levels = [0.10, 0.12, 0.15, 0.18]
                    highest_locked = float(pos.get("highest_locked_profit_pct") or 0.0)

                    # Update locked profit levels if new milestone reached
                    for level in profit_lock_levels:
                        if profit_pct >= level and level > highest_locked:
                            highest_locked = level
                            with _connect() as conn:
                                conn.execute(
                                    "UPDATE positions SET highest_locked_profit_pct=? WHERE id=?",
                                    (highest_locked, pid),
                                )
                                conn.commit()
                            logger.info(
                                "[PositionMonitor] #%d locked profit at +%.1f%% (%s)",
                                pid, level*100, symbol
                            )

                    # KEY FEATURE: Ratchet stop - if profit falls below locked level, close
                    if highest_locked > 0 and profit_pct < highest_locked:
                        sl = price - 0.01
                        reason = "profit_ratchet_breach"
                    else:
                        trailing_sl = lowest + (trailing_mult * float(atr_14))
                        sl = trailing_sl
                        reason = None

                # Store adaptive multiplier used
                with _connect() as conn:
                    conn.execute(
                        "UPDATE positions SET atr_multiplier_used=? WHERE id=?",
                        (trailing_mult, pid),
                    )
                    conn.commit()
            else:
                sl = pos.get("stop_loss")

            # ── SL/TP Check ──────────────────────────────────────────────────
            if direction == "long":
                if sl is not None and price <= float(sl):
                    reason = "trailing_stop" if atr_14 else "stop_loss"
                elif tp is not None and price >= float(tp):
                    reason = "take_profit"
            else:  # short
                if sl is not None and price >= float(sl):
                    reason = "trailing_stop" if atr_14 else "stop_loss"
                elif tp is not None and price <= float(tp):
                    reason = "take_profit"

            if reason:
                result = self.close_position(pid, reason, price)
                actions.append(result)

        return actions

    def close_all_open(self, reason: str = "manual") -> List[Dict[str, Any]]:
        """Schließt alle offenen Positionen (z.B. vor Börsenschluss)."""
        results: List[Dict[str, Any]] = []
        for pos in self.get_open_positions():
            price = self._get_price(pos["symbol"])
            if price is None:
                logger.warning("[PositionMonitor] Kein Preis für %s – überspringe.", pos["symbol"])
                continue
            result = self.close_position(pos["id"], reason, price)
            results.append(result)
        return results

    def stats(self) -> Dict[str, Any]:
        """Gibt Überblick über alle Trades und P&L."""
        with _connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            open_cnt = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='open'"
            ).fetchone()[0]
            tp_cnt = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='closed_take_profit'"
            ).fetchone()[0]
            sl_cnt = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='closed_stop_loss'"
            ).fetchone()[0]
            total_pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) FROM positions WHERE pnl IS NOT NULL"
            ).fetchone()[0]

        closed = tp_cnt + sl_cnt
        return {
            "total_trades": total,
            "open": open_cnt,
            "closed_take_profit": tp_cnt,
            "closed_stop_loss": sl_cnt,
            "total_pnl": round(float(total_pnl), 2),
            "win_rate": round(tp_cnt / closed, 3) if closed > 0 else None,
        }

    # ── Background-Thread ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("[PositionMonitor] Läuft bereits.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="PositionMonitor"
        )
        self._thread.start()
        logger.info("[PositionMonitor] Gestartet (Intervall: %ds).", self.check_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        logger.info("[PositionMonitor] Gestoppt.")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                actions = self.check_positions()
                if actions:
                    logger.info(
                        "[PositionMonitor] %d Position(en) geschlossen: %s",
                        len(actions),
                        [(a["symbol"], a["reason"], a["pnl"]) for a in actions],
                    )
            except Exception as exc:
                logger.error("[PositionMonitor] Fehler im Check-Loop: %s", exc)
            self._stop_event.wait(self.check_interval)

    # ── Preisfetcher ──────────────────────────────────────────────────────────

    def _get_price(self, symbol: str) -> Optional[float]:
        """Finnhub → Alpaca → yfinance (fallback)."""
        # 1) Finnhub
        if self._finnhub_key:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": self._finnhub_key},
                    timeout=5,
                )
                if resp.ok:
                    price = resp.json().get("c")
                    if price and float(price) > 0:
                        return float(price)
            except Exception:
                pass

        # 2) Alpaca
        if self._alpaca_key and self._alpaca_secret:
            try:
                resp = requests.get(
                    f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
                    headers={
                        "APCA-API-KEY-ID": self._alpaca_key,
                        "APCA-API-SECRET-KEY": self._alpaca_secret,
                    },
                    timeout=5,
                )
                if resp.ok:
                    price = resp.json().get("quote", {}).get("ap")
                    if price and float(price) > 0:
                        return float(price)
            except Exception:
                pass

        # 3) yfinance (fallback für autonome VPS operation)
        try:
            import yfinance as yf
            df = yf.download(symbol, period="1d", progress=False, timeout=10)
            if not df.empty:
                last_close = df["Close"].iloc[-1]
                price = float(last_close) if last_close is not None else None
                if price and price > 0:
                    return price
        except Exception:
            pass

        return None


# ── Modul-Singleton (wird von anderen Modulen importiert) ─────────────────────
# Wird erst nach Erstellung des ExecutionAgent befüllt – siehe trading_agents_with_gpt.py
monitor: Optional[PositionMonitor] = None
