"""
RiskManager Module — Greeks calculation and portfolio risk limits
Validates signals against portfolio limits and computes Greeks-based exposures.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math

from strategy_engine import Signal, StrategyType


@dataclass
class Greeks:
    """Option Greeks for a single leg"""
    delta: float = 0.0      # Directional exposure (-1.0 to 1.0)
    gamma: float = 0.0      # Delta sensitivity
    theta: float = 0.0      # Time decay per day ($)
    vega: float = 0.0       # IV sensitivity per 1% move
    price: float = 0.0      # Option price


@dataclass
class PositionRisk:
    """Risk metrics for a single position"""
    symbol: str
    strategy: str
    notional_value: float   # Total position value
    delta_exposure: float   # Portfolio delta contribution
    gamma_exposure: float   # Portfolio gamma contribution
    theta_per_day: float    # Daily theta contribution
    vega_exposure: float    # IV sensitivity exposure
    max_loss: float         # Maximum loss on position
    contracts: int = 1


@dataclass
class PortfolioState:
    """Current portfolio risk state"""
    timestamp: datetime
    total_delta: float      # Portfolio delta (-1.0 to 1.0)
    total_gamma: float      # Portfolio gamma exposure
    total_theta_day: float  # Daily theta bleed ($)
    total_vega: float       # Portfolio vega exposure
    open_positions: int     # Number of open option positions
    portfolio_notional: float  # Total notional exposure
    margin_used: float      # % margin utilization
    positions: List[PositionRisk] = field(default_factory=list)


# ============================================================
# RiskManager
# ============================================================

class RiskManager:
    """Manages Greeks calculation and enforces portfolio limits"""

    # Portfolio-level limits
    MAX_PORTFOLIO_DELTA = 0.30  # Max ±30% delta exposure
    MAX_THETA_BLEED_DAY = 500.0  # Max $500/day theta decay
    MAX_CONCURRENT_POSITIONS = 5  # Max 5 open options positions
    MIN_DTE = 14  # Minimum days-to-expiration
    MAX_NOTIONAL_PER_POSITION = 0.10  # Max 10% of account per position

    # Position-level limits
    MAX_DELTA_PER_POSITION = 0.20  # Max ±20% delta per position
    MAX_GAMMA_PER_POSITION = 0.10  # Max 10% gamma per position

    def __init__(self, account_size: float = 100000.0):
        self.account_size = account_size
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.portfolio_state: Optional[PortfolioState] = None

    def validate_signal(
        self,
        signal: Signal,
        current_portfolio: Optional[List[PositionRisk]] = None,
    ) -> Tuple[bool, str]:
        """
        Validate if signal meets risk requirements

        Returns:
            (is_valid: bool, reason: str)
        """
        try:
            # Calculate Greeks for the signal
            position_greeks = self._calculate_signal_greeks(signal)

            # Check position-level limits
            is_valid, reason = self._validate_position_limits(signal, position_greeks)
            if not is_valid:
                return False, reason

            # Check portfolio-level limits (if current portfolio provided)
            if current_portfolio:
                is_valid, reason = self._validate_portfolio_limits(
                    signal, position_greeks, current_portfolio
                )
                if not is_valid:
                    return False, reason

            # Check DTE requirement
            if signal.recommended_dte < self.MIN_DTE:
                return False, f"DTE {signal.recommended_dte} < minimum {self.MIN_DTE}"

            return True, "Valid"

        except Exception as e:
            self.logger.error(f"{signal.symbol}: Validation error: {e}")
            return False, f"Validation error: {e}"

    # -------- Greeks Calculation --------

    def _calculate_signal_greeks(self, signal: Signal) -> Greeks:
        """Calculate Greeks for entire signal (all legs combined)"""
        total_greeks = Greeks()

        for leg in signal.legs:
            leg_greeks = self._calculate_leg_greeks(leg, signal)

            # Add (long) or subtract (short) leg Greeks
            multiplier = 1.0 if leg.side == "long" else -1.0

            total_greeks.delta += leg_greeks.delta * multiplier
            total_greeks.gamma += leg_greeks.gamma * multiplier
            total_greeks.theta += leg_greeks.theta * multiplier
            total_greeks.vega += leg_greeks.vega * multiplier
            total_greeks.price += leg_greeks.price * multiplier

        # Scale by contracts
        total_greeks.delta *= signal.recommended_contracts
        total_greeks.gamma *= signal.recommended_contracts
        total_greeks.theta *= signal.recommended_contracts
        total_greeks.vega *= signal.recommended_contracts

        return total_greeks

    def _calculate_leg_greeks(self, leg, signal: Signal) -> Greeks:
        """Calculate Greeks for single option leg using Black-Scholes approximation"""

        # Simplified Greek calculation for demo
        # In production, use full Black-Scholes model
        current_price = signal.current_price
        strike = leg.strike
        dte = max(leg.dte_min, signal.recommended_dte)
        iv = signal.iv_percentile / 100.0 if signal.iv_percentile > 1 else 0.25
        moneyness = current_price / strike

        greeks = Greeks()

        # Delta approximation: ITM calls ~1.0, OTM calls ~0.0, ATM ~0.5
        if leg.option_type == "call":
            greeks.delta = min(max(moneyness * 0.4 + 0.3, 0.0), 1.0)
        else:  # put
            greeks.delta = -(min(max(1.0 - moneyness * 0.4 - 0.3, 0.0), 1.0))

        # Gamma: peaks at ATM, ~0.02-0.05 typically
        abs_moneyness_diff = abs(moneyness - 1.0)
        greeks.gamma = 0.05 * math.exp(-(abs_moneyness_diff ** 2) * 2)

        # Theta: positive for shorts, negative for longs
        # Approximation: ~$0.10 per day for ATM, decays with DTE
        theta_base = signal.current_price * 0.0001 * (30.0 / max(dte, 1))
        greeks.theta = theta_base if leg.side == "short" else -theta_base

        # Vega: sensitivity to IV (typically $0.01-$0.05 per 1% IV move)
        vega_base = signal.current_price * 0.02 * math.sqrt(dte / 365.0)
        greeks.vega = vega_base

        # Option price (simplified Black-Scholes estimate)
        intrinsic = max(current_price - strike, 0) if leg.option_type == "call" else max(strike - current_price, 0)
        time_value = signal.current_price * iv * math.sqrt(dte / 365.0) * 0.4
        greeks.price = intrinsic + time_value

        return greeks

    # -------- Validation --------

    def _validate_position_limits(
        self,
        signal: Signal,
        greeks: Greeks,
    ) -> Tuple[bool, str]:
        """Check position-level risk limits"""

        # Delta limit
        if abs(greeks.delta) > self.MAX_DELTA_PER_POSITION:
            return False, f"Position delta {abs(greeks.delta):.3f} > max {self.MAX_DELTA_PER_POSITION}"

        # Gamma limit
        if greeks.gamma > self.MAX_GAMMA_PER_POSITION:
            return False, f"Position gamma {greeks.gamma:.3f} > max {self.MAX_GAMMA_PER_POSITION}"

        # Notional limit
        notional = greeks.price * signal.recommended_contracts * 100  # Options are per 100 shares
        notional_pct = notional / self.account_size
        if notional_pct > self.MAX_NOTIONAL_PER_POSITION:
            return False, f"Notional {notional_pct:.1%} > max {self.MAX_NOTIONAL_PER_POSITION:.1%}"

        return True, "Position limits OK"

    def _validate_portfolio_limits(
        self,
        signal: Signal,
        signal_greeks: Greeks,
        current_positions: List[PositionRisk],
    ) -> Tuple[bool, str]:
        """Check portfolio-level limits"""

        # Check position count
        if len(current_positions) >= self.MAX_CONCURRENT_POSITIONS:
            return False, f"Already at max {self.MAX_CONCURRENT_POSITIONS} positions"

        # Calculate portfolio delta after this trade
        current_delta = sum(p.delta_exposure for p in current_positions)
        new_portfolio_delta = current_delta + signal_greeks.delta

        if abs(new_portfolio_delta) > self.MAX_PORTFOLIO_DELTA:
            return False, (
                f"Portfolio delta would be {new_portfolio_delta:.3f}, "
                f"exceeds max ±{self.MAX_PORTFOLIO_DELTA}"
            )

        # Calculate portfolio theta after this trade
        current_theta = sum(p.theta_per_day for p in current_positions)
        new_portfolio_theta = current_theta + signal_greeks.theta

        if abs(new_portfolio_theta) > self.MAX_THETA_BLEED_DAY:
            return False, (
                f"Portfolio theta would be ${new_portfolio_theta:.2f}/day, "
                f"exceeds max ${self.MAX_THETA_BLEED_DAY:.2f}"
            )

        return True, "Portfolio limits OK"

    # -------- Stop Loss / Take Profit --------

    def calculate_exits(self, signal: Signal) -> Tuple[float, float]:
        """
        Calculate stop-loss and take-profit levels

        Returns:
            (stop_loss_price, take_profit_price)
        """
        if signal.max_risk <= 0 or signal.target_profit <= 0:
            return 0.0, 0.0

        current = signal.current_price

        # Direction-based SL/TP
        if signal.direction == "bullish":
            # Risk is downside, profit is upside
            stop_loss = current - signal.max_risk
            take_profit = current + signal.target_profit
        elif signal.direction == "bearish":
            # Risk is upside, profit is downside
            stop_loss = current + signal.max_risk
            take_profit = current - signal.target_profit
        else:
            # Income/neutral: risk is on both sides
            stop_loss = current - signal.max_risk
            take_profit = current + signal.target_profit

        return stop_loss, take_profit

    # -------- Portfolio State --------

    def update_portfolio_state(
        self,
        positions: List[PositionRisk],
    ) -> PortfolioState:
        """Update portfolio risk state"""

        total_delta = sum(p.delta_exposure for p in positions)
        total_gamma = sum(p.gamma_exposure for p in positions)
        total_theta = sum(p.theta_per_day for p in positions)
        total_vega = sum(p.vega_exposure for p in positions)

        notional = sum(p.notional_value for p in positions)
        margin = (notional / self.account_size) * 100 if self.account_size > 0 else 0

        self.portfolio_state = PortfolioState(
            timestamp=datetime.now(timezone.utc),
            total_delta=total_delta,
            total_gamma=total_gamma,
            total_theta_day=total_theta,
            total_vega=total_vega,
            open_positions=len(positions),
            portfolio_notional=notional,
            margin_used=margin,
            positions=positions,
        )

        self.logger.info(
            f"Portfolio: delta={total_delta:.3f}, theta=${total_theta:.2f}/day, "
            f"positions={len(positions)}, margin={margin:.1f}%"
        )

        return self.portfolio_state

    def get_portfolio_state(self) -> Optional[PortfolioState]:
        """Get current portfolio state"""
        return self.portfolio_state


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from strategy_engine import SignalLeg

    manager = RiskManager(account_size=100000.0)

    # Create test signal
    test_signal = Signal(
        symbol="AAPL",
        strategy=StrategyType.BULL_CALL_SPREAD,
        direction="bullish",
        confidence=0.80,
        signal_strength=0.75,
        entry_reason="Test bullish setup",
        iv_percentile=30.0,
        volatility_regime="low",
        recommended_contracts=2,
        recommended_dte=30,
        legs=[
            SignalLeg(
                option_type="call",
                strike=150.0,
                quantity=2,
                delta_target=0.50,
                side="long",
            ),
            SignalLeg(
                option_type="call",
                strike=153.0,
                quantity=2,
                delta_target=0.25,
                side="short",
            ),
        ],
        max_risk=300.0,
        target_profit=150.0,
    )

    # Set current price for Greeks calculation
    current_price = 150.0

    # Monkey-patch current_price for this test
    test_signal.current_price = current_price

    # Validate signal
    print("\n=== Signal Validation ===")
    is_valid, reason = manager.validate_signal(test_signal)
    print(f"Valid: {is_valid}, Reason: {reason}")

    # Calculate Greeks
    print("\n=== Greeks Calculation ===")
    greeks = manager._calculate_signal_greeks(test_signal)
    print(f"Delta: {greeks.delta:.4f}")
    print(f"Gamma: {greeks.gamma:.4f}")
    print(f"Theta: ${greeks.theta:.2f}/day")
    print(f"Vega: ${greeks.vega:.2f}")

    # Calculate exits
    print("\n=== Exit Levels ===")
    sl, tp = manager.calculate_exits(test_signal)
    print(f"Stop Loss: ${sl:.2f}")
    print(f"Take Profit: ${tp:.2f}")

    # Portfolio state
    print("\n=== Portfolio State ===")
    position = PositionRisk(
        symbol="AAPL",
        strategy="bull_call_spread",
        notional_value=3000.0,
        delta_exposure=greeks.delta,
        gamma_exposure=greeks.gamma,
        theta_per_day=greeks.theta,
        vega_exposure=greeks.vega,
        max_loss=300.0,
        contracts=2,
    )
    state = manager.update_portfolio_state([position])

    import json
    print(json.dumps({
        "total_delta": state.total_delta,
        "total_theta_day": state.total_theta_day,
        "open_positions": state.open_positions,
        "margin_used": f"{state.margin_used:.1f}%",
    }, indent=2))
