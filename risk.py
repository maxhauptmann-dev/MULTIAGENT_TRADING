from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
import time
import math

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

# --- Circuit-Breaker ----------------------------------------

@dataclass
class CircuitBreaker:
    n_errors: int = 5
    n_losses: int = 3
    cooldown_seconds: int = 3600
    _error_count: int = 0
    _loss_count: int = 0
    _opened_at: Optional[float] = None

    def allow(self) -> bool:
        """True, wenn kein aktiver Cooldown."""
        if self._opened_at is None:
            return True
        if (time.time() - self._opened_at) >= self.cooldown_seconds:
            self.reset()
            return True
        return False

    def record_error(self) -> None:
        self._error_count += 1
        if self._error_count >= self.n_errors:
            self._trip("errors")

    def record_loss(self) -> None:
        self._loss_count += 1
        if self._loss_count >= self.n_losses:
            self._trip("losses")

    def reset(self) -> None:
        self._error_count = 0
        self._loss_count = 0
        self._opened_at = None

    def _trip(self, reason: str) -> None:
        if self._opened_at is None:
            self._opened_at = time.time()
            print(f"[CircuitBreaker] OPEN due to {reason}. Cooldown {self.cooldown_seconds}s")

    def state(self) -> Dict[str, Any]:
        return {
            "errors": self._error_count,
            "losses": self._loss_count,
            "opened_at": self._opened_at,
            "allow": self.allow(),
        }