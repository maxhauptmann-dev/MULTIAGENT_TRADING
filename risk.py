from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time
import math
from datetime import datetime, timezone
import sqlite3

# --- Positionsgröße -----------------------------------------

def compute_position_size(account_size: float,
                          max_risk_per_trade: float,
                          entry_price: Optional[float],
                          stop_price: Optional[float]) -> Dict[str, Any]:
    """
    Konservative Stückzahl:
    qty = floor( max_risk_amount / abs(entry - stop) )
    """
    try:
        account_size = float(account_size or 0.0)
        max_risk_per_trade = float(max_risk_per_trade or 0.0)
        entry = float(entry_price) if entry_price is not None else None
        stop = float(stop_price) if stop_price is not None else None
    except Exception:
        return {"max_risk_amount": 0.0, "risk_per_share": 0.0, "qty": 0}

    if account_size <= 0 or max_risk_per_trade <= 0 or entry is None or stop is None:
        return {"max_risk_amount": 0.0, "risk_per_share": 0.0, "qty": 0}

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"max_risk_amount": 0.0, "risk_per_share": 0.0, "qty": 0}

    max_risk_amount = account_size * max_risk_per_trade
    qty = int(math.floor(max_risk_amount / risk_per_share))
    if qty < 0:
        qty = 0

    return {
        "max_risk_amount": round(max_risk_amount, 2),
        "risk_per_share": round(risk_per_share, 4),
        "qty": qty,
    }

# --- Kelly Criterion ----------------------------------------

def compute_kelly_size(
    account_size: float,
    buy_probability: float,
    rr_ratio: float,
    max_risk_per_trade: float,
    entry_price: Optional[float],
    stop_price: Optional[float],
) -> Dict[str, Any]:
    """
    Half-Kelly Positionsgröße.
    f = max(0, (p - (1-p)/b) / 2), gedeckelt auf max_risk_per_trade.
    Fällt auf compute_position_size zurück wenn Kelly-Fraction <= 0.
    """
    try:
        p = float(buy_probability)
        b = float(rr_ratio) if rr_ratio and rr_ratio > 0 else 1.5
        kelly = (p - (1.0 - p) / b) / 2.0
        kelly = max(0.0, min(kelly, float(max_risk_per_trade)))
    except Exception:
        kelly = 0.0

    if kelly <= 0:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    try:
        entry = float(entry_price) if entry_price is not None else None
        stop  = float(stop_price)  if stop_price  is not None else None
    except Exception:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    if entry is None or stop is None:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"max_risk_amount": 0.0, "risk_per_share": 0.0, "qty": 0}

    max_risk_amount = float(account_size) * kelly
    qty = int(math.floor(max_risk_amount / risk_per_share))

    return {
        "max_risk_amount": round(max_risk_amount, 2),
        "risk_per_share":  round(risk_per_share, 4),
        "qty":             max(0, qty),
        "kelly_fraction":  round(kelly, 4),
    }


def compute_adaptive_kelly_size(
    account_size: float,
    buy_probability: float,
    rr_ratio: float,
    max_risk_per_trade: float,
    entry_price: Optional[float],
    stop_price: Optional[float],
    monthly_drawdown_pct: float = 0.0,
    recent_win_count: int = 0,
    recent_trade_count: int = 10,
) -> Dict[str, Any]:
    """
    Adaptive Half-Kelly mit Drawdown & Streak Faktoren.

    kelly_base = (p - (1-p)/b) / 2
    kelly_adjusted = kelly_base * drawdown_factor * streak_factor
    kelly_final = clamp(kelly_adjusted, 0.003, min(0.25, base * 1.5))
    """
    try:
        p = float(buy_probability)
        b = float(rr_ratio) if rr_ratio and rr_ratio > 0 else 1.5
        kelly_base = (p - (1.0 - p) / b) / 2.0
        kelly_base = max(0.0, min(kelly_base, float(max_risk_per_trade)))
    except Exception:
        kelly_base = 0.0

    if kelly_base <= 0:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    # Drawdown Factor: Decay bei Verlusten
    dd_pct = float(monthly_drawdown_pct)
    if dd_pct < 0:
        dd_factor = max(0.3, 1.0 + dd_pct)  # At -5% DD, factor = 0.95
    else:
        dd_factor = 1.0

    # Streak Factor: Increase bei Gewinnen, cap at 1.5x
    recent_wins = int(recent_win_count)
    recent_total = int(recent_trade_count)
    streak_factor = 1.0
    if recent_total > 0:
        win_ratio = recent_wins / recent_total
        streak_factor = 1.0 + (win_ratio / 2.0)  # 0 wins = 1.0x, 10 wins = 1.5x
        streak_factor = min(streak_factor, 1.5)

    kelly_adjusted = kelly_base * dd_factor * streak_factor

    # Clamp: min 0.3%, max 25% or 1.5x base
    kelly_final = max(0.003, min(kelly_adjusted, min(0.25, kelly_base * 1.5)))

    try:
        entry = float(entry_price) if entry_price is not None else None
        stop = float(stop_price) if stop_price is not None else None
    except Exception:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    if entry is None or stop is None:
        return compute_position_size(account_size, max_risk_per_trade, entry_price, stop_price)

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"max_risk_amount": 0.0, "risk_per_share": 0.0, "qty": 0}

    max_risk_amount = float(account_size) * kelly_final
    qty = int(math.floor(max_risk_amount / risk_per_share))

    return {
        "max_risk_amount": round(max_risk_amount, 2),
        "risk_per_share": round(risk_per_share, 4),
        "qty": max(0, qty),
        "kelly_fraction_base": round(kelly_base, 4),
        "kelly_fraction_adjusted": round(kelly_final, 4),
        "drawdown_factor": round(dd_factor, 4),
        "streak_factor": round(streak_factor, 4),
    }


