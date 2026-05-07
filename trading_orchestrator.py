"""
TradingOrchestrator Module — Central coordination and hourly scheduling
Orchestrates all modules: DataFetcher → AnalyticsEngine → StrategyEngine → RiskManager
"""

import logging
import json
import os
import requests
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

        # Option exit tracking: OCC symbol → max unrealized_plpc seen (high-water mark)
        self._option_hwm: Dict[str, float] = {}

        # Scheduler
        self.scheduler = None
        if SCHEDULER_AVAILABLE and schedule_enabled:
            self._init_scheduler()

        # Alpaca credentials for stop-loss monitoring
        self._alpaca_key = os.getenv("APCA_API_KEY_ID", "")
        self._alpaca_secret = os.getenv("APCA_API_SECRET_KEY", "")
        self._alpaca_base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self._alpaca_headers = {
            "APCA-API-KEY-ID": self._alpaca_key,
            "APCA-API-SECRET-KEY": self._alpaca_secret,
        }

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

        # Step 0a: Check stop-losses on ALL Alpaca positions (incl. manually opened)
        stopped = self.check_alpaca_stop_losses(hard_stop_pct=0.05)
        if stopped:
            self.logger.warning(f"[{cycle_id}] Stop-loss closed {len(stopped)} positions: {[s['symbol'] for s in stopped]}")

        # Step 0b: Close option positions that conflict with current signal direction
        reconciled = self.reconcile_option_positions()
        if reconciled:
            self.logger.warning(f"[{cycle_id}] Reconciled {len(reconciled)} conflicting options: {[r['symbol'] for r in reconciled]}")

        # Step 0c: Option stop-loss + profit-lock exits
        exited = self.check_option_exits()
        if exited:
            self.logger.warning(f"[{cycle_id}] Option exits: {[e['symbol'] + ' ' + e['reason'] for e in exited]}")

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

                    # Get current price: use API if available, fallback to last hourly close
                    if data["price"]:
                        current_price = data["price"]["price"]
                    else:
                        # Fallback: use last hourly candle close price
                        current_price = data["hourly_candles"][-1].close if data["hourly_candles"] else 100.0

                    # Analyze
                    analysis = self.analytics_engine.analyze(
                        symbol=symbol,
                        current_price=current_price,
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

    def check_alpaca_stop_losses(self, hard_stop_pct: float = 0.05) -> List[Dict]:
        """
        Fetch all open Alpaca positions and close any that exceed the stop-loss.
        Runs every cycle so existing positions (incl. manually opened) are protected.
        """
        closed = []
        try:
            resp = requests.get(
                f"{self._alpaca_base}/v2/positions",
                headers=self._alpaca_headers,
                timeout=10,
            )
            if resp.status_code != 200:
                self.logger.warning(f"[StopLoss] Could not fetch positions: {resp.status_code}")
                return closed

            positions = resp.json()
        except Exception as e:
            self.logger.warning(f"[StopLoss] Fetch error: {e}")
            return closed

        for pos in positions:
            symbol = pos.get("symbol", "")
            qty = float(pos.get("qty", 0))
            side = pos.get("side", "long")  # "long" or "short"
            avg_entry = float(pos.get("avg_entry_price", 0))
            current_price = float(pos.get("current_price", 0))
            unrealized_plpc = float(pos.get("unrealized_plpc", 0))  # already as fraction

            if avg_entry <= 0 or current_price <= 0:
                continue

            # Calculate loss % (positive = loss)
            if side == "long":
                loss_pct = (avg_entry - current_price) / avg_entry
            else:  # short
                loss_pct = (current_price - avg_entry) / avg_entry

            if loss_pct < hard_stop_pct:
                continue

            self.logger.warning(
                f"[StopLoss] {symbol} {side} — loss {loss_pct*100:.1f}% > {hard_stop_pct*100:.0f}% threshold → CLOSING"
            )

            # Place market order to close
            close_side = "sell" if side == "long" else "buy"
            close_qty = abs(qty)
            try:
                order_resp = requests.post(
                    f"{self._alpaca_base}/v2/orders",
                    headers={**self._alpaca_headers, "Content-Type": "application/json"},
                    json={
                        "symbol": symbol,
                        "qty": str(int(close_qty)),
                        "side": close_side,
                        "type": "market",
                        "time_in_force": "day",
                    },
                    timeout=10,
                )
                if order_resp.status_code in (200, 201):
                    self.logger.warning(
                        f"[StopLoss] ✓ {symbol} close order placed (loss={loss_pct*100:.1f}%)"
                    )
                    closed.append({"symbol": symbol, "side": side, "loss_pct": loss_pct})
                else:
                    self.logger.error(
                        f"[StopLoss] ✗ {symbol} close order failed: {order_resp.status_code} {order_resp.text[:100]}"
                    )
            except Exception as e:
                self.logger.error(f"[StopLoss] ✗ {symbol} close order error: {e}")

        return closed

    def close_all_option_positions(self) -> List[Dict]:
        """
        Immediately close ALL open option positions via limit orders at 98% of current price.
        Used for cleanup after strategy bugs or manual resets.
        """
        import re
        closed = []
        occ_pattern = re.compile(r'^([A-Z]{1,6})(\d{6})([PC])(\d{8})$')

        try:
            resp = requests.get(
                f"{self._alpaca_base}/v2/positions",
                headers=self._alpaca_headers, timeout=10,
            )
            if resp.status_code != 200:
                self.logger.warning(f"[CloseAll] Could not fetch positions: {resp.status_code}")
                return closed
            positions = resp.json()
        except Exception as e:
            self.logger.warning(f"[CloseAll] Fetch error: {e}")
            return closed

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not occ_pattern.match(symbol):
                continue
            qty = float(pos.get("qty", 0))
            current_price = float(pos.get("current_price", 0))
            unrealized_plpc = float(pos.get("unrealized_plpc", 0))

            limit_price = round(current_price * 0.98, 2) if current_price > 0 else None
            order_body: Dict = {
                "symbol": symbol,
                "qty": str(int(abs(qty))),
                "side": "sell",
                "type": "limit" if limit_price else "market",
                "time_in_force": "day",
            }
            if limit_price:
                order_body["limit_price"] = str(limit_price)

            try:
                r = requests.post(
                    f"{self._alpaca_base}/v2/orders",
                    headers={**self._alpaca_headers, "Content-Type": "application/json"},
                    json=order_body, timeout=10,
                )
                if r.status_code in (200, 201):
                    self.logger.warning(
                        f"[CloseAll] ✓ {symbol} close order @ ${limit_price} "
                        f"(P&L: {unrealized_plpc*100:.1f}%)"
                    )
                    closed.append({"symbol": symbol, "pnl_pct": round(unrealized_plpc * 100, 2)})
                else:
                    self.logger.error(f"[CloseAll] ✗ {symbol}: {r.status_code} {r.text[:100]}")
            except Exception as e:
                self.logger.error(f"[CloseAll] ✗ {symbol}: {e}")

        return closed

    def check_option_exits(self) -> List[Dict]:
        """
        Manages option exits via hard stop-loss and profit-locking tiers.

        Hard stop-loss:  option loses > 35% of entry price → close immediately.
        Profit-locking:  tracks high-water mark (HWM) per position.
                         Once HWM crosses a tier, a floor is set.
                         If P&L drops below the floor → close to lock in gains.

        Profit tiers (unrealized_plpc, i.e. 0.40 = +40%):
            HWM ≥ +150% → floor +100%
            HWM ≥ +100% → floor  +75%
            HWM ≥  +80% → floor  +60%
            HWM ≥  +60% → floor  +40%
            HWM ≥  +40% → floor  +20%
        """
        import re

        OPTION_STOP_LOSS = -0.20        # -20% on option premium (tighter)
        PROFIT_FLOORS = [
            (1.50, 1.00),
            (1.00, 0.75),
            (0.80, 0.60),
            (0.60, 0.40),
            (0.40, 0.20),
        ]

        closed = []
        occ_pattern = re.compile(r'^([A-Z]{1,6})(\d{6})([PC])(\d{8})$')

        try:
            resp = requests.get(
                f"{self._alpaca_base}/v2/positions",
                headers=self._alpaca_headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return closed
            positions = resp.json()
        except Exception as e:
            self.logger.warning(f"[OptionExit] Fetch error: {e}")
            return closed

        for pos in positions:
            symbol = pos.get("symbol", "")
            if not occ_pattern.match(symbol):
                continue

            qty = float(pos.get("qty", 0))
            current_price = float(pos.get("current_price", 0))
            unrealized_plpc = float(pos.get("unrealized_plpc", 0))

            # Update high-water mark
            hwm = max(self._option_hwm.get(symbol, unrealized_plpc), unrealized_plpc)
            self._option_hwm[symbol] = hwm

            # Determine active profit floor from HWM
            active_floor = None
            for threshold, floor in PROFIT_FLOORS:
                if hwm >= threshold:
                    active_floor = floor
                    break

            # Evaluate exit conditions
            exit_reason: Optional[str] = None

            if unrealized_plpc <= OPTION_STOP_LOSS:
                exit_reason = (
                    f"stop-loss ({unrealized_plpc*100:.1f}% ≤ "
                    f"-{abs(OPTION_STOP_LOSS)*100:.0f}%)"
                )
            elif active_floor is not None and unrealized_plpc < active_floor:
                exit_reason = (
                    f"profit-lock fell below floor "
                    f"(HWM={hwm*100:.0f}% → floor={active_floor*100:.0f}%, "
                    f"now={unrealized_plpc*100:.1f}%)"
                )

            if exit_reason is None:
                continue

            self.logger.warning(f"[OptionExit] {symbol} → {exit_reason}")

            limit_price = round(current_price * 0.98, 2) if current_price > 0 else None
            order_body: Dict = {
                "symbol": symbol,
                "qty": str(int(abs(qty))),
                "side": "sell",
                "type": "limit" if limit_price else "market",
                "time_in_force": "day",
            }
            if limit_price:
                order_body["limit_price"] = str(limit_price)

            try:
                order_resp = requests.post(
                    f"{self._alpaca_base}/v2/orders",
                    headers={**self._alpaca_headers, "Content-Type": "application/json"},
                    json=order_body,
                    timeout=10,
                )
                if order_resp.status_code in (200, 201):
                    self.logger.info(f"[OptionExit] ✓ {symbol} closed — {exit_reason}")
                    closed.append({
                        "symbol": symbol,
                        "reason": exit_reason,
                        "pnl_pct": round(unrealized_plpc * 100, 2),
                        "hwm_pct": round(hwm * 100, 2),
                    })
                    self._option_hwm.pop(symbol, None)
                else:
                    self.logger.error(
                        f"[OptionExit] ✗ {symbol}: {order_resp.status_code} {order_resp.text[:120]}"
                    )
            except Exception as e:
                self.logger.error(f"[OptionExit] ✗ {symbol}: {e}")

        return closed

    def reconcile_option_positions(self) -> List[Dict]:
        """
        Close option positions whose direction conflicts with current signal.
        Catches positions opened under stale/buggy strategy logic.
        Long Put on bullish stock → close. Long Call on bearish stock → close.
        """
        import re
        closed = []
        occ_pattern = re.compile(r'^([A-Z]{1,6})(\d{6})([PC])(\d{8})$')

        try:
            resp = requests.get(
                f"{self._alpaca_base}/v2/positions",
                headers=self._alpaca_headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return closed
            positions = resp.json()
        except Exception as e:
            self.logger.warning(f"[Reconcile] Fetch error: {e}")
            return closed

        for pos in positions:
            symbol = pos.get("symbol", "")
            match = occ_pattern.match(symbol)
            if not match:
                continue  # Not an option

            underlying = match.group(1)
            opt_type = match.group(3)  # P or C
            qty = float(pos.get("qty", 0))
            current_price = float(pos.get("current_price", 0))
            unrealized_plpc = float(pos.get("unrealized_plpc", 0))

            if underlying not in self.symbols:
                continue

            try:
                data = self.data_fetcher.fetch_all_symbols([underlying]).get(underlying)
                if not data or not data.get("hourly_candles") or not data.get("daily_candles"):
                    continue

                price = data["price"]["price"] if data.get("price") else data["hourly_candles"][-1].close
                analysis = self.analytics_engine.analyze(
                    symbol=underlying,
                    current_price=price,
                    hourly_candles=data["hourly_candles"],
                    daily_candles=data["daily_candles"],
                    iv=data["iv"],
                )
                if not analysis:
                    continue

                signal = self.strategy_engine.generate_signal(analysis)
                if not signal:
                    continue

                direction = signal.direction  # "bullish" or "bearish"

                # Conflict: long put on bullish signal, or long call on bearish signal
                is_conflict = (opt_type == "P" and direction == "bullish") or \
                              (opt_type == "C" and direction == "bearish")

                if not is_conflict:
                    continue

                self.logger.warning(
                    f"[Reconcile] {symbol} ({opt_type}) conflicts with {direction} signal "
                    f"(P&L: {unrealized_plpc*100:.1f}%) → CLOSING"
                )

                # Limit order at 98% of current price (willing to accept small discount to exit quickly)
                limit_price = round(current_price * 0.98, 2) if current_price > 0 else None
                order_body: Dict = {
                    "symbol": symbol,
                    "qty": str(int(abs(qty))),
                    "side": "sell",
                    "type": "limit" if limit_price else "market",
                    "time_in_force": "day",
                }
                if limit_price:
                    order_body["limit_price"] = str(limit_price)

                order_resp = requests.post(
                    f"{self._alpaca_base}/v2/orders",
                    headers={**self._alpaca_headers, "Content-Type": "application/json"},
                    json=order_body,
                    timeout=10,
                )
                if order_resp.status_code in (200, 201):
                    self.logger.info(
                        f"[Reconcile] ✓ {symbol} close order placed @ ${limit_price}"
                    )
                    closed.append({
                        "symbol": symbol,
                        "underlying": underlying,
                        "opt_type": opt_type,
                        "direction": direction,
                        "pnl_pct": round(unrealized_plpc * 100, 2),
                    })
                else:
                    self.logger.error(
                        f"[Reconcile] ✗ {symbol} close failed: {order_resp.status_code} {order_resp.text[:120]}"
                    )

            except Exception as e:
                self.logger.error(f"[Reconcile] Error processing {underlying}: {e}")
                continue

        return closed


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    import time as _time
    logging.basicConfig(level=logging.INFO)

    # Expanded watchlist — diverse sectors for more signal opportunities
    SYMBOLS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",  # Tech
        "META", "TSLA",                              # Growth
        "AMD", "INTC",                               # Semiconductors
        "JPM", "GS",                                 # Finance
        "SPY", "QQQ",                                # ETFs
    ]

    orchestrator = TradingOrchestrator(
        symbols=SYMBOLS,
        account_size=100000.0,
        schedule_enabled=True,  # Run hourly via APScheduler
    )

    orchestrator.start()

    # Close ALL open option positions (cleanup from bug-era)
    print("\n=== Closing All Existing Option Positions ===")
    all_closed = orchestrator.close_all_option_positions()
    if all_closed:
        import json as _json2
        print(_json2.dumps(all_closed, indent=2))
    else:
        print("No open option positions found.")

    # Reconcile any remaining conflicting positions
    print("\n=== Reconciling Conflicting Option Positions ===")
    reconciled = orchestrator.reconcile_option_positions()
    if reconciled:
        import json as _json
        print(_json.dumps(reconciled, indent=2))
    else:
        print("No conflicting positions found.")

    # Run first cycle immediately on startup
    print("\n=== Running Initial Cycle ===")
    result = orchestrator.run_hourly_cycle()
    if result:
        import json
        print(json.dumps({
            "cycle_id": result.cycle_id,
            "symbols_analyzed": result.symbols_analyzed,
            "signals_generated": result.signals_generated,
            "signals_executed": result.signals_executed,
            "signals_rejected": result.signals_rejected,
            "duration_seconds": round(result.duration_seconds, 1),
            "errors": result.errors,
        }, indent=2, default=str))

    print("\n=== Scheduler running (hourly cycles) — Ctrl+C to stop ===")
    try:
        while True:
            _time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        orchestrator.stop()
        print("Orchestrator stopped.")
