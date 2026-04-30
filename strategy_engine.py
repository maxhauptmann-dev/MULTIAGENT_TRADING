"""
StrategyEngine Module — Signal generation with intelligent decision tree
Generates trading signals and strategy selections based on technical analysis.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from analytics_engine import Analysis, Trend


class StrategyType(Enum):
    """Available options strategies"""
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    PROTECTIVE_PUT = "protective_put"
    COVERED_CALL = "covered_call"
    CALENDAR_SPREAD = "calendar_spread"
    DIRECTIONAL_CALL = "directional_call"
    DIRECTIONAL_PUT = "directional_put"


@dataclass
class SignalLeg:
    """Single leg of a multi-leg strategy"""
    option_type: str  # "call" or "put"
    strike: float
    quantity: int
    delta_target: float  # -1.0 to 1.0
    dte_min: int = 14
    dte_max: int = 60
    side: str = "long"  # "long" or "short"


@dataclass
class Signal:
    """Trading signal for a symbol"""
    symbol: str
    strategy: StrategyType
    direction: str  # "bullish", "bearish", "neutral", "income"
    confidence: float  # 0.0-1.0
    signal_strength: float  # 0.0-1.0 (based on technical score)
    entry_reason: str  # Human-readable explanation
    legs: List[SignalLeg] = field(default_factory=list)
    recommended_contracts: int = 1
    recommended_dte: int = 30
    max_risk: float = 0.0
    target_profit: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    iv_percentile: float = 0.0
    volatility_regime: str = "medium"
    risk_reward_ratio: float = 0.0
    probability_of_profit: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "direction": self.direction,
            "confidence": self.confidence,
            "signal_strength": self.signal_strength,
            "entry_reason": self.entry_reason,
            "legs": [
                {
                    "option_type": leg.option_type,
                    "strike": leg.strike,
                    "quantity": leg.quantity,
                    "delta_target": leg.delta_target,
                    "dte_min": leg.dte_min,
                    "dte_max": leg.dte_max,
                    "side": leg.side,
                }
                for leg in self.legs
            ],
            "recommended_contracts": self.recommended_contracts,
            "recommended_dte": self.recommended_dte,
            "max_risk": self.max_risk,
            "target_profit": self.target_profit,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "iv_percentile": self.iv_percentile,
            "volatility_regime": self.volatility_regime,
            "risk_reward_ratio": self.risk_reward_ratio,
            "probability_of_profit": self.probability_of_profit,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================
# StrategyEngine
# ============================================================

class StrategyEngine:
    """Generates trading signals and selects strategies"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def generate_signal(
        self,
        analysis: Analysis,
        current_position: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        """
        Generate trading signal based on analysis

        Args:
            analysis: Complete Analysis from AnalyticsEngine
            current_position: Current position info (for hedging decisions)

        Returns:
            Signal object or None if no trade warranted
        """
        if analysis is None:
            return None

        try:
            # Calculate signal strength
            signal_strength = self._calculate_signal_strength(analysis)

            # Select strategy based on decision tree
            strategy = self._select_strategy(analysis, signal_strength)

            if strategy is None:
                return None

            # Build signal with strategy-specific details
            signal = self._build_signal(analysis, strategy, signal_strength)

            self.logger.info(
                f"{analysis.symbol}: {signal.strategy.value} "
                f"({signal.direction}) confidence={signal.confidence:.2f}"
            )

            return signal

        except Exception as e:
            self.logger.error(f"{analysis.symbol}: Signal generation error: {e}")
            return None

    # -------- Signal Strength Calculation --------

    def _calculate_signal_strength(self, analysis: Analysis) -> float:
        """
        Calculate overall signal strength (0.0-1.0)
        Weighted combination of indicators
        """
        scores = []
        weights = []

        # Hourly RSI contribution
        if analysis.hourly_indicators.rsi_14 is not None:
            rsi = analysis.hourly_indicators.rsi_14
            if rsi > 70:
                rsi_score = 0.9
            elif rsi > 60:
                rsi_score = 0.75
            elif rsi > 50:
                rsi_score = 0.6
            elif rsi > 40:
                rsi_score = 0.4
            elif rsi > 30:
                rsi_score = 0.25
            else:
                rsi_score = 0.1
            scores.append(rsi_score)
            weights.append(0.20)

        # MACD trend contribution (hourly)
        if (analysis.hourly_indicators.macd is not None and
            analysis.hourly_indicators.macd_signal is not None):
            macd_diff = analysis.hourly_indicators.macd - analysis.hourly_indicators.macd_signal
            if macd_diff > 0:
                macd_score = 0.8
            else:
                macd_score = 0.2
            scores.append(macd_score)
            weights.append(0.25)

        # EMA alignment (daily)
        if (analysis.daily_indicators.ema_20 is not None and
            analysis.daily_indicators.ema_50 is not None and
            analysis.daily_indicators.ema_200 is not None):

            ema_20 = analysis.daily_indicators.ema_20
            ema_50 = analysis.daily_indicators.ema_50
            ema_200 = analysis.daily_indicators.ema_200

            if ema_20 > ema_50 > ema_200:
                ema_score = 0.9
            elif ema_20 < ema_50 < ema_200:
                ema_score = 0.1
            else:
                ema_score = 0.5
            scores.append(ema_score)
            weights.append(0.25)

        # Daily confirmation
        daily_strength = self._score_timeframe(analysis.daily_indicators)
        scores.append(daily_strength)
        weights.append(0.30)

        # Calculate weighted average
        if not scores:
            return 0.5

        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        total_weight = sum(weights)
        strength = weighted_sum / total_weight if total_weight > 0 else 0.5

        return min(max(strength, 0.0), 1.0)

    def _score_timeframe(self, indicators) -> float:
        """Score a single timeframe (0.0-1.0)"""
        score = 0.5
        count = 0

        if indicators.rsi_14 is not None:
            score += (indicators.rsi_14 / 100 - 0.5) * 0.5
            count += 1

        if indicators.atr_pct is not None and indicators.atr_pct > 0:
            # Normalize ATR%: 0.5% = neutral, 2% = strong
            atr_norm = min(indicators.atr_pct / 2, 1.0)
            score += atr_norm * 0.2
            count += 1

        return score / (count + 1) if count > 0 else 0.5

    # -------- Strategy Selection (Decision Tree) --------

    def _select_strategy(
        self,
        analysis: Analysis,
        signal_strength: float,
    ) -> Optional[StrategyType]:
        """
        Select strategy based on decision tree

        Decision tree:
        1. Bullish hourly + Bullish daily + IV < 40% → BULL_CALL_SPREAD
        2. Bullish hourly + Bullish daily + IV > 60% → BEAR_PUT_SPREAD
        3. Neutral hourly + Bullish daily + IV > 60% → BEAR_PUT_SPREAD (theta)
        4. Neutral hourly + Bullish daily + IV < 30% → CALENDAR_SPREAD
        5. Bearish hourly + Bullish daily → PROTECTIVE_PUT (hedge)
        6. Bullish hourly + Neutral daily → DIRECTIONAL_CALL
        7. Bearish hourly + Bearish daily → DIRECTIONAL_PUT
        """
        hourly_trend = analysis.trend_analysis.hourly_trend
        daily_trend = analysis.trend_analysis.daily_trend
        iv_percentile = analysis.volatility_regime.iv_percentile

        # Condition 1: Bullish + Bullish + Low IV
        if (hourly_trend == Trend.BULLISH and
            daily_trend == Trend.BULLISH and
            iv_percentile < 40):
            return StrategyType.BULL_CALL_SPREAD

        # Condition 2: Bullish + Bullish + High IV
        if (hourly_trend == Trend.BULLISH and
            daily_trend == Trend.BULLISH and
            iv_percentile > 60):
            return StrategyType.BEAR_PUT_SPREAD

        # Condition 3: Neutral + Bullish + High IV
        if (hourly_trend == Trend.NEUTRAL and
            daily_trend == Trend.BULLISH and
            iv_percentile > 60):
            return StrategyType.BEAR_PUT_SPREAD

        # Condition 4: Neutral + Bullish + Low IV
        if (hourly_trend == Trend.NEUTRAL and
            daily_trend == Trend.BULLISH and
            iv_percentile < 30):
            return StrategyType.CALENDAR_SPREAD

        # Condition 5: Bearish + Bullish (rare, hedge)
        if (hourly_trend == Trend.BEARISH and
            daily_trend == Trend.BULLISH):
            return StrategyType.PROTECTIVE_PUT

        # Condition 6: Bullish + Neutral
        if (hourly_trend == Trend.BULLISH and
            daily_trend == Trend.NEUTRAL):
            return StrategyType.DIRECTIONAL_CALL

        # Condition 7: Bearish + Bearish
        if (hourly_trend == Trend.BEARISH and
            daily_trend == Trend.BEARISH):
            return StrategyType.DIRECTIONAL_PUT

        return None

    # -------- Signal Building --------

    def _build_signal(
        self,
        analysis: Analysis,
        strategy: StrategyType,
        signal_strength: float,
    ) -> Signal:
        """Build complete Signal object for strategy"""

        signal = Signal(
            symbol=analysis.symbol,
            strategy=strategy,
            direction="neutral",  # Will be overridden
            confidence=0.5,  # Will be overridden
            entry_reason="",  # Will be overridden
            signal_strength=signal_strength,
            iv_percentile=analysis.volatility_regime.iv_percentile,
            volatility_regime=analysis.volatility_regime.regime,
        )

        if strategy == StrategyType.BULL_CALL_SPREAD:
            signal = self._build_bull_call_spread(signal, analysis)

        elif strategy == StrategyType.BEAR_PUT_SPREAD:
            signal = self._build_bear_put_spread(signal, analysis)

        elif strategy == StrategyType.DIRECTIONAL_CALL:
            signal = self._build_directional_call(signal, analysis)

        elif strategy == StrategyType.DIRECTIONAL_PUT:
            signal = self._build_directional_put(signal, analysis)

        elif strategy == StrategyType.CALENDAR_SPREAD:
            signal = self._build_calendar_spread(signal, analysis)

        elif strategy == StrategyType.PROTECTIVE_PUT:
            signal = self._build_protective_put(signal, analysis)

        return signal

    def _build_bull_call_spread(self, signal: Signal, analysis: Analysis) -> Signal:
        """Bull call spread: long ATM call, short OTM call"""
        signal.direction = "bullish"
        signal.confidence = analysis.trend_analysis.hourly_strength * 0.9
        signal.entry_reason = (
            f"Bullish technicals (hourly+daily) with low IV ({analysis.volatility_regime.iv_percentile:.0f}%). "
            f"Buy ATM call, sell OTM call for defined risk."
        )
        signal.recommended_dte = 30
        signal.legs = [
            SignalLeg(
                option_type="call",
                strike=analysis.current_price,  # ATM
                quantity=1,
                delta_target=0.50,
                side="long",
            ),
            SignalLeg(
                option_type="call",
                strike=analysis.current_price * 1.02,  # 2% OTM
                quantity=1,
                delta_target=0.25,
                side="short",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.02  # 2% of price
        signal.target_profit = analysis.current_price * 0.01  # 1% of price
        signal.probability_of_profit = 0.55
        signal.risk_reward_ratio = 1 / 2

        return signal

    def _build_bear_put_spread(self, signal: Signal, analysis: Analysis) -> Signal:
        """Bear put spread: sell ATM put, buy OTM put"""
        signal.direction = "income"
        signal.confidence = min(analysis.trend_analysis.daily_strength, 0.85)
        signal.entry_reason = (
            f"Bullish bias with high IV ({analysis.volatility_regime.iv_percentile:.0f}%). "
            f"Collect theta decay, limited downside risk."
        )
        signal.recommended_dte = 45
        signal.legs = [
            SignalLeg(
                option_type="put",
                strike=analysis.current_price,  # ATM
                quantity=1,
                delta_target=-0.50,
                side="short",
            ),
            SignalLeg(
                option_type="put",
                strike=analysis.current_price * 0.98,  # 2% OTM
                quantity=1,
                delta_target=-0.25,
                side="long",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.02
        signal.target_profit = analysis.current_price * 0.015
        signal.probability_of_profit = 0.65
        signal.risk_reward_ratio = 2 / 3

        return signal

    def _build_directional_call(self, signal: Signal, analysis: Analysis) -> Signal:
        """Long call: simple directional bet"""
        signal.direction = "bullish"
        signal.confidence = analysis.trend_analysis.hourly_strength
        signal.entry_reason = (
            f"Bullish hourly trend ({analysis.trend_analysis.hourly_trend.name}). "
            f"Long ATM call for directional exposure."
        )
        signal.recommended_dte = 30
        signal.legs = [
            SignalLeg(
                option_type="call",
                strike=analysis.current_price,
                quantity=1,
                delta_target=0.50,
                side="long",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.03
        signal.target_profit = analysis.current_price * 0.05
        signal.probability_of_profit = 0.45
        signal.risk_reward_ratio = 1.7

        return signal

    def _build_directional_put(self, signal: Signal, analysis: Analysis) -> Signal:
        """Long put: directional bearish bet"""
        signal.direction = "bearish"
        signal.confidence = analysis.trend_analysis.hourly_strength
        signal.entry_reason = (
            f"Bearish trend ({analysis.trend_analysis.combined_trend.name}). "
            f"Long ATM put for downside exposure."
        )
        signal.recommended_dte = 30
        signal.legs = [
            SignalLeg(
                option_type="put",
                strike=analysis.current_price,
                quantity=1,
                delta_target=-0.50,
                side="long",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.03
        signal.target_profit = analysis.current_price * 0.05
        signal.probability_of_profit = 0.45
        signal.risk_reward_ratio = 1.7

        return signal

    def _build_calendar_spread(self, signal: Signal, analysis: Analysis) -> Signal:
        """Calendar spread: sell near-term, buy longer-dated"""
        signal.direction = "neutral"
        signal.confidence = 0.7
        signal.entry_reason = (
            f"Neutral trend with low IV. Sell near-term call, buy longer call. "
            f"Theta farming strategy for volatility expansion."
        )
        signal.recommended_dte = 21  # Sell short-term
        signal.legs = [
            SignalLeg(
                option_type="call",
                strike=analysis.current_price,
                quantity=1,
                delta_target=0.40,
                dte_min=14,
                dte_max=21,
                side="short",
            ),
            SignalLeg(
                option_type="call",
                strike=analysis.current_price,
                quantity=1,
                delta_target=0.40,
                dte_min=45,
                dte_max=60,
                side="long",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.01
        signal.target_profit = analysis.current_price * 0.008
        signal.probability_of_profit = 0.60
        signal.risk_reward_ratio = 0.8

        return signal

    def _build_protective_put(self, signal: Signal, analysis: Analysis) -> Signal:
        """Protective put: hedge existing long position"""
        signal.direction = "hedge"
        signal.confidence = 0.9
        signal.entry_reason = (
            "Short-term bearish signal suggests hedging long position. "
            "Buy slightly OTM put for downside protection."
        )
        signal.recommended_dte = 45
        signal.legs = [
            SignalLeg(
                option_type="put",
                strike=analysis.current_price * 0.98,  # Slightly OTM
                quantity=1,
                delta_target=-0.40,
                side="long",
            ),
        ]
        signal.max_risk = analysis.current_price * 0.02
        signal.target_profit = 0  # Insurance, not profit-seeking
        signal.probability_of_profit = 0.5

        return signal


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from analytics_engine import (
        AnalyticsEngine, TechnicalIndicators, Trend, TrendAnalysis, VolatilityRegime, Analysis
    )

    # Create StrategyEngine
    engine = StrategyEngine()

    # Create mock bullish Analysis for testing
    bullish_analysis = Analysis(
        symbol="AAPL",
        timestamp=datetime.now(timezone.utc),
        current_price=150.0,
        hourly_indicators=TechnicalIndicators(
            rsi_14=75.0,
            macd=5.0,
            macd_signal=3.0,
            ema_20=150.0,
            ema_50=145.0,
            ema_200=140.0,
            atr_14=2.5,
        ),
        daily_indicators=TechnicalIndicators(
            rsi_14=65.0,
            macd=10.0,
            macd_signal=8.0,
            ema_20=148.0,
            ema_50=144.0,
            ema_200=138.0,
            atr_14=3.0,
        ),
        trend_analysis=TrendAnalysis(
            hourly_trend=Trend.BULLISH,
            hourly_strength=0.85,
            daily_trend=Trend.BULLISH,
            daily_strength=0.90,
            combined_trend=Trend.BULLISH,
            combined_strength=0.88,
            primary_direction="bullish",
        ),
        volatility_regime=VolatilityRegime(
            iv=0.18,
            iv_percentile=30.0,  # Low IV
            hv=0.15,
            regime="low",
            vix_level=18.0,
            iv_crush_risk=0.2,
            regime_change_likely=False,
        ),
    )

    # Generate signal
    signal = engine.generate_signal(bullish_analysis)

    if signal:
        print("\n=== Signal Result ===")
        import json
        print(json.dumps(signal.to_dict(), indent=2, default=str))
    else:
        print("No signal generated (analysis may have no actionable trend)")