# --- Circuit-Breaker ----------------------------------------

@dataclass
class CircuitBreaker:
    n_errors: int = 5
    n_losses: int = 3
    cooldown_seconds: int = 3600
    _error_count: int = 0
    _loss_count: int = 0
    _opened_at: Optional[float] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """True, wenn kein aktiver Cooldown."""
        with self._lock:
            if self._opened_at is None:
                return True
            if (time.time() - self._opened_at) >= self.cooldown_seconds:
                self._reset_locked()
                return True
            return False

    def record_error(self) -> None:
        with self._lock:
            self._error_count += 1
            if self._error_count >= self.n_errors:
                self._trip_locked("errors")

    def record_loss(self) -> None:
        with self._lock:
            self._loss_count += 1
            if self._loss_count >= self.n_losses:
                self._trip_locked("losses")

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def _reset_locked(self) -> None:
        self._error_count = 0
        self._loss_count = 0
        self._opened_at = None

    def _trip_locked(self, reason: str) -> None:
        if self._opened_at is None:
            self._opened_at = time.time()
            print(f"[CircuitBreaker] OPEN due to {reason}. Cooldown {self.cooldown_seconds}s")

    def _trip(self, reason: str) -> None:
        with self._lock:
            self._trip_locked(reason)

    def state(self) -> Dict[str, Any]:
        return {
            "errors": self._error_count,
            "losses": self._loss_count,
            "opened_at": self._opened_at,
            "allow": self.allow(),
        }


# --- Portfolio Metrics (Daily/Monthly Drawdown Tracking) --------

@dataclass
class PortfolioMetrics:
    """
    Tracks daily and monthly high water marks for drawdown calculations.
    """
    db_path: str = "positions.db"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self._lock = threading.Lock()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def update_equity(self, current_equity: float) -> Dict[str, Any]:
        """
        Updates daily/monthly HWM based on current equity.
        Returns current state: {daily_dd, monthly_dd, status}
        """
        with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM portfolio_metrics WHERE date=?",
                    (today,),
                ).fetchone()

                if row:
                    daily_hwm = float(row["daily_high_water_mark"])
                    monthly_hwm = float(row["monthly_high_water_mark"])
                else:
                    daily_hwm = current_equity
                    monthly_hwm = current_equity

                # Update HWMs
                daily_hwm = max(daily_hwm, current_equity)
                monthly_hwm = max(monthly_hwm, current_equity)

                # Calculate drawdowns
                daily_dd = (current_equity - daily_hwm) / daily_hwm if daily_hwm > 0 else 0
                monthly_dd = (current_equity - monthly_hwm) / monthly_hwm if monthly_hwm > 0 else 0

                # Determine status
                if daily_dd <= -0.10:
                    status = "halted"
                elif daily_dd <= -0.05:
                    status = "paused"
                else:
                    status = "open"

                # Upsert
                if row:
                    conn.execute(
                        """
                        UPDATE portfolio_metrics
                        SET daily_high_water_mark=?, monthly_high_water_mark=?, drawdown_status=?
                        WHERE date=?
                        """,
                        (daily_hwm, monthly_hwm, status, today),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO portfolio_metrics
                        (date, daily_high_water_mark, monthly_high_water_mark, drawdown_status)
                        VALUES (?, ?, ?, ?)
                        """,
                        (today, daily_hwm, monthly_hwm, status),
                    )
                conn.commit()

            return {
                "daily_drawdown_pct": round(daily_dd * 100, 2),
                "monthly_drawdown_pct": round(monthly_dd * 100, 2),
                "status": status,
                "daily_hwm": round(daily_hwm, 2),
                "monthly_hwm": round(monthly_hwm, 2),
                "allow_new_trades": status == "open",
            }

    def reset_daily(self, new_equity: float) -> None:
        """Reset daily HWM at market open."""
        with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE portfolio_metrics
                    SET daily_high_water_mark=? WHERE date=?
                    """,
                    (new_equity, today),
                )
                conn.commit()

    def reset_monthly(self, new_equity: float) -> None:
        """Reset monthly HWM at month start."""
        with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE portfolio_metrics
                    SET monthly_high_water_mark=? WHERE date=?
                    """,
                    (new_equity, today),
                )
                conn.commit()