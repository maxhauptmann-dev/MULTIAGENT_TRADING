"""
ExecutionEngine — Paper Trading with Conservative Fills
Simulates option trade execution for backtesting and paper trading.
Uses Ask-Entry (worst-case) and Mid-Price Exit for realistic P&L.
"""

import logging
import sqlite3
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from risk_manager import Greeks
from strategy_engine import Signal, StrategyType


# ============================================================
# Data Classes
# ============================================================

class ExecutionStatus(Enum):
    """Trade execution status"""
    PENDING = "pending"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class ExecutedTrade:
    """Single executed option trade"""
    trade_id: str
    cycle_id: str
    symbol: str
    strategy: StrategyType
    direction: str  # bullish/bearish

    # Entry (Ask-price, worst-case)
    entry_price: float
    entry_time: datetime
    entry_greeks: Greeks

    # Exit (Mid-price, realistic)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_greeks: Optional[Greeks] = None

    # Position Details
    contracts: int = 1
    dte: int = 30

    # P&L Tracking
    realized_pnl: float = 0.0
    pnl_percent: float = 0.0
    status: ExecutionStatus = ExecutionStatus.FILLED

    # Metadata
    confidence: float = 0.0
    signal_strength: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionResult:
    """Result of trade execution"""
    executed: bool
    trade_id: Optional[str] = None
    entry_price: Optional[float] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# ExecutionEngine
# ============================================================

