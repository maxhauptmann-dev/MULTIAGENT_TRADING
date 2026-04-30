"""
AnalyticsEngine Module — Technical analysis and trend detection
Computes indicators, detects trends, and assesses volatility regimes.
Integrates with DEF_INDICATORS.py for core indicator calculations.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

# Import existing indicators module
try:
    from DEF_INDICATORS import compute_indicators, compute_market_regime
except ImportError:
    compute_indicators = None
    compute_market_regime = None


class Trend(Enum):
    """Trend direction enum"""
    BULLISH = 1
    NEUTRAL = 0
    BEARISH = -1


@dataclass
class TechnicalIndicators:
    """Container for technical indicator values"""
    # RSI
    rsi_14: Optional[float] = None
    rsi_zone: Optional[str] = None  # "overbought", "neutral", "oversold"

    # MACD
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_trend: Optional[str] = None  # "bullish", "neutral", "bearish"

    # ATR
    atr_14: Optional[float] = None
    atr_pct: Optional[float] = None

    # Moving Averages
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    ema_alignment: Optional[str] = None  # "bullish", "neutral", "bearish"

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_pct_b: Optional[float] = None

    # Volume
    volume_ratio: Optional[float] = None
    volume_trend: Optional[str] = None

    # ADX / Stochastic
    adx: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None

    # Metadata
    candle_count: int = 0
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "rsi_14": self.rsi_14,
            "rsi_zone": self.rsi_zone,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "macd_trend": self.macd_trend,
            "atr_14": self.atr_14,
            "atr_pct": self.atr_pct,
            "ema_20": self.ema_20,
            "ema_50": self.ema_50,
            "ema_200": self.ema_200,
            "ema_alignment": self.ema_alignment,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "bb_mid": self.bb_mid,
            "bb_pct_b": self.bb_pct_b,
            "volume_ratio": self.volume_ratio,
            "volume_trend": self.volume_trend,
            "adx": self.adx,
            "stoch_k": self.stoch_k,
            "stoch_d": self.stoch_d,
        }


@dataclass
class TrendAnalysis:
    """Trend detection results"""
    hourly_trend: Trend
    hourly_strength: float  # 0.0-1.0 confidence
    daily_trend: Trend
    daily_strength: float  # 0.0-1.0 confidence
    combined_trend: Trend  # Synthesis of hourly + daily
    combined_strength: float
    primary_direction: str  # "bullish", "neutral", "bearish", "divergence"


@dataclass
class VolatilityRegime:
    """Volatility assessment"""
    iv: float  # Current implied volatility
    iv_percentile: float  # 0-100 ranking
    hv: float  # Historical volatility
    regime: str  # "low", "medium", "high", "extreme"
    vix_level: float  # VIX if available
    iv_crush_risk: float  # 0-1 probability
    regime_change_likely: bool


@dataclass
class Analysis:
    """Complete analysis snapshot for a symbol"""
    symbol: str
    timestamp: datetime
    current_price: float

    # Indicators
    hourly_indicators: TechnicalIndicators
    daily_indicators: TechnicalIndicators

    # Trend analysis
    trend_analysis: TrendAnalysis

    # Volatility
    volatility_regime: VolatilityRegime

    # Metadata
    hourly_candle_count: int = 0
    daily_candle_count: int = 0
    analysis_quality: str = "good"  # "good", "fair", "poor"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "current_price": self.current_price,
            "hourly_indicators": self.hourly_indicators.to_dict(),
            "daily_indicators": self.daily_indicators.to_dict(),
            "trend_analysis": {
                "hourly_trend": self.trend_analysis.hourly_trend.name,
                "hourly_strength": self.trend_analysis.hourly_strength,
                "daily_trend": self.trend_analysis.daily_trend.name,
                "daily_strength": self.trend_analysis.daily_strength,
                "combined_trend": self.trend_analysis.combined_trend.name,
                "combined_strength": self.trend_analysis.combined_strength,
                "primary_direction": self.trend_analysis.primary_direction,
            },
            "volatility_regime": {
                "iv": self.volatility_regime.iv,
                "iv_percentile": self.volatility_regime.iv_percentile,
                "hv": self.volatility_regime.hv,
                "regime": self.volatility_regime.regime,
                "vix_level": self.volatility_regime.vix_level,
                "iv_crush_risk": self.volatility_regime.iv_crush_risk,
                "regime_change_likely": self.volatility_regime.regime_change_likely,
            },
        }


# ============================================================
# AnalyticsEngine
# ============================================================

class AnalyticsEngine:
    """Main analytics engine — orchestrates indicator computation and trend detection"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        if compute_indicators is None:
            self.logger.warning(
                "DEF_INDICATORS not available; install pandas and pandas-ta"
            )

    def analyze(
        self,
        symbol: str,
        current_price: float,
        hourly_candles: List[Dict[str, float]],
        daily_candles: List[Dict[str, float]],
        iv: float = 0.25,
    ) -> Optional[Analysis]:
        """
        Complete analysis for a symbol

        Args:
            symbol: Stock symbol (e.g., "AAPL")
            current_price: Current price
            hourly_candles: List of hourly OHLCV dicts
            daily_candles: List of daily OHLCV dicts
            iv: Implied volatility (0.0-1.0)

        Returns:
            Analysis object or None if insufficient data
        """
        try:
            # Check minimum data requirements
            if len(hourly_candles) < 20:
                self.logger.warning(
                    f"{symbol}: Insufficient hourly candles ({len(hourly_candles)} < 20)"
                )
                return None

            if len(daily_candles) < 20:
                self.logger.warning(
                    f"{symbol}: Insufficient daily candles ({len(daily_candles)} < 20)"
                )
                return None

            # Compute indicators
            hourly_ind = self._compute_indicators_with_fallback(symbol, hourly_candles)
            daily_ind = self._compute_indicators_with_fallback(symbol, daily_candles)

            # Trend analysis
            trend = self._analyze_trends(hourly_ind, daily_ind)

            # Volatility regime
            vol_regime = self._assess_volatility_regime(iv, daily_ind)

            # Determine analysis quality
            quality = self._assess_quality(hourly_ind, daily_ind)

            analysis = Analysis(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                current_price=current_price,
                hourly_indicators=hourly_ind,
                daily_indicators=daily_ind,
                trend_analysis=trend,
                volatility_regime=vol_regime,
                hourly_candle_count=len(hourly_candles),
                daily_candle_count=len(daily_candles),
                analysis_quality=quality,
            )

            self.logger.info(
                f"{symbol}: {trend.primary_direction} "
                f"(hourly:{trend.hourly_trend.name} daily:{trend.daily_trend.name})"
            )

            return analysis

        except Exception as e:
            self.logger.error(f"{symbol}: Analysis error: {e}")
            return None

    # -------- Indicator Computation --------

    def _compute_indicators_with_fallback(
        self,
        symbol: str,
        candles: List[Dict[str, float]],
    ) -> TechnicalIndicators:
        """Compute indicators using DEF_INDICATORS, with fallback for missing data"""

        if compute_indicators is None:
            self.logger.warning(f"{symbol}: DEF_INDICATORS not available, using fallback")
            return self._compute_indicators_manual(candles)

        try:
            raw = compute_indicators(candles)

            if "error" in raw:
                self.logger.warning(f"{symbol}: DEF_INDICATORS error: {raw['error']}")
                return self._compute_indicators_manual(candles)

            indicators = TechnicalIndicators(raw_data=raw)

            # Extract values
            indicators.rsi_14 = raw.get("rsi_14")
            indicators.rsi_zone = raw.get("rsi_zone")

            indicators.macd = raw.get("macd")
            indicators.macd_signal = raw.get("macd_signal")
            indicators.macd_histogram = raw.get("macd_histogram")
            indicators.macd_trend = raw.get("macd_trend")

            indicators.atr_14 = raw.get("atr_14")
            indicators.atr_pct = raw.get("atr_pct")

            indicators.ema_20 = raw.get("ema_20")
            indicators.ema_50 = raw.get("ema_50")
            indicators.ema_200 = raw.get("ema_200")
            indicators.ema_alignment = raw.get("ema_alignment")

            indicators.bb_upper = raw.get("bb_upper")
            indicators.bb_lower = raw.get("bb_lower")
            indicators.bb_mid = raw.get("bb_mid")
            indicators.bb_pct_b = raw.get("bb_pct_b")

            indicators.volume_ratio = raw.get("volume_ratio")
            indicators.volume_trend = raw.get("volume_trend")

            indicators.adx = raw.get("adx")
            indicators.stoch_k = raw.get("stoch_k")
            indicators.stoch_d = raw.get("stoch_d")

            indicators.candle_count = len(candles)

            return indicators

        except Exception as e:
            self.logger.warning(f"{symbol}: Indicator computation error: {e}")
            return self._compute_indicators_manual(candles)

    def _compute_indicators_manual(
        self,
        candles: List[Dict[str, float]],
    ) -> TechnicalIndicators:
        """Minimal indicator computation without pandas-ta"""
        indicators = TechnicalIndicators(candle_count=len(candles))

        if len(candles) < 20:
            return indicators

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        # Simple SMA (not EMA, but close enough for fallback)
        indicators.ema_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
        indicators.ema_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
        indicators.ema_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else closes[-1]

        # Bollinger Bands (20-period SMA ± 2 std)
        sma_20 = indicators.ema_20
        variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
        std = variance ** 0.5
        indicators.bb_mid = sma_20
        indicators.bb_upper = sma_20 + 2 * std
        indicators.bb_lower = sma_20 - 2 * std

        # ATR (simplified: average of (high-low))
        ranges = [h - l for h, l in zip(highs[-14:], lows[-14:])]
        indicators.atr_14 = sum(ranges) / len(ranges) if ranges else 0
        indicators.atr_pct = (indicators.atr_14 / closes[-1] * 100) if closes[-1] > 0 else 0

        return indicators

    # -------- Trend Detection --------

    def _analyze_trends(
        self,
        hourly_ind: TechnicalIndicators,
        daily_ind: TechnicalIndicators,
    ) -> TrendAnalysis:
        """Detect trends from indicators"""

        # Hourly trend
        hourly_trend, hourly_strength = self._detect_trend(hourly_ind)

        # Daily trend
        daily_trend, daily_strength = self._detect_trend(daily_ind)

        # Combined trend (daily has more weight)
        combined_trend = self._combine_trends(hourly_trend, daily_trend)
        combined_strength = (hourly_strength * 0.3 + daily_strength * 0.7)

        # Primary direction
        if hourly_trend == daily_trend:
            primary = "bullish" if hourly_trend == Trend.BULLISH else (
                "bearish" if hourly_trend == Trend.BEARISH else "neutral"
            )
        else:
            primary = "divergence"

        return TrendAnalysis(
            hourly_trend=hourly_trend,
            hourly_strength=hourly_strength,
            daily_trend=daily_trend,
            daily_strength=daily_strength,
            combined_trend=combined_trend,
            combined_strength=combined_strength,
            primary_direction=primary,
        )

    def _detect_trend(self, indicators: TechnicalIndicators) -> Tuple[Trend, float]:
        """Detect trend from single timeframe indicators

        Returns: (Trend, strength: 0.0-1.0)
        """
        if indicators.raw_data.get("error"):
            return Trend.NEUTRAL, 0.5

        scores = []
        weights = []

        # RSI scoring
        if indicators.rsi_14 is not None:
            if indicators.rsi_14 > 70:
                scores.append(1.0)  # Bullish
            elif indicators.rsi_14 > 60:
                scores.append(0.7)
            elif indicators.rsi_14 > 50:
                scores.append(0.6)
            elif indicators.rsi_14 > 40:
                scores.append(0.4)
            elif indicators.rsi_14 > 30:
                scores.append(0.2)
            else:
                scores.append(0.0)  # Bearish
            weights.append(0.25)

        # MACD scoring
        if indicators.macd is not None and indicators.macd_signal is not None:
            if indicators.macd > indicators.macd_signal:
                scores.append(0.7)  # Bullish
            else:
                scores.append(0.3)  # Bearish
            weights.append(0.30)

        # EMA alignment scoring
        if (indicators.ema_20 is not None and
            indicators.ema_50 is not None and
            indicators.ema_200 is not None):

            if indicators.ema_20 > indicators.ema_50 > indicators.ema_200:
                scores.append(0.9)  # Strong bullish
            elif indicators.ema_20 < indicators.ema_50 < indicators.ema_200:
                scores.append(0.1)  # Strong bearish
            else:
                scores.append(0.5)  # Neutral
            weights.append(0.30)

        # Volume trend scoring
        if indicators.volume_ratio is not None:
            if indicators.volume_ratio > 1.2:
                scores.append(0.8)  # Strong volume
            elif indicators.volume_ratio > 1.0:
                scores.append(0.6)
            else:
                scores.append(0.4)
            weights.append(0.15)

        # Weighted average
        if not scores:
            return Trend.NEUTRAL, 0.5

        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        total_weight = sum(weights)
        score = weighted_sum / total_weight if total_weight > 0 else 0.5

        # Convert to trend
        if score > 0.65:
            trend = Trend.BULLISH
            strength = min(score, 1.0)
        elif score < 0.35:
            trend = Trend.BEARISH
            strength = min(1.0 - score, 1.0)
        else:
            trend = Trend.NEUTRAL
            strength = 1.0 - abs(score - 0.5) * 2  # Higher if closer to 0.5

        return trend, strength

    def _combine_trends(self, hourly: Trend, daily: Trend) -> Trend:
        """Combine hourly and daily trends (daily has more weight)"""
        if hourly == daily:
            return hourly

        if daily != Trend.NEUTRAL:
            return daily

        return hourly

    # -------- Volatility Assessment --------

    def _assess_volatility_regime(
        self,
        iv: float,
        daily_ind: TechnicalIndicators,
    ) -> VolatilityRegime:
        """Assess volatility regime and IV environment"""

        # Historical volatility from ATR
        hv = daily_ind.atr_pct / 100 if daily_ind.atr_pct else 0.25

        # IV Rank (simplified: percentile assumption)
        # In production, compare to 252-day IV history
        if iv < 0.15:
            iv_percentile = 20.0
        elif iv < 0.20:
            iv_percentile = 35.0
        elif iv < 0.25:
            iv_percentile = 50.0
        elif iv < 0.35:
            iv_percentile = 70.0
        elif iv < 0.50:
            iv_percentile = 85.0
        else:
            iv_percentile = 95.0

        # Regime classification
        if iv < 0.15:
            regime = "low"
        elif iv < 0.25:
            regime = "medium"
        elif iv < 0.40:
            regime = "high"
        else:
            regime = "extreme"

        # IV crush risk (high if IV > historical vol + buffer)
        iv_crush_risk = max(0, min(1, (iv - hv - 0.10) / 0.10))

        # Regime change likelihood
        regime_change_likely = iv_crush_risk > 0.7

        return VolatilityRegime(
            iv=iv,
            iv_percentile=iv_percentile,
            hv=hv,
            regime=regime,
            vix_level=iv * 100,  # Simplified proxy
            iv_crush_risk=iv_crush_risk,
            regime_change_likely=regime_change_likely,
        )

    # -------- Quality Assessment --------

    def _assess_quality(
        self,
        hourly_ind: TechnicalIndicators,
        daily_ind: TechnicalIndicators,
    ) -> str:
        """Assess data quality"""
        errors = 0

        if hourly_ind.raw_data.get("error"):
            errors += 1
        if daily_ind.raw_data.get("error"):
            errors += 1

        if hourly_ind.rsi_14 is None:
            errors += 0.5
        if daily_ind.rsi_14 is None:
            errors += 0.5

        if errors > 1.5:
            return "poor"
        elif errors > 0.5:
            return "fair"
        else:
            return "good"


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    engine = AnalyticsEngine()

    # Synthetic test data
    test_candles = [
        {
            "open": 100.0 + i * 0.5,
            "high": 101.0 + i * 0.5,
            "low": 99.0 + i * 0.5,
            "close": 100.5 + i * 0.5,
            "volume": 1000000 + i * 10000,
        }
        for i in range(100)
    ]

    hourly = test_candles[-72:]
    daily = test_candles[::5]  # Sample every 5 bars

    analysis = engine.analyze(
        symbol="AAPL",
        current_price=130.0,
        hourly_candles=hourly,
        daily_candles=daily,
        iv=0.25,
    )

    if analysis:
        print("\n=== Analysis Result ===")
        import json
        print(json.dumps(analysis.to_dict(), indent=2, default=str))
