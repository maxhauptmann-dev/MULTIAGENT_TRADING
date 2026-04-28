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

# Dedizierter Logger für Position Events (Profit Lock, SL/TP Closes)
position_events_logger = logging.getLogger("PositionEvents")
_pos_handler = logging.FileHandler(os.getenv("POSITION_EVENTS_LOG", "position_events.log"))
_pos_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
position_events_logger.addHandler(_pos_handler)
position_events_logger.setLevel(logging.INFO)

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
                broker           TEXT    DEFAULT 'alpaca',
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

        # Options Positions Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options_positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                option_symbol   TEXT    NOT NULL,
                option_type     TEXT    NOT NULL,
                strike          REAL    NOT NULL,
                expiry          TEXT    NOT NULL,
                dte_at_entry    INTEGER,
                contracts       INTEGER NOT NULL,
                premium_paid    REAL,
                delta_at_entry  REAL,
                broker          TEXT    DEFAULT 'alpaca',
                opened_at       TEXT    NOT NULL,
                status          TEXT    DEFAULT 'open',
                close_premium   REAL,
                closed_at       TEXT,
                pnl             REAL,
                close_reason    TEXT
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
        self._alpaca_key = os.getenv("APCA_API_KEY_ID")
        self._alpaca_secret = os.getenv("APCA_API_SECRET_KEY")
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        _init_db()

    def sync_from_alpaca(self) -> int:
        """Lädt offene Positionen von Alpaca und schreibt sie in die lokale DB.
        Gibt Anzahl der synced Positionen zurück."""
        if not (self._alpaca_key and self._alpaca_secret):
            return 0

        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        headers = {
            "APCA-API-KEY-ID": self._alpaca_key,
            "APCA-API-SECRET-KEY": self._alpaca_secret,
        }

        try:
            resp = requests.get(f"{base_url}/v2/positions", headers=headers, timeout=10)
            resp.raise_for_status()
            alpaca_positions = resp.json()
        except Exception as e:
            logger.warning(f"[Alpaca Sync] Fehler: {e}")
            return 0

        synced = 0
        with _connect() as conn:
            for pos in alpaca_positions:
                symbol = pos.get("symbol", "").upper()
                if not symbol:
                    continue

                qty = abs(float(pos.get("qty", 0)))
                side = "long" if float(pos.get("qty", 0)) > 0 else "short"
                entry_price = float(pos.get("avg_entry_price", 0))

                # Prüfe ob Position schon in DB ist
                exists = conn.execute(
                    "SELECT id FROM positions WHERE symbol=? AND status=?",
                    (symbol, "open")
                ).fetchone()

                if not exists:
                    conn.execute("""
                        INSERT INTO positions
                        (symbol, direction, entry_price, quantity, broker, opened_at, status)
                        VALUES (?, ?, ?, ?, 'alpaca', ?, 'open')
                    """, (symbol, side, entry_price, qty,
                          datetime.utcnow().isoformat()))
                    synced += 1

            conn.commit()

        if synced > 0:
            logger.info(f"[Alpaca Sync] {synced} neue Positionen geladen")
        return synced

    def update_correlation_matrix(self) -> None:
        """Aktualisiert die Korrelationsmatrix basierend auf historischen Daten."""
        try:
            import yfinance as yf
            from datetime import timedelta

            # Hole alle offenen Positionen
            open_symbols = []
            with _connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT symbol FROM positions WHERE status='open'"
                ).fetchall()
            open_symbols = [r[0] for r in rows]

            if len(open_symbols) < 2:
                return

            # Lade 90 Tage Daten für alle Symbole
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=90)

            data = {}
            for symbol in open_symbols:
                try:
                    df = yf.download(symbol, start=start, end=end, progress=False)
                    if not df.empty:
                        data[symbol] = df["Close"].pct_change()
                except Exception as e:
                    logger.warning(f"[Correlation] Fehler beim Download {symbol}: {e}")
                    continue

            if len(data) < 2:
                return

            # Berechne Korrelationen
            import pandas as pd
            df_returns = pd.DataFrame(data)
            correlations = df_returns.corr()

            # Speichere in DB
            with _connect() as conn:
                for i, sym_a in enumerate(open_symbols):
                    for sym_b in open_symbols[i+1:]:
                        corr_value = float(correlations.loc[sym_a, sym_b])

                        # Upsert
                        conn.execute("""
                            INSERT OR REPLACE INTO correlation_matrix
                            (symbol_a, symbol_b, correlation, calculated_at)
                            VALUES (?, ?, ?, ?)
                        """, (sym_a, sym_b, corr_value, datetime.now(timezone.utc).isoformat()))

                conn.commit()

            logger.info(f"[Correlation] Matrix aktualisiert für {len(open_symbols)} Symbole")
        except Exception as e:
            logger.warning(f"[Correlation] Fehler: {e}")

    def _get_sector(self, symbol: str) -> str:
        """Klassifiziere Symbol nach Sektor."""
        sector_map = {
            "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
            "META": "Communication Services", "NVDA": "Technology", "AMD": "Technology",
            "ASML": "Technology", "TSLA": "Consumer Discretionary", "AMZN": "Consumer Discretionary",
            "WMT": "Consumer Staples", "PG": "Consumer Staples", "BA": "Industrials",
            "GS": "Financials", "UNH": "Healthcare",
        }
        return sector_map.get(symbol.upper(), "Other")

    def rebalance_position_sizes(self) -> None:
        """Reduziert Positionen die größer als MAX_POSITION_SIZE_PCT sind."""
        max_position_pct = float(os.getenv("MAX_POSITION_SIZE_PCT", "0.02"))  # 2%
        account_size = float(os.getenv("ACCOUNT_SIZE", "100000"))

        with _connect() as conn:
            positions = conn.execute(
                "SELECT id, symbol, quantity, entry_price, direction FROM positions WHERE status='open'"
            ).fetchall()

        if not positions:
            return

        # Total portfolio value (for percentage calculation only)
        total_value = 0
        pos_info = {}
        for pid, symbol, qty, entry, direction in positions:
            current_price = self._get_price(symbol)
            if not current_price:
                continue
            value = qty * current_price
            total_value += value
            pos_info[(pid, symbol)] = (qty, entry, direction, current_price, value)

        if total_value == 0:
            return

        # Check each position: 2% of ACCOUNT SIZE, not current portfolio value
        max_value_per_position = account_size * max_position_pct

        for (pid, symbol), (qty, entry, direction, price, value) in pos_info.items():
            if value > max_value_per_position:
                # Position zu groß - verkaufen um auf 2% zu reduzieren
                max_qty = int(max_value_per_position / price) if price > 0 else 0
                # Calculate how many to sell, but be conservative with pending orders
                ideal_sell_qty = qty - max_qty
                # Sell at most 25% of position to avoid "insufficient qty" errors from pending orders
                sell_qty = max(1, min(ideal_sell_qty, int(qty * 0.25)))

                if sell_qty > 0:
                    pnl = (price - entry) * sell_qty if direction == "long" else (entry - price) * sell_qty
                    pct_of_account = (value / account_size) * 100

                    logger.warning(
                        "[PositionMonitor] POSITION SIZE VIOLATION: #%d %s | %.1f%% of account ($%.0f) "
                        "exceeds %d%% limit ($%.0f max). Auto-selling %.0f shares to reduce to $%.0f",
                        pid, symbol, pct_of_account, value, int(max_position_pct*100), max_value_per_position,
                        sell_qty, max_value_per_position
                    )

                    position_events_logger.warning(
                        f"OVERSIZED_POSITION | #{pid} {symbol} | {pct_of_account:.1f}% of account "
                        f"(${value:.0f}) exceeds {int(max_position_pct*100)}% limit (${max_value_per_position:.0f} max). "
                        f"Auto-selling {sell_qty:.0f} shares to rebalance"
                    )

                    # Direct Alpaca API call (no execution_agent dependency)
                    try:
                        resp = requests.post(
                            f"{os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}/v2/orders",
                            headers={
                                "APCA-API-KEY-ID": self._alpaca_key,
                                "APCA-API-SECRET-KEY": self._alpaca_secret,
                            },
                            json={
                                "symbol": symbol,
                                "qty": int(sell_qty),
                                "side": "sell",
                                "type": "market",
                                "time_in_force": "day",
                            },
                            timeout=10
                        )
                        resp.raise_for_status()

                        # Update local DB
                        with _connect() as conn:
                            conn.execute(
                                "UPDATE positions SET quantity = quantity - ? WHERE id=?",
                                (sell_qty, pid)
                            )
                            conn.commit()

                        logger.info(f"[PositionMonitor] Partial close executed for {symbol}: sold {int(sell_qty)} shares")
                    except Exception as e:
                        logger.error(f"[PositionMonitor] Failed to execute partial close for {symbol}: {e}")

    def rebalance_sector_concentration(self) -> None:
        """Reduziert übergewichtete Sektoren (>30%) durch Verkauf profitabler Positionen."""
        with _connect() as conn:
            # Hole alle offenen Positionen mit aktuellen Preisen
            positions = conn.execute("""
                SELECT id, symbol, direction, entry_price, quantity, highest_price,
                       lowest_price, opened_at FROM positions WHERE status='open'
            """).fetchall()

        if not positions:
            return

        # Berechne Sektor-Gewichte
        sector_values = {}
        position_dict = {}
        total_value = 0

        for pid, symbol, direction, entry, qty, highest, lowest, opened_at in positions:
            current_price = self._get_price(symbol)
            if not current_price:
                continue

            sector = self._get_sector(symbol)
            value = qty * current_price
            pnl_dollar = (current_price - entry) * qty if direction == "long" else (entry - current_price) * qty

            position_dict[(pid, symbol)] = {
                "current_price": current_price,
                "pnl_dollar": pnl_dollar,
                "value": value,
                "qty": qty,
            }

            sector_values.setdefault(sector, {"value": 0, "positions": []})
            sector_values[sector]["value"] += value
            sector_values[sector]["positions"].append((pid, symbol, pnl_dollar, value, qty))
            total_value += value

        if total_value == 0:
            return

        # Finde übergewichtete Sektoren
        max_sector_pct = float(os.getenv("MAX_SECTOR_PCT", "0.30"))  # 30%

        for sector, data in sector_values.items():
            sector_pct = data["value"] / total_value if total_value > 0 else 0

            if sector_pct > max_sector_pct:
                # Finde profitable Positionen in diesem Sektor
                profitable = [(pid, sym, pnl, val, qty) for pid, sym, pnl, val, qty in data["positions"] if pnl > 0]

                if profitable:
                    # Reduziere größte profitable Position um 30%
                    pid, symbol, pnl, value, qty = max(profitable, key=lambda x: x[2])
                    reduce_qty = max(1, int(qty * 0.30))

                    try:
                        resp = requests.post(
                            f"{os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}/v2/orders",
                            headers={
                                "APCA-API-KEY-ID": self._alpaca_key,
                                "APCA-API-SECRET-KEY": self._alpaca_secret,
                            },
                            json={
                                "symbol": symbol,
                                "qty": reduce_qty,
                                "side": "sell",
                                "type": "market",
                                "time_in_force": "day",
                            },
                            timeout=10
                        )
                        resp.raise_for_status()

                        with _connect() as conn:
                            conn.execute(
                                "UPDATE positions SET quantity = quantity - ? WHERE id=?",
                                (reduce_qty, pid)
                            )
                            conn.commit()

                        logger.info(
                            f"[Rebalance] {symbol}: sold {reduce_qty} shares (sector {sector} at {sector_pct*100:.1f}%)"
                        )
                    except Exception as e:
                        logger.warning(f"[Rebalance] Fehler beim Verkauf {symbol}: {e}")

    def check_correlation_hedge(self) -> None:
        """Reduziert hochkorrelierte Positionen zur Risikominderung."""
        with _connect() as conn:
            # Lade Correlation Matrix
            correlations = conn.execute("""
                SELECT symbol_a, symbol_b, correlation FROM correlation_matrix WHERE correlation > 0.85
            """).fetchall()

        if not correlations:
            return

        for sym_a, sym_b, corr in correlations:
            with _connect() as conn:
                # Hole Positionen
                pos_a = conn.execute(
                    "SELECT id, quantity, entry_price FROM positions WHERE symbol=? AND status='open'",
                    (sym_a,)
                ).fetchone()
                pos_b = conn.execute(
                    "SELECT id, quantity, entry_price FROM positions WHERE symbol=? AND status='open'",
                    (sym_b,)
                ).fetchone()

            if not (pos_a and pos_b):
                continue

            id_a, qty_a, entry_a = pos_a
            id_b, qty_b, entry_b = pos_b

            # Berechne P&L
            price_a = self._get_price(sym_a)
            price_b = self._get_price(sym_b)

            if not (price_a and price_b):
                continue

            pnl_a = (price_a - entry_a) * qty_a
            pnl_b = (price_b - entry_b) * qty_b

            # Reduziere NUR profitable Position(en)
            to_reduce = None
            if pnl_a > 0 and pnl_b > 0:
                # Beide profitable - reduziere die mit kleinerem Gewinn
                to_reduce = (sym_a, id_a, qty_a, pnl_a) if pnl_a < pnl_b else (sym_b, id_b, qty_b, pnl_b)
            elif pnl_a > 0:
                to_reduce = (sym_a, id_a, qty_a, pnl_a)
            elif pnl_b > 0:
                to_reduce = (sym_b, id_b, qty_b, pnl_b)

            if to_reduce:
                symbol, pos_id, qty, pnl = to_reduce
                reduce_qty = max(1, int(qty * 0.25))  # 25% reduzieren

                try:
                    requests.post(
                        f"{os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}/v2/orders",
                        headers={
                            "APCA-API-KEY-ID": self._alpaca_key,
                            "APCA-API-SECRET-KEY": self._alpaca_secret,
                        },
                        json={
                            "symbol": symbol,
                            "qty": reduce_qty,
                            "side": "sell",
                            "type": "market",
                            "time_in_force": "day",
                        },
                        timeout=10
                    )

                    with _connect() as conn:
                        conn.execute(
                            "UPDATE positions SET quantity = quantity - ? WHERE id=?",
                            (reduce_qty, pos_id)
                        )
                        conn.commit()

                    logger.info(
                        f"[Correlation Hedge] {symbol}: sold {reduce_qty} shares (corr with {sym_a if symbol == sym_b else sym_b}: {corr:.2f})"
                    )
                except Exception as e:
                    logger.warning(f"[Correlation Hedge] Fehler: {e}")

    def daily_rebalance_worst_performer(self) -> Optional[Dict[str, Any]]:
        """
        DAILY REBALANCING: Schließt die worst-performing offene Position (größter Verlust %)
        um Kapital für bessere Setups freizumachen.

        Wird 1x täglich aufgerufen, um Portfolio-Qualität zu verbessern.
        Konzept: "Sell the loser, wait for the winner"
        """
        with _connect() as conn:
            open_positions = conn.execute("""
                SELECT id, symbol, direction, entry_price, quantity FROM positions WHERE status='open'
            """).fetchall()

        if not open_positions or len(open_positions) <= 1:
            # Brauche mindestens 2 offene Positionen zum Rebalancieren
            return None

        # Berechne P&L % für jede Position
        positions_with_pnl = []
        for pid, symbol, direction, entry, qty in open_positions:
            current_price = self._get_price(symbol)
            if not current_price or entry <= 0:
                continue

            if direction == "long":
                pnl_pct = (current_price - entry) / entry
            else:  # short
                pnl_pct = (entry - current_price) / entry

            positions_with_pnl.append({
                "id": pid,
                "symbol": symbol,
                "direction": direction,
                "entry_price": entry,
                "qty": qty,
                "current_price": current_price,
                "pnl_pct": pnl_pct,
                "pnl_dollar": pnl_pct * entry * qty
            })

        if not positions_with_pnl:
            return None

        # Finde worst performer (größter Verlust %)
        worst = min(positions_with_pnl, key=lambda x: x["pnl_pct"])

        # Nur schließen wenn wirklich ein Verlust besteht (nicht profitable Positionen)
        if worst["pnl_pct"] >= 0:
            logger.info("[DailyRebalance] Alle Positionen profitable – kein Rebalancing nötig")
            return None

        worst_id = worst["id"]
        worst_symbol = worst["symbol"]
        worst_loss_pct = worst["pnl_pct"]
        worst_qty = worst["qty"]
        worst_price = worst["current_price"]

        logger.warning(
            "[DailyRebalance] WORST PERFORMER: #%d %s | Loss: %+.2f%% | Entry: $%.2f → Current: $%.2f",
            worst_id, worst_symbol, worst_loss_pct * 100, worst["entry_price"], worst_price
        )

        # Schließe Position
        result = self.close_position(worst_id, "daily_rebalance_worst", worst_price)

        if result.get("status") == "closed":
            position_events_logger.warning(
                f"DAILY_REBALANCE | Closed worst performer #{worst_id} {worst_symbol} | "
                f"Loss: {worst_loss_pct*100:+.2f}% (${worst['pnl_dollar']:+.2f}) | "
                f"Freeing capital for better setups"
            )

        return result

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
        broker = execution_result.get("broker", "alpaca")
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

        # Fallback wenn execution_agent noch nicht initialisiert
        if self.execution_agent is None:
            logger.warning("[PositionMonitor] execution_agent nicht verfügbar – Position nur in DB geschlossen")
            exec_result = {"status": "db_only", "symbol": pos["symbol"]}
        else:
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

        # Event-Log für Position Close
        status_icon = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
        position_events_logger.info(
            f"POSITION_CLOSED | {status_icon} #{position_id} {pos['symbol']} | Reason: {reason.upper()} | P&L: {pnl:+.2f} ({(pnl/float(pos.get('entry_price', 1))*100) if pos.get('entry_price') else 0:+.1f}%)"
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
            qty = float(pos.get("quantity") or 0.0)
            reason = None

            # ── AGGRESSIVE STOP-LOSS: Large positions (>3% account) use -2% instead of -5% ──
            account_size = float(os.getenv("ACCOUNT_SIZE", "100000"))
            position_value = qty * price if price > 0 else 0
            position_pct = (position_value / account_size) if account_size > 0 else 0

            # Use aggressive 2% SL for large positions, default 5% for others
            effective_sl_pct = 0.02 if position_pct > 0.03 else self.hard_stop_loss_pct

            # Log if aggressive SL applies
            if position_pct > 0.03 and effective_sl_pct == 0.02:
                logger.debug(f"[PositionMonitor] #{pid} {symbol}: Large position ({position_pct*100:.1f}% of account) → using aggressive -2% SL")

            # ── HARD STOP-LOSS CHECK (5% default, 2% für große Positionen) ─────
            if entry > 0:
                if direction == "long":
                    loss_pct = (entry - price) / entry
                    if loss_pct >= effective_sl_pct:
                        reason = "hard_stop_loss_aggressive" if effective_sl_pct == 0.02 else "hard_stop_loss"
                else:  # short
                    loss_pct = (price - entry) / entry
                    if loss_pct >= effective_sl_pct:
                        reason = "hard_stop_loss_aggressive" if effective_sl_pct == 0.02 else "hard_stop_loss"

            if reason and "hard_stop_loss" in reason:
                result = self.close_position(pid, reason, price)
                actions.append(result)
                if effective_sl_pct == 0.02:
                    position_events_logger.warning(
                        f"AGGRESSIVE_SL | #{pid} {symbol} | Position: {position_pct*100:.1f}% of account | Loss: {loss_pct*100:.1f}% | Entry: ${entry:.2f} → Exit: ${price:.2f}"
                    )
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
                            position_events_logger.info(
                                f"PROFIT_LOCKED | #{pid} {symbol} | Level: +{level*100:.0f}% | Price: ${price:.2f}"
                            )

                    # KEY FEATURE: Ratchet stop - if profit falls below locked level, close
                    if highest_locked > 0 and profit_pct < highest_locked:
                        sl = price + 0.01
                        reason = "profit_ratchet_breach"
                        position_events_logger.warning(
                            f"RATCHET_BREACH | #{pid} {symbol} | Was: +{highest_locked*100:.0f}% Now: {profit_pct*100:+.1f}% | Price: ${price:.2f}"
                        )
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
                            position_events_logger.info(
                                f"PROFIT_LOCKED | #{pid} {symbol} (SHORT) | Level: +{level*100:.0f}% | Price: ${price:.2f}"
                            )

                    # KEY FEATURE: Ratchet stop - if profit falls below locked level, close
                    if highest_locked > 0 and profit_pct < highest_locked:
                        sl = price - 0.01
                        reason = "profit_ratchet_breach"
                        position_events_logger.warning(
                            f"RATCHET_BREACH | #{pid} {symbol} (SHORT) | Was: +{highest_locked*100:.0f}% Now: {profit_pct*100:+.1f}% | Price: ${price:.2f}"
                        )
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
        self.sync_from_alpaca()  # Load Alpaca positions on startup
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
        iteration = 0
        last_daily_rebalance = None
        while not self._stop_event.is_set():
            try:
                if iteration % 15 == 0:
                    self.sync_from_alpaca()

                # Daily rebalancing (sector concentration + correlation hedge + position sizes + worst performer)
                today = datetime.now().date()
                if last_daily_rebalance != today:
                    self.update_correlation_matrix()
                    self.rebalance_position_sizes()  # Reduce oversized positions
                    self.rebalance_sector_concentration()
                    self.check_correlation_hedge()
                    self.daily_rebalance_worst_performer()  # NEW: Close worst performer to free capital
                    last_daily_rebalance = today
                    logger.info("[PositionMonitor] Tägliche Rebalance durchgeführt (worst performer check inclusive)")

                actions = self.check_positions()
                if actions:
                    logger.info(
                        "[PositionMonitor] %d Position(en) geschlossen: %s",
                        len(actions),
                        [(a["symbol"], a["reason"], a["pnl"]) for a in actions],
                    )
            except Exception as exc:
                logger.error("[PositionMonitor] Fehler im Check-Loop: %s", exc)
            iteration += 1
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


# ── OptionsPositionMonitor ────────────────────────────────────────────────────

class OptionsPositionMonitor:
    """Verwaltet offene Optionen-Positionen separat von Aktien-Positionen."""

    def __init__(self, check_interval_seconds: int = 300) -> None:
        self._alpaca_key = os.getenv("ALPACA_API_KEY")
        self._alpaca_secret = os.getenv("ALPACA_API_SECRET")
        self._finnhub_key = os.getenv("FINNHUB_API_KEY")
        self.check_interval = check_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        _init_db()

    def sync_from_alpaca_options(self) -> int:
        """Lädt offene Options-Positionen von Alpaca."""
        if not (self._alpaca_key and self._alpaca_secret):
            return 0

        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        headers = {
            "APCA-API-KEY-ID": self._alpaca_key,
            "APCA-API-SECRET-KEY": self._alpaca_secret,
        }

        try:
            resp = requests.get(f"{base_url}/v2/positions", headers=headers, timeout=10)
            resp.raise_for_status()
            positions = resp.json()
        except Exception as e:
            logger.warning(f"[Options Sync] Fehler: {e}")
            return 0

        synced = 0
        with _connect() as conn:
            for pos in positions:
                symbol = pos.get("symbol", "").upper()
                # Nur Options-Symbole (OCC Format: AAPL260517C00200000)
                if not (symbol and len(symbol) > 10 and symbol[-1] in "CP"):
                    continue

                qty = abs(float(pos.get("qty", 0)))
                entry_price = float(pos.get("avg_entry_price", 0))

                exists = conn.execute(
                    "SELECT id FROM options_positions WHERE option_symbol=? AND status='open'",
                    (symbol,)
                ).fetchone()

                if not exists:
                    # Parse OCC Symbol: AAPL260517C00200000
                    underlying = symbol[:symbol.find(symbol[-10])]  # Find where digits start
                    for i, c in enumerate(symbol):
                        if c in "CP":
                            option_type = "call" if c == "C" else "put"
                            expiry_str = symbol[len(underlying):i]  # YYMMDD
                            strike_str = symbol[i+1:]
                            break

                    try:
                        expiry = datetime.strptime(f"20{expiry_str}", "%Y%m%d").date()
                        strike = float(strike_str) / 1000.0
                        dte = (expiry - datetime.now().date()).days

                        conn.execute("""
                            INSERT INTO options_positions
                            (symbol, option_symbol, option_type, strike, expiry,
                             dte_at_entry, contracts, premium_paid, broker, opened_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'alpaca', ?, 'open')
                        """, (underlying, symbol, option_type, strike,
                              expiry.isoformat(), dte, int(qty),
                              entry_price, datetime.now(timezone.utc).isoformat()))
                        synced += 1
                    except Exception as e:
                        logger.warning(f"[Options Sync] Parse error für {symbol}: {e}")

            conn.commit()

        if synced > 0:
            logger.info(f"[Options Sync] {synced} neue Optionen-Positionen geladen")
        return synced

    def check_options_positions(self) -> List[Dict[str, Any]]:
        """Prüft alle offenen Optionen gegen Expiry/Premium/DTE."""
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM options_positions WHERE status='open'"
            ).fetchall()

        actions = []
        for row in rows:
            pos = dict(row)
            option_symbol = pos["option_symbol"]
            contracts = pos["contracts"]
            premium_paid = pos["premium_paid"]
            dte = (datetime.fromisoformat(pos["expiry"]) - datetime.now()).days

            # 1) DTE Guard – close wenn < 3 Tage bis Expiry
            if dte < 3:
                self.close_option(pos["id"], "expiry", premium_paid)
                actions.append({
                    "symbol": option_symbol,
                    "reason": "expiry",
                    "dte": dte,
                    "status": "closed",
                })
                continue

            # 2) Price check
            price = self._get_option_price(option_symbol)
            if price is None:
                continue

            price_per_share = price  # Alpaca gibt per-share quotes
            pct_of_premium = price_per_share / premium_paid if premium_paid > 0 else 0

            # Stop-Loss: wenn unter 20% des Entry-Preises
            if pct_of_premium < 0.20:
                pnl = (price_per_share - premium_paid) * contracts * 100
                self.close_option(pos["id"], "stop_loss", price_per_share)
                actions.append({
                    "symbol": option_symbol,
                    "reason": "stop_loss",
                    "pnl": pnl,
                    "price": price,
                })
                continue

            # Take-Profit: wenn über 200% des Entry-Preises
            if pct_of_premium > 2.0:
                pnl = (price_per_share - premium_paid) * contracts * 100
                self.close_option(pos["id"], "take_profit", price_per_share)
                actions.append({
                    "symbol": option_symbol,
                    "reason": "take_profit",
                    "pnl": pnl,
                    "price": price,
                })
                continue

        return actions

    def close_option(self, position_id: int, reason: str, close_price: float) -> None:
        """Schließt eine Options-Position."""
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM options_positions WHERE id=?", (position_id,)
            ).fetchone()

        if not row:
            return

        pos = dict(row)
        contracts = pos["contracts"]
        premium_paid = pos["premium_paid"]
        pnl = (close_price - premium_paid) * contracts * 100

        now = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                """UPDATE options_positions
                   SET status=?, close_premium=?, closed_at=?, pnl=?, close_reason=?
                   WHERE id=?""",
                (f"closed_{reason}", close_price, now, pnl, reason, position_id),
            )
            conn.commit()

        logger.info(
            "[Options] %s geschlossen (%s): @ %.4f | P&L: %+.2f",
            pos["option_symbol"], reason, close_price, pnl,
        )

    def open_option(self, options_plan: Dict[str, Any], contract: Dict[str, Any], contracts_count: int) -> None:
        """Registriert neue Options-Position in DB."""
        now = datetime.now(timezone.utc).isoformat()
        premium = float(contract.get("premium") or options_plan.get("position_risk_budget", 0) / (contracts_count * 100 if contracts_count > 0 else 1))

        with _connect() as conn:
            conn.execute("""
                INSERT INTO options_positions
                (symbol, option_symbol, option_type, strike, expiry, dte_at_entry,
                 contracts, premium_paid, delta_at_entry, broker, opened_at, status)
                VALUES (?,?,?,?,?,?,?,?,?,'alpaca',?,'open')
            """, (
                contract["underlying"],
                contract["occ_symbol"],
                contract["option_type"],
                contract["strike"],
                contract["expiry"],
                contract["dte"],
                contracts_count,
                premium,
                contract.get("delta", 0.5),
                now,
            ))
            conn.commit()

        logger.info(
            "[Options] %s eröffnet: %d Kontrakte @ %.4f (DTE: %d, Delta: %.2f)",
            contract["occ_symbol"], contracts_count, premium, contract["dte"], contract.get("delta", 0.5),
        )

    def _get_option_price(self, option_symbol: str) -> Optional[float]:
        """Holt aktuellen Preis für Options-Symbol."""
        # Finnhub
        if self._finnhub_key:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": option_symbol, "token": self._finnhub_key},
                    timeout=5,
                )
                if resp.ok:
                    price = resp.json().get("c")
                    if price and float(price) > 0:
                        return float(price)
            except Exception:
                pass

        # Alpaca
        if self._alpaca_key and self._alpaca_secret:
            try:
                resp = requests.get(
                    f"https://data.alpaca.markets/v2/options/snapshots/{option_symbol}",
                    headers={
                        "APCA-API-KEY-ID": self._alpaca_key,
                        "APCA-API-SECRET-KEY": self._alpaca_secret,
                    },
                    timeout=5,
                )
                if resp.ok:
                    price = resp.json().get("snapshot", {}).get("last_quote", {}).get("ap")
                    if price and float(price) > 0:
                        return float(price)
            except Exception:
                pass

        return None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("[OptionsMonitor] Läuft bereits.")
            return
        self.sync_from_alpaca_options()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="OptionsPositionMonitor"
        )
        self._thread.start()
        logger.info("[OptionsMonitor] Gestartet (Intervall: %ds).", self.check_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        logger.info("[OptionsMonitor] Gestoppt.")

    def _loop(self) -> None:
        iteration = 0
        while not self._stop_event.is_set():
            try:
                if iteration % 3 == 0:  # Alle 15 Minuten (bei 300s interval)
                    self.sync_from_alpaca_options()

                actions = self.check_options_positions()
                if actions:
                    logger.info(
                        "[OptionsMonitor] %d Position(en) geschlossen: %s",
                        len(actions),
                        [(a["symbol"], a["reason"]) for a in actions],
                    )
            except Exception as exc:
                logger.error("[OptionsMonitor] Fehler im Check-Loop: %s", exc)
            iteration += 1
            self._stop_event.wait(self.check_interval)


# ── Modul-Singleton (wird von anderen Modulen importiert) ─────────────────────
# KRITISCH: Monitor muss sofort instantiiert werden, damit check_positions() läuft!
monitor = PositionMonitor(
    execution_agent=None,  # wird später gesetzt von trading_agents_with_gpt
    circuit_breaker=None,  # wird später gesetzt
    check_interval_seconds=int(os.getenv("MONITOR_INTERVAL_SECONDS", "60")),
)
options_monitor = OptionsPositionMonitor(
    check_interval_seconds=int(os.getenv("OPTIONS_MONITOR_INTERVAL", "300")),
)