class ExecutionEngine:
    """
    Simulates option trade execution in paper trading mode.

    Conservative Fill Rules:
    - Entry: Ask price (worst-case when buying)
    - Exit: Mid-price (realistic market exit)
    - Spread: Bid-Ask from current market
    """

    def __init__(self, paper_trading: bool = True, db_path: str = "trading.db"):
        self.paper_trading = paper_trading
        self.db_path = db_path
        self.trades: Dict[str, ExecutedTrade] = {}
        self.trade_counter = 0
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def execute_signal(
        self,
        signal: Signal,
        cycle_id: str,
        current_bid: Optional[float] = None,
        current_ask: Optional[float] = None,
    ) -> ExecutionResult:
        """
        Execute a trading signal with conservative fills.

        Args:
            signal: Trading signal from StrategyEngine
            cycle_id: Current cycle identifier
            current_bid: Current bid price (from market data)
            current_ask: Current ask price (from market data)

        Returns:
            ExecutionResult with trade details or rejection reason
        """

        # Validate signal
        if not signal or signal.confidence < 0.60:
            return ExecutionResult(
                executed=False,
                reason=f"Low confidence: {signal.confidence if signal else 'None'}"
            )

        # Generate Ask/Bid if not provided
        if current_ask is None or current_bid is None:
            # Estimate from signal current_price with typical option spread
            mid = signal.current_price if signal.current_price else 100.0
            spread = max(0.05, mid * 0.001)  # 0.5% typical spread, min 0.05
            current_bid = mid - spread / 2
            current_ask = mid + spread / 2

        # Conservative entry: Ask price (buying at worst price)
        entry_price = current_ask

        # Calculate Greeks at entry
        entry_greeks = self._estimate_greeks(signal, entry_price)

        # Create trade
        self.trade_counter += 1
        trade_id = f"trade_{self.trade_counter}_{cycle_id}"

        trade = ExecutedTrade(
            trade_id=trade_id,
            cycle_id=cycle_id,
            symbol=signal.symbol,
            strategy=signal.strategy,
            direction=signal.direction,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            entry_greeks=entry_greeks,
            contracts=signal.recommended_contracts or 1,
            dte=signal.recommended_dte or 30,
            confidence=signal.confidence,
            signal_strength=signal.signal_strength,
            status=ExecutionStatus.FILLED,
        )

        self.trades[trade_id] = trade
        self._save_trade_to_db(trade)

        self.logger.info(
            f"[EXECUTION] {signal.symbol} {signal.strategy.value} @ ${entry_price:.2f} "
            f"(confidence={signal.confidence:.2f}, delta={entry_greeks.delta:.2f})"
        )

        return ExecutionResult(
            executed=True,
            trade_id=trade_id,
            entry_price=entry_price,
        )

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "target_hit"
    ) -> Tuple[bool, float]:
        """
        Close an open trade and calculate P&L.

        Args:
            trade_id: Trade to close
            exit_price: Exit price (mid-price, realistic)
            exit_reason: Why trade is closing

        Returns:
            (success, pnl_dollars)
        """
        if trade_id not in self.trades:
            self.logger.warning(f"Trade {trade_id} not found")
            return False, 0.0

        trade = self.trades[trade_id]
        if trade.status == ExecutionStatus.CLOSED:
            return False, 0.0

        # Calculate P&L (per contract)
        pnl_per_contract = exit_price - trade.entry_price
        total_pnl = pnl_per_contract * trade.contracts
        pnl_percent = (pnl_per_contract / trade.entry_price * 100) if trade.entry_price else 0

        # Update trade
        trade.exit_price = exit_price
        trade.exit_time = datetime.now(timezone.utc)
        trade.realized_pnl = total_pnl
        trade.pnl_percent = pnl_percent
        trade.status = ExecutionStatus.CLOSED

        self.logger.info(
            f"[CLOSE] {trade_id}: {trade.symbol} @ ${exit_price:.2f} "
            f"P&L: ${total_pnl:.2f} ({pnl_percent:+.2f}%)"
        )

        # Save to database
        self._save_trade_to_db(trade)

        return True, total_pnl

    def get_portfolio_pnl(self) -> Dict[str, float]:
        """Calculate total portfolio P&L from all closed trades"""
        realized = sum(
            t.realized_pnl for t in self.trades.values()
            if t.status == ExecutionStatus.CLOSED
        )

        open_trades = [
            t for t in self.trades.values()
            if t.status == ExecutionStatus.FILLED
        ]
        unrealized = sum(
            (t.exit_price or t.entry_price * 1.1) - t.entry_price
            for t in open_trades
        )

        return {
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": realized + unrealized,
            "closed_trades": len([t for t in self.trades.values() if t.status == ExecutionStatus.CLOSED]),
            "open_trades": len(open_trades),
        }

    def get_trade_statistics(self) -> Dict[str, float]:
        """Calculate win rate, avg win/loss, profit factor"""
        closed_trades = [
            t for t in self.trades.values()
            if t.status == ExecutionStatus.CLOSED
        ]

        if not closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "profit_factor": 0,
                "largest_win": 0,
                "largest_loss": 0,
            }

        winning = [t for t in closed_trades if t.realized_pnl > 0]
        losing = [t for t in closed_trades if t.realized_pnl < 0]

        win_rate = len(winning) / len(closed_trades) * 100 if closed_trades else 0
        avg_win = sum(t.realized_pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.realized_pnl for t in losing) / len(losing) if losing else 0

        total_wins = sum(t.realized_pnl for t in winning)
        total_losses = abs(sum(t.realized_pnl for t in losing))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        return {
            "total_trades": len(closed_trades),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "largest_win": max((t.realized_pnl for t in winning), default=0),
            "largest_loss": min((t.realized_pnl for t in losing), default=0),
        }

    # -------- Database --------

    def _save_trade_to_db(self, trade: ExecutedTrade) -> bool:
        """Save trade to executed_strategies table"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT OR REPLACE INTO executed_strategies
                (symbol, strategy, direction, contracts, entry_price, entry_timestamp,
                 exit_price, exit_timestamp, pnl, pnl_percent, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.symbol,
                    trade.strategy.value,
                    trade.direction,
                    trade.contracts,
                    trade.entry_price,
                    trade.entry_time.isoformat(),
                    trade.exit_price,
                    trade.exit_time.isoformat() if trade.exit_time else None,
                    trade.realized_pnl,
                    trade.pnl_percent,
                    trade.status.value,
                    trade.created_at.isoformat(),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            self.logger.error(f"Error saving trade to DB: {e}")
            return False

    # -------- Helpers --------

    def _estimate_greeks(self, signal: Signal, entry_price: float) -> Greeks:
        """Estimate Greeks at entry price"""
        # If signal has pre-calculated Greeks, use those
        if hasattr(signal, '_greeks') and signal._greeks:
            return signal._greeks

        # Otherwise estimate based on strategy and direction
        # This is simplified; real Greeks would come from Black-Scholes
        delta = 0.5 if signal.direction == "bullish" else -0.5
        gamma = 0.05
        theta = -0.10
        vega = entry_price * 0.1

        return Greeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            price=entry_price
        )


# ============================================================
# Test / Debug
# ============================================================

if __name__ == "__main__":
    print("ExecutionEngine initialized (Paper Trading)")

    engine = ExecutionEngine(paper_trading=True)
    print(f"Paper Trading: {engine.paper_trading}")
    print(f"Trades: {len(engine.trades)}")
