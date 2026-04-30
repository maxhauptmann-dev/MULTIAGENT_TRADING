"""
Unit Tests for AnalyticsEngine Module
Tests trend detection, indicator computation, and volatility assessment
"""

import unittest
import logging
from datetime import datetime, timezone

from analytics_engine import (
    AnalyticsEngine,
    Trend,
    TechnicalIndicators,
    TrendAnalysis,
    VolatilityRegime,
    Analysis,
)

# Configure logging for tests
logging.basicConfig(level=logging.WARNING)


class TestTechnicalIndicators(unittest.TestCase):
    """Test TechnicalIndicators data class"""

    def test_creation(self):
        """Test indicator creation"""
        ind = TechnicalIndicators(
            rsi_14=55.5,
            rsi_zone="neutral",
            atr_14=2.5,
            ema_20=150.0,
        )

        self.assertEqual(ind.rsi_14, 55.5)
        self.assertEqual(ind.ema_20, 150.0)

    def test_to_dict(self):
        """Test serialization"""
        ind = TechnicalIndicators(rsi_14=55.5, atr_14=2.5)
        result = ind.to_dict()

        self.assertIn("rsi_14", result)
        self.assertEqual(result["rsi_14"], 55.5)


class TestTrendAnalysis(unittest.TestCase):
    """Test TrendAnalysis data class"""

    def test_creation(self):
        """Test trend analysis creation"""
        analysis = TrendAnalysis(
            hourly_trend=Trend.BULLISH,
            hourly_strength=0.8,
            daily_trend=Trend.BULLISH,
            daily_strength=0.9,
            combined_trend=Trend.BULLISH,
            combined_strength=0.85,
            primary_direction="bullish",
        )

        self.assertEqual(analysis.hourly_trend, Trend.BULLISH)
        self.assertEqual(analysis.combined_strength, 0.85)


