"""
Unit Tests for RiskManager Module
Tests Greeks calculation, validation, and portfolio limits
"""

import unittest
import logging
from datetime import datetime, timezone

from risk_manager import (
    RiskManager, Greeks, PositionRisk, PortfolioState
)
from strategy_engine import Signal, SignalLeg, StrategyType

logging.basicConfig(level=logging.WARNING)


class TestGreeks(unittest.TestCase):
    """Test Greeks data class"""

    def test_creation(self):
        """Test Greeks creation"""
        greeks = Greeks(delta=0.5, gamma=0.05, theta=-0.10, vega=2.0)
        self.assertEqual(greeks.delta, 0.5)
        self.assertEqual(greeks.theta, -0.10)


class TestPositionRisk(unittest.TestCase):
    """Test PositionRisk data class"""

    def test_creation(self):
        """Test PositionRisk creation"""
        pos = PositionRisk(
            symbol="AAPL",
            strategy="bull_call_spread",
            notional_value=3000.0,
            delta_exposure=0.15,
            gamma_exposure=0.05,
            theta_per_day=-0.50,
            vega_exposure=2.0,
            max_loss=300.0,
            contracts=2,
        )
        self.assertEqual(pos.symbol, "AAPL")
        self.assertEqual(pos.delta_exposure, 0.15)


class TestRiskManager(unittest.TestCase):
    """Test RiskManager"""

    def setUp(self):
        self.manager = RiskManager(account_size=100000.0)

    def _create_test_signal(self, direction: str = "bullish") -> Signal:
        """Helper to create test signal"""
        signal = Signal(
            symbol="AAPL",
            strategy=StrategyType.BULL_CALL_SPREAD,
            direction=direction,
            confidence=0.80,
            signal_strength=0.75,
            entry_reason="Test",
            iv_percentile=30.0,
            volatility_regime="low",
            recommended_contracts=1,
            recommended_dte=30,
            legs=[
                SignalLeg(
                    option_type="call",
                    strike=150.0,
                    quantity=1,
                    delta_target=0.50,
                    side="long",
                ),
            ],
            max_risk=300.0,
            target_profit=150.0,
        )
        signal.current_price = 150.0
        return signal

    def test_initialization(self):
        """Test RiskManager init"""
        self.assertEqual(self.manager.account_size, 100000.0)
        self.assertIsNotNone(self.manager.logger)

    def test_validate_signal_valid(self):
        """Test signal validation - valid signal"""
        signal = self._create_test_signal()
        is_valid, reason = self.manager.validate_signal(signal)
        self.assertTrue(is_valid)

    def test_validate_signal_low_dte(self):
        """Test signal validation - DTE too low"""
        signal = self._create_test_signal()
        signal.recommended_dte = 5  # Below minimum 14
        is_valid, reason = self.manager.validate_signal(signal)
        self.assertFalse(is_valid)
        self.assertIn("DTE", reason)

    def test_calculate_greeks(self):
        """Test Greeks calculation"""
        signal = self._create_test_signal()
        greeks = self.manager._calculate_signal_greeks(signal)

        self.assertIsNotNone(greeks.delta)
        self.assertIsNotNone(greeks.gamma)
        self.assertIsNotNone(greeks.theta)
        # Deltas should be positive for long call
        self.assertGreater(greeks.delta, 0)

    def test_calculate_exits(self):
        """Test stop-loss and take-profit calculation"""
        signal = self._create_test_signal()
        sl, tp = self.manager.calculate_exits(signal)

        # For bullish: SL below current, TP above current
        self.assertLess(sl, signal.current_price)
        self.assertGreater(tp, signal.current_price)

    def test_calculate_exits_bearish(self):
        """Test exits for bearish direction"""
        signal = self._create_test_signal(direction="bearish")
        sl, tp = self.manager.calculate_exits(signal)

        # For bearish: SL above current, TP below current
        self.assertGreater(sl, signal.current_price)
        self.assertLess(tp, signal.current_price)

    def test_portfolio_state(self):
        """Test portfolio state tracking"""
        pos = PositionRisk(
            symbol="AAPL",
            strategy="bull_call_spread",
            notional_value=3000.0,
            delta_exposure=0.15,
            gamma_exposure=0.05,
            theta_per_day=-0.50,
            vega_exposure=2.0,
            max_loss=300.0,
        )

        state = self.manager.update_portfolio_state([pos])

        self.assertEqual(state.open_positions, 1)
        self.assertEqual(state.total_delta, 0.15)
        self.assertEqual(state.total_theta_day, -0.50)

    def test_portfolio_state_multiple_positions(self):
        """Test portfolio state with multiple positions"""
        positions = [
            PositionRisk(
                symbol="AAPL",
                strategy="bull_call_spread",
                notional_value=3000.0,
                delta_exposure=0.15,
                gamma_exposure=0.05,
                theta_per_day=-0.50,
                vega_exposure=2.0,
                max_loss=300.0,
            ),
            PositionRisk(
                symbol="MSFT",
                strategy="bear_put_spread",
                notional_value=3000.0,
                delta_exposure=-0.10,
                gamma_exposure=0.03,
                theta_per_day=0.30,
                vega_exposure=1.5,
                max_loss=300.0,
            ),
        ]

        state = self.manager.update_portfolio_state(positions)

        self.assertEqual(state.open_positions, 2)
        self.assertAlmostEqual(state.total_delta, 0.05, places=2)  # 0.15 - 0.10
        self.assertAlmostEqual(state.total_theta_day, -0.20, places=2)  # -0.50 + 0.30

    def test_validate_portfolio_limits(self):
        """Test portfolio limit validation"""
        # Create a position that violates delta limit
        signal = self._create_test_signal()
        greeks = Greeks(delta=0.25, gamma=0.05, theta=-0.10, vega=2.0, price=100.0)

        # No current positions, should validate
        is_valid, reason = self.manager._validate_portfolio_limits(
            signal, greeks, []
        )
        self.assertTrue(is_valid)

        # With current positions that would exceed limit
        current_pos = [
            PositionRisk(
                symbol="XYZ",
                strategy="test",
                notional_value=3000.0,
                delta_exposure=0.25,  # High delta
                gamma_exposure=0.05,
                theta_per_day=-0.10,
                vega_exposure=2.0,
                max_loss=300.0,
            ),
        ]

        # Adding another 0.25 delta would exceed 0.30 limit
        is_valid, reason = self.manager._validate_portfolio_limits(
            signal, greeks, current_pos
        )
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()
