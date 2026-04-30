"""
TradingOrchestrator Module — Central coordination and hourly scheduling
Orchestrates all modules: DataFetcher → AnalyticsEngine → StrategyEngine → RiskManager
"""

import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

from data_fetcher import DataFetcher
from analytics_engine import AnalyticsEngine
from strategy_engine import StrategyEngine
from risk_manager import RiskManager, PositionRisk
from execution_engine import ExecutionEngine


@dataclass
class CycleResult:
    """Result of a single hourly trading cycle"""
    cycle_id: str
    timestamp: datetime
    symbols_analyzed: int
    signals_generated: int
    signals_executed: int
    signals_rejected: int
    portfolio_delta: float
    portfolio_theta: float
    errors: List[str]
    duration_seconds: float


class TradingOrchestrator:
    """Orchestrates hourly multi-timeframe options trading"""

    def __init__(
        self,
        symbols: List[str],
        account_size: float = 100000.0,
        schedule_enabled: bool = False,
    ):
        self.symbols = symbols
        self.account_size = account_size
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Initialize modules
        self.data_fetcher = DataFetcher()
        self.analytics_engine = AnalyticsEngine()
        self.strategy_engine = StrategyEngine()
        self.risk_manager = RiskManager(account_size=account_size)
        self.execution_engine = ExecutionEngine(paper_trading=True)

        # State
        self.open_positions: List[PositionRisk] = []
        self.cycle_count = 0
        self.last_cycle_result: Optional[CycleResult] = None

        # Scheduler
        self.scheduler = None
        if SCHEDULER_AVAILABLE and schedule_enabled:
            self._init_scheduler()

        self.logger.info(
            f"TradingOrchestrator initialized: {len(symbols)} symbols, "
            f"${account_size:.0f} account"
        )

    def _init_scheduler(self):
        """Initialize APScheduler for hourly execution"""
        self.scheduler = BackgroundScheduler()
        # Run at 15 minutes past each hour (market hours 10:00-20:00 UTC)
        self.scheduler.add_job(
            self.run_hourly_cycle,
            'cron',
            hour='10-20',
            minute='15',
            timezone='UTC',
            misfire_grace_time=300,
        )
        self.logger.info("APScheduler configured for hourly cycles (10:15-20:15 UTC)")

    def start(self):
        """Start the orchestrator (scheduler if enabled)"""
        if self.scheduler:
            self.scheduler.start()
            self.logger.info("TradingOrchestrator started")

    def stop(self):
        """Stop the orchestrator"""
        if self.scheduler:
            self.scheduler.shutdown()
            self.logger.info("TradingOrchestrator stopped")

    def run_hourly_cycle(self) -> Optional[CycleResult]:
        """
        Execute complete hourly trading cycle

        Flow:
        1. Fetch data (hourly + daily candles, IV)
        2. Analyze each symbol (technicals, trends)
        3. Generate signals (6 strategies)
        4. Validate signals (Greeks, portfolio limits)
        5. Update portfolio state
        """
        import time
        cycle_start = time.time()
        self.cycle_count += 1
        cycle_id = f"cycle_{self.cycle_count}_{datetime.now(timezone.utc).isoformat()}"

        result = CycleResult(
            cycle_id=cycle_id,
            timestamp=datetime.now(timezone.utc),
            symbols_analyzed=0,
            signals_generated=0,
            signals_executed=0,
            signals_rejected=0,
            portfolio_delta=0.0,
            portfolio_theta=0.0,
            errors=[],
            duration_seconds=0.0,
        )

        try:
            self.logger.info(f"[{cycle_id}] Starting hourly cycle")

            # Step 1: Fetch data for all symbols
            self.logger.info(f"[{cycle_id}] Fetching data for {len(self.symbols)} symbols...")
            market_data = self.data_fetcher.fetch_all_symbols(self.symbols)

            # Step 2-4: Analyze and generate signals
            valid_signals = []

            for symbol in self.symbols:
                try:
                    if symbol not in market_data:
                        result.errors.append(f"{symbol}: No market data")
                        continue

                    data = market_data[symbol]
                    result.symbols_analyzed += 1

                    # Skip if insufficient data
                    if not data["hourly_candles"] or not data["daily_candles"]:
                        result.errors.append(f"{symbol}: Insufficient candles")
                        continue

                    # Analyze
                    analysis = self.analytics_engine.analyze(
                        symbol=symbol,
                        current_price=data["price"]["price"] if data["price"] else 0.0,
                        hourly_candles=data["hourly_candles"],
                        daily_candles=data["daily_candles"],
                        iv=data["iv"],
                    )

                    if not analysis:
                        result.errors.append(f"{symbol}: Analysis failed")
                        continue

                    # Generate signal
                    signal = self.strategy_engine.generate_signal(analysis)

                    if not signal:
                        continue  # No signal warranted

                    result.signals_generated += 1

                    # Validate signal against portfolio limits
                    is_valid, validation_reason = self.risk_manager.validate_signal(
                        signal, self.open_positions
                    )

                    if not is_valid:
                        self.logger.warning(
                            f"[{cycle_id}] {symbol} signal rejected: {validation_reason}"
                        )
                        result.signals_rejected += 1
                        continue

                    valid_signals.append(signal)

                except Exception as e:
                    self.logger.error(f"[{cycle_id}] {symbol} processing error: {e}")
                    result.errors.append(f"{symbol}: {str(e)[:50]}")
                    continue

            # Step 4.5: Execute valid signals with ExecutionEngine (Paper Trading)
            for signal in valid_signals:
                try:
                    exec_result = self.execution_engine.execute_signal(
                        signal=signal,
                        cycle_id=cycle_id,
                        current_bid=signal.current_price * 0.995 if signal.current_price else None,
                        current_ask=signal.current_price * 1.005 if signal.current_price else None,
                    )

                    if exec_result.executed:
                        result.signals_executed += 1
                        self.logger.info(f"[{cycle_id}] {signal.symbol} trade executed: {exec_result.trade_id}")
                    else:
                        result.signals_rejected += 1
                        self.logger.warning(f"[{cycle_id}] {signal.symbol} execution failed: {exec_result.reason}")

                except Exception as e:
                    result.signals_rejected += 1
                    self.logger.error(f"[{cycle_id}] Execution error for {signal.symbol}: {e}")

            # Step 5: Update portfolio state
            if self.open_positions:
                portfolio_state = self.risk_manager.update_portfolio_state(
                    self.open_positions
                )
                result.portfolio_delta = portfolio_state.total_delta
                result.portfolio_theta = portfolio_state.total_theta_day

            # Logging
            result.duration_seconds = time.time() - cycle_start

            self.logger.info(
                f"[{cycle_id}] Cycle complete: "
                f"analyzed={result.symbols_analyzed}, "
                f"signals={result.signals_generated}, "
                f"executed={result.signals_executed}, "
                f"rejected={result.signals_rejected}, "
                f"time={result.duration_seconds:.1f}s"
            )

            self.last_cycle_result = result
            return result

        except Exception as e:
            self.logger.error(f"[{cycle_id}] Cycle error: {e}")
            result.errors.append(f"Cycle error: {str(e)[:100]}")
            result.duration_seconds = time.time() - cycle_start
            return result

    def get_portfolio_status(self) -> Dict[str, Any]:
        """Get current portfolio status"""
        state = self.risk_manager.get_portfolio_state()

        if not state:
            return {
                "status": "no_positions",
                "positions": 0,
                "delta": 0.0,
                "theta_per_day": 0.0,
            }

        return {
            "timestamp": state.timestamp.isoformat(),
            "positions": state.open_positions,
            "delta": round(state.total_delta, 4),
            "gamma": round(state.total_gamma, 4),
            "theta_per_day": round(state.total_theta_day, 2),
            "vega": round(state.total_vega, 2),
            "notional": round(state.portfolio_notional, 2),
            "margin_used": f"{state.margin_used:.1f}%",
        }

    def get_last_cycle_result(self) -> Optional[Dict[str, Any]]:
        """Get last cycle result"""
        if not self.last_cycle_result:
            return None

        return {
            "cycle_id": self.last_cycle_result.cycle_id,
            "timestamp": self.last_cycle_result.timestamp.isoformat(),
            "symbols_analyzed": self.last_cycle_result.symbols_analyzed,
            "signals_generated": self.last_cycle_result.signals_generated,
            "signals_executed": self.last_cycle_result.signals_executed,
            "signals_rejected": self.last_cycle_result.signals_rejected,
            "duration_seconds": round(self.last_cycle_result.duration_seconds, 2),
            "errors": self.last_cycle_result.errors,
        }

    def get_paper_trading_stats(self) -> Dict[str, Any]:
        """Get paper trading performance statistics"""
        pnl = self.execution_engine.get_portfolio_pnl()
        stats = self.execution_engine.get_trade_statistics()

        return {
            "paper_trading": True,
            "pnl": {
                "realized": round(pnl["realized_pnl"], 2),
                "unrealized": round(pnl["unrealized_pnl"], 2),
                "total": round(pnl["total_pnl"], 2),
                "closed_trades": pnl["closed_trades"],
                "open_trades": pnl["open_trades"],
            },
            "statistics": {
                "total_trades": stats["total_trades"],
                "win_rate": round(stats["win_rate"], 2),
                "avg_win": round(stats["avg_win"], 2),
                "avg_loss": round(stats["avg_loss"], 2),
                "profit_factor": round(stats["profit_factor"], 2),
                "largest_win": round(stats["largest_win"], 2),
                "largest_loss": round(stats["largest_loss"], 2),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test orchestrator with small watchlist
    orchestrator = TradingOrchestrator(
        symbols=["AAPL", "MSFT"],
        account_size=100000.0,
        schedule_enabled=False,  # Don't start scheduler in test
    )

    print("\n=== Running Single Cycle ===")
    result = orchestrator.run_hourly_cycle()

    if result:
        print("\n=== Cycle Result ===")
        import json
        result_dict = {
            "cycle_id": result.cycle_id,
            "symbols_analyzed": result.symbols_analyzed,
            "signals_generated": result.signals_generated,
            "signals_executed": result.signals_executed,
            "signals_rejected": result.signals_rejected,
            "duration_seconds": result.duration_seconds,
            "errors": result.errors,
        }
        print(json.dumps(result_dict, indent=2, default=str))

    print("\n=== Portfolio Status ===")
    status = orchestrator.get_portfolio_status()
    print(json.dumps(status, indent=2, default=str))