class TestAnalyticsEngine(unittest.TestCase):
    """Test AnalyticsEngine"""

    def setUp(self):
        self.engine = AnalyticsEngine()
        # Synthetic test data
        self.test_candles = [
            {
                "open": 100.0 + i * 0.5,
                "high": 101.0 + i * 0.5,
                "low": 99.0 + i * 0.5,
                "close": 100.5 + i * 0.5,
                "volume": 1000000 + i * 10000,
            }
            for i in range(100)
        ]

    def test_initialization(self):
        """Test engine initialization"""
        self.assertIsNotNone(self.engine.logger)

    def test_analyze_sufficient_data(self):
        """Test analysis with sufficient data"""
        hourly = self.test_candles[-72:]
        daily = self.test_candles[::5]

        result = self.engine.analyze(
            symbol="AAPL",
            current_price=130.0,
            hourly_candles=hourly,
            daily_candles=daily,
            iv=0.25,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.symbol, "AAPL")
        self.assertEqual(result.current_price, 130.0)
        self.assertIsNotNone(result.trend_analysis)
        self.assertIsNotNone(result.volatility_regime)

    def test_analyze_insufficient_hourly(self):
        """Test with insufficient hourly candles"""
        hourly = self.test_candles[:10]  # Too few
        daily = self.test_candles[::5]

        result = self.engine.analyze(
            symbol="AAPL",
            current_price=130.0,
            hourly_candles=hourly,
            daily_candles=daily,
            iv=0.25,
        )

        self.assertIsNone(result)

    def test_analyze_insufficient_daily(self):
        """Test with insufficient daily candles"""
        hourly = self.test_candles[-72:]
        daily = self.test_candles[:10]  # Too few

        result = self.engine.analyze(
            symbol="AAPL",
            current_price=130.0,
            hourly_candles=hourly,
            daily_candles=daily,
            iv=0.25,
        )

        self.assertIsNone(result)

    def test_detect_trend_bullish(self):
        """Test trend detection with bullish indicators"""
        ind = TechnicalIndicators(
            rsi_14=75.0,  # Overbought -> Bullish
            macd=5.0,
            macd_signal=3.0,  # MACD above signal -> Bullish
            ema_20=150.0,
            ema_50=140.0,
            ema_200=130.0,  # 20 > 50 > 200 -> Bullish
            volume_ratio=1.5,  # High volume -> Bullish
        )

        trend, strength = self.engine._detect_trend(ind)

        self.assertEqual(trend, Trend.BULLISH)
        self.assertGreater(strength, 0.65)

    def test_detect_trend_bearish(self):
        """Test trend detection with bearish indicators"""
        ind = TechnicalIndicators(
            rsi_14=25.0,  # Oversold -> Bearish
            macd=-5.0,
            macd_signal=-3.0,  # MACD below signal -> Bearish
            ema_20=130.0,
            ema_50=140.0,
            ema_200=150.0,  # 20 < 50 < 200 -> Bearish
            volume_ratio=1.5,
        )

        trend, strength = self.engine._detect_trend(ind)

        self.assertEqual(trend, Trend.BEARISH)
        self.assertGreater(strength, 0.65)

    def test_detect_trend_neutral(self):
        """Test trend detection with neutral indicators"""
        ind = TechnicalIndicators(
            rsi_14=50.0,  # Neutral
            macd=0.0,
            macd_signal=0.0,  # At signal line -> Neutral
            ema_20=140.0,
            ema_50=140.0,  # Aligned but no clear direction
            ema_200=150.0,
            volume_ratio=0.9,
        )

        trend, strength = self.engine._detect_trend(ind)

        self.assertEqual(trend, Trend.NEUTRAL)

    def test_combine_trends(self):
        """Test trend combination"""
        # Same trends
        result = self.engine._combine_trends(Trend.BULLISH, Trend.BULLISH)
        self.assertEqual(result, Trend.BULLISH)

        # Different trends, daily takes priority
        result = self.engine._combine_trends(Trend.BEARISH, Trend.BULLISH)
        self.assertEqual(result, Trend.BULLISH)

        # Daily neutral, hourly wins
        result = self.engine._combine_trends(Trend.BEARISH, Trend.NEUTRAL)
        self.assertEqual(result, Trend.BEARISH)

    def test_assess_volatility_regime_low(self):
        """Test volatility regime assessment - low IV"""
        ind = TechnicalIndicators(atr_pct=0.5)  # Very low volatility

        regime = self.engine._assess_volatility_regime(iv=0.10, daily_ind=ind)

        self.assertEqual(regime.regime, "low")
        self.assertLess(regime.iv_percentile, 50)

    def test_assess_volatility_regime_high(self):
        """Test volatility regime assessment - high IV"""
        ind = TechnicalIndicators(atr_pct=1.0)

        regime = self.engine._assess_volatility_regime(iv=0.35, daily_ind=ind)

        self.assertEqual(regime.regime, "high")
        self.assertGreater(regime.iv_percentile, 70)

    def test_assess_volatility_regime_extreme(self):
        """Test volatility regime assessment - extreme IV"""
        ind = TechnicalIndicators(atr_pct=2.0)

        regime = self.engine._assess_volatility_regime(iv=0.60, daily_ind=ind)

        self.assertEqual(regime.regime, "extreme")
        self.assertGreater(regime.iv_percentile, 90)

    def test_assess_quality_good(self):
        """Test quality assessment - good"""
        hourly = TechnicalIndicators(
            rsi_14=55.0,
            macd=1.0,
            ema_20=150.0,
        )
        daily = TechnicalIndicators(
            rsi_14=60.0,
            macd=2.0,
            ema_50=145.0,
        )

        quality = self.engine._assess_quality(hourly, daily)

        self.assertEqual(quality, "good")

    def test_assess_quality_poor(self):
        """Test quality assessment - poor"""
        hourly = TechnicalIndicators(raw_data={"error": "test error"})
        daily = TechnicalIndicators(raw_data={"error": "test error"})

        quality = self.engine._assess_quality(hourly, daily)

        self.assertEqual(quality, "poor")

    def test_compute_indicators_manual_fallback(self):
        """Test manual indicator computation fallback"""
        candles = self.test_candles[-50:]

        ind = self.engine._compute_indicators_manual(candles)

        self.assertIsNotNone(ind.ema_20)
        self.assertIsNotNone(ind.ema_50)
        self.assertIsNotNone(ind.atr_14)
        self.assertIsNotNone(ind.bb_upper)
        self.assertIsNotNone(ind.bb_lower)

    def test_analysis_object_creation(self):
        """Test Analysis object creation and serialization"""
        hourly = self.test_candles[-72:]
        daily = self.test_candles[::5]

        analysis = self.engine.analyze(
            symbol="MSFT",
            current_price=350.0,
            hourly_candles=hourly,
            daily_candles=daily,
            iv=0.30,
        )

        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.symbol, "MSFT")

        # Test serialization
        data = analysis.to_dict()
        self.assertIn("symbol", data)
        self.assertIn("trend_analysis", data)
        self.assertIn("volatility_regime", data)


if __name__ == "__main__":
    unittest.main()
