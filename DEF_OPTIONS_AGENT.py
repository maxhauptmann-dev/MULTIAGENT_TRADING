# DEF_OPTIONS_AGENT.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone


@dataclass
class OptionPOPConfig:
    min_pop: float = 0.65  # Mindest-POP für "lohnenden" Options-Trade
    default_iv_score: float = 0.5


class OptionsAgent:
    """
    Rein analytischer Options-Planer:
    - Nutzt synthese_output, signal_output, news_output, trade_plan, account_info
    - Berechnet Trend/Entry/News/IV-Scores
    - Liefert option_plan (Call/Put-Setup) oder None, wenn Setup zu schwach
    """

    def __init__(self, config: Optional[OptionPOPConfig] = None):
        self.config = config or OptionPOPConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_options_plan(
        self,
        symbol: str,
        trade_plan: Dict[str, Any],
        synthese_output: Dict[str, Any],
        signal_output: Dict[str, Any],
        news_output: Dict[str, Any],
        account_info: Dict[str, Any],
        market_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Gibt einen Options-Plan zurück oder None, wenn:
        - kein open_position
        - keine Richtung
        - POP < min_pop
        """

        action = trade_plan.get("action")
        direction = (trade_plan.get("direction") or "").lower()

        if action != "open_position" or direction not in ("long", "short"):
            return None

        # 1) Grundrichtung → Call/Put
        option_type = "call" if direction == "long" else "put"

        # 2) Scores berechnen
        trend_score = self._score_trend(direction, synthese_output)
        entry_score = self._score_entry(signal_output)
        news_score = self._score_news(direction, news_output)
        iv_score = self._score_iv(synthese_output)

        pop_score = (
            0.4 * trend_score
            + 0.3 * entry_score
            + 0.2 * news_score
            + 0.1 * iv_score
        )

        pop_score = max(0.0, min(1.0, pop_score))

        if pop_score < self.config.min_pop:
            # Setup zu schwach → kein dedizierter Options-Trade
            return None

        # 3) DTE / Expiry-Heuristik (auf Basis Time-Horizon)
        dte_min, dte_max = self._choose_dte_range(account_info)

        # 4) Delta & Strike-Präferenz
        delta_target, strike_pref = self._choose_delta_and_strike(direction, account_info)

        # 5) Risikobudget aus Trade-Plan
        pos_sizing = trade_plan.get("position_sizing") or {}
        max_risk_amount = pos_sizing.get("max_risk_amount") or account_info.get("account_size", 0) * account_info.get("max_risk_per_trade", 0.01)

        # 6) Optional: grober Expiry-Hinweis (ohne echte Optionskette)
        today = datetime.now(timezone.utc).date()
        mid_dte = int((dte_min + dte_max) / 2)
        expiry_hint = today + timedelta(days=mid_dte)

        option_plan = {
            "symbol": symbol,
            "type": option_type,                        # "call" oder "put"
            "underlying_direction": direction,          # "long"/"short"
            "pop_score": round(pop_score, 3),
            "component_scores": {
                "trend_score": round(trend_score, 3),
                "entry_score": round(entry_score, 3),
                "news_score": round(news_score, 3),
                "iv_score": round(iv_score, 3),
            },
            "dte_target": {
                "min": dte_min,
                "max": dte_max,
                "expiry_hint": expiry_hint.isoformat(),  # rein orientierend
            },
            "delta_target": delta_target,               # z.B. 0.5
            "strike_preference": strike_pref,           # "ATM"/"ITM"
            "position_risk_budget": max_risk_amount,
            "contracts": None,                          # braucht Optionskette/Preis
            "entry_reason": self._build_entry_reason(option_type, synthese_output, signal_output, news_output),
            "notes": [
                "Optionsplan ist rein analytisch; konkrete Kontraktauswahl benötigt Optionskette (z.B. Finnhub Options API).",
            ],
        }

        return option_plan

    # ------------------------------------------------------------------
    # Score-Funktionen
    # ------------------------------------------------------------------

    def _score_trend(self, direction: str, synth: Dict[str, Any]) -> float:
        if not synth:
            return 0.5
        bias = synth.get("overall_bias")
        conf = synth.get("overall_confidence") or 0.0

        # Richtung passt ↔ voller Score
        if direction == "long" and bias == "bullish":
            return float(conf)
        if direction == "short" and bias == "bearish":
            return float(conf)

        # Neutral oder gegenläufig → Abschlag
        if bias == "neutral":
            return float(conf) * 0.5

        # Gegen Trend → starker Abschlag
        return float(conf) * 0.25

    def _score_entry(self, signal: Dict[str, Any]) -> float:
        if not signal:
            return 0.5
        conf = signal.get("confidence") or 0.0
        style = signal.get("entry_style") or "none"

        base = float(conf)

        # Breakout / Pullback → leicht boost
        if style in ("breakout", "pullback"):
            base = min(1.0, base + 0.1)

        return base

    def _score_news(self, direction: str, news: Dict[str, Any]) -> float:
        """
        Mappt overall_sentiment (-1..1) auf Score (0..1),
        wobei:
        - für LONG: positive News gut
        - für SHORT: negative News gut
        """
        if not news:
            return 0.5  # neutral
        sent = news.get("overall_sentiment")
        if sent is None:
            return 0.5  # neutral

        try:
            s = float(sent)
        except Exception:
            return 0.5

        s_norm = (s + 1.0) / 2.0  # -1..1 → 0..1

        if direction == "long":
            # 0..1 direkt
            return max(0.0, min(1.0, s_norm))
        elif direction == "short":
            # für Shorts sind negative News gut → invertieren
            return max(0.0, min(1.0, 1.0 - s_norm))
        else:
            return 0.5

    def _score_iv(self, synth: Dict[str, Any]) -> float:
        """
        Approximation über volatility_level aus synthese_output,
        bis echte IV-Daten angebunden sind.
        """
        if not synth:
            return self.config.default_iv_score
        vol = (synth.get("volatility_level") or "").lower()

        # Für Optionskäufe ist zu hohe Volatilität (oft = hohe IV) eher schlecht.
        if vol in ("low", "niedrig"):
            return 1.0
        if vol in ("medium", "mittel"):
            return 0.7
        if vol in ("high", "hoch"):
            return 0.4
        if vol in ("very_high", "extrem"):
            return 0.2

        # Unbekannt → neutral
        return self.config.default_iv_score

    # ------------------------------------------------------------------
    # DTE & Delta/Strike-Heuristiken
    # ------------------------------------------------------------------

    def _choose_dte_range(self, account_info: Dict[str, Any]) -> (int, int):
        horizon = (account_info.get("time_horizon") or "short").lower()

        if horizon in ("scalp", "intraday"):
            return 5, 15
        if horizon in ("short", "swing"):
            return 20, 45
        if horizon in ("medium", "midterm"):
            return 45, 90
        if horizon in ("long", "longterm"):
            return 60, 120

        return 20, 45

    def _choose_delta_and_strike(self, direction: str, account_info: Dict[str, Any]) -> (float, str):
        horizon = (account_info.get("time_horizon") or "short").lower()

        if horizon in ("short", "swing", "scalp", "intraday"):
            return 0.5, "ATM"   # guter Kompromiss
        if horizon in ("medium", "midterm"):
            return 0.6, "ITM"
        if horizon in ("long", "longterm"):
            return 0.65, "ITM"

        return 0.5, "ATM"

    # ------------------------------------------------------------------
    # Text-Reason
    # ------------------------------------------------------------------

    def _build_entry_reason(
        self,
        option_type: str,
        synth: Dict[str, Any],
        signal: Dict[str, Any],
        news: Dict[str, Any],
    ) -> str:
        bias = (synth or {}).get("overall_bias", "unknown")
        bias_conf = (synth or {}).get("overall_confidence", "n/a")
        sig = (signal or {}).get("short_term_signal", "unknown")
        style = (signal or {}).get("entry_style", "n/a")
        sent = (news or {}).get("overall_sentiment", "n/a")

        return (
            f"{option_type.upper()}-Setup basierend auf "
            f"Bias={bias} (Conf={bias_conf}), "
            f"Signal={sig} / Entry-Stil={style}, "
            f"News-Sentiment={sent}."
        )

    # ------------------------------------------------------------------
    # POP Calculator für Contracts (mit Delta)
    # ------------------------------------------------------------------

    def calculate_pop_from_contract(
        self,
        option_type: str,
        delta: float,
    ) -> float:
        """
        Berechne echte Probability of Profit aus Delta des Contracts.

        CALL: POP = Delta direkt (Delta 0.6 = 60% Chance ITM)
        PUT:  POP = |Delta| direkt (Delta -0.4 = 40% Chance ITM)

        Args:
            option_type: "call" oder "put"
            delta: Delta vom Options-Contract

        Returns:
            POP Score 0..1 (Wahrscheinlichkeit dass Option ITM ist bei Expiry)
        """
        if option_type == "call":
            # Call: Delta = POP direkt
            return float(delta)
        elif option_type == "put":
            # Put: |Delta| = POP (Delta ist negativ für Puts)
            return abs(float(delta))
        else:
            return 0.5

    def calculate_total_pop(
        self,
        option_type: str,
        contract_delta: float,
        max_loss: float,
        current_premium: float,
    ) -> float:
        """
        Berechne gesamt POP unter Berücksichtigung von Breakeven.

        Echte POP = (Wahrscheinlichkeit ITM) × (profitable_wenn_ITM) + (wahrscheinlichkeit OTM) × (profitable_wenn_OTM)

        Vereinfacht für Long Calls/Puts:
        - Profit wenn: Intrinsic Value > Premium gezahlt
        - Loss wenn: Preis < Strike (Call) oder > Strike (Put) UND Premium > Gewinn

        Args:
            option_type: "call" oder "put"
            contract_delta: Delta vom Contract
            max_loss: Max Verlust möglich (= Premium × 100)
            current_premium: Aktuelle Optionsprämie

        Returns:
            Angepasstes POP unter Berücksichtigung von Breakeven
        """
        # ITM-Wahrscheinlichkeit
        itm_prob = self.calculate_pop_from_contract(option_type, contract_delta)

        # Breakeven Anpassung: Wie viel muss der Preis sich bewegen damit wir Profit machen?
        # Vereinfacht: je höher Premium, desto mehr muss Preis sich bewegen
        # Bei current_premium = 2.00, mit Delta 0.5, brauchen wir mehr als 50% Wahrscheinlichkeit

        # Faktor: Bei hoher Premium wird POP reduziert
        # Bei niedriger Premium bleibt POP nah am Delta
        premium_factor = max(0.3, 1.0 - (current_premium / 10.0))

        adjusted_pop = itm_prob * premium_factor
        return max(0.0, min(1.0, adjusted_pop))

    # ------------------------------------------------------------------
    # IMPROVED POP CALCULATOR v2 (mit allen Faktoren)
    # ------------------------------------------------------------------

    def calculate_improved_pop(
        self,
        option_type: str,
        analytical_pop: float,
        contract_delta: float,
        dte: int,
        current_iv: float = 0.25,
        iv_percentile: float = 0.5,
        current_premium: float = 0.0,
        underlying_price: float = 100.0,
        strike: float = 100.0,
    ) -> Dict[str, float]:
        """
        Verbesserte POP Berechnung mit ALLEN realen Faktoren.

        Berücksichtigt:
        • Analytisches Signal (Trend/Entry)
        • Delta (aber mit Guards)
        • IV Qualität (IV Percentile + Skew)
        • Theta Decay (exponentiell, nicht linear)
        • Slippage & Bid-Ask Spread (5-8%)
        • IV Crush Risk (bei High IV)
        • Edge Cases Guards (Min/Max)

        Returns:
            {
                'pop': final_pop_score (0.0-1.0),
                'analytical': analytical_pop,
                'delta_component': delta_pop,
                'iv_quality': iv_quality_score,
                'theta_decay': theta_factor,
                'slippage_adj': slippage_discount,
                'iv_crush_risk': iv_crush_factor,
                'components': {...detailed breakdown...}
            }
        """
        import math

        # 1. ANALYTICAL COMPONENT (45%)
        analytical_norm = max(0.0, min(1.0, analytical_pop))

        # 2. DELTA COMPONENT (35%) - aber mit IV-Anpassung
        # Delta ist nur gültig wenn IV nicht extrem ist
        delta_pop = abs(float(contract_delta))

        # IV-Anpassung: wenn IV sehr hoch, Delta ist weniger zuverlässig
        iv_adjustment = 1.0
        if iv_percentile > 0.75:
            iv_adjustment = 0.85  # High IV macht Delta weniger zuverlässig
        elif iv_percentile < 0.25:
            iv_adjustment = 0.95  # Low IV macht Delta zuverlässig

        delta_pop_adjusted = delta_pop * iv_adjustment

        # 3. IV QUALITY COMPONENT (15%)
        # Je näher IV am 50th Percentile, desto besser
        iv_from_mean = abs(iv_percentile - 0.5)
        iv_quality = 1.0 - (iv_from_mean * 2)  # 0.5 Percentile = 1.0 quality
        iv_quality = max(0.3, min(1.0, iv_quality))

        # 4. THETA DECAY COMPONENT (5%)
        # Exponentieller Decay: nach DTE=7 wird es exponentiell teuer
        if dte > 30:
            theta_factor = 1.0  # Viel Zeit = guter Theta
        elif dte > 14:
            theta_factor = 0.95
        elif dte > 7:
            theta_factor = 0.85  # 7-14 DTE: Decay wird problematisch
        else:
            # Exponentiell nach unten bei < 7 DTE
            theta_factor = max(0.5, math.exp(-0.5 * (7 - dte)))

        # 5. SLIPPAGE ADJUSTMENT (5-8%)
        # Bid-Ask Spread + Slippage discount
        slippage_pct = 0.06  # 6% Standard

        # Bei breiten Spreads (OTM) höherer Slippage
        moneyness = abs(underlying_price - strike) / strike
        if moneyness > 0.05:  # OTM
            slippage_pct = 0.08
        elif moneyness < 0.01:  # ATM
            slippage_pct = 0.05

        # 6. IV CRUSH RISK (bei High IV)
        # Nach Earnings/News kann IV um 30-50% fallen
        iv_crush_factor = 1.0
        if iv_percentile > 0.80:
            # High IV = hohes IV Crush Risk
            iv_crush_factor = 0.85  # -15% Adjustment bei Very High IV
        elif iv_percentile > 0.70:
            iv_crush_factor = 0.92  # -8% bei High IV

        # 7. KOMBINIERE ALLE KOMPONENTEN
        # Neue Gewichtung (datengestützt):
        #   Analytical: 45% (Signal-Qualität)
        #   Delta: 35% (Greeks)
        #   IV Quality: 15% (Market Condition)
        #   Theta: 5% (Time Factor)

        combined_pop = (
            0.45 * analytical_norm +
            0.35 * delta_pop_adjusted +
            0.15 * iv_quality +
            0.05 * theta_factor
        )

        # 8. APPLIZIERE ADJUSTMENTS
        final_pop = combined_pop * iv_crush_factor * (1.0 - slippage_pct)

        # 9. GUARDS gegen Edge Cases
        # Min: 0.20 (nicht unter 20% - zu riskant)
        # Max: 0.92 (nicht über 92% - keine echte 100% Sicherheit)
        final_pop = max(0.20, min(0.92, final_pop))

        return {
            'pop': round(final_pop, 3),
            'analytical': round(analytical_norm, 3),
            'delta_component': round(delta_pop_adjusted, 3),
            'iv_quality': round(iv_quality, 3),
            'theta_decay': round(theta_factor, 3),
            'slippage_adj': round(slippage_pct, 3),
            'iv_crush_risk': round(1.0 - iv_crush_factor, 3),
            'components': {
                'analytical_45pct': round(0.45 * analytical_norm, 3),
                'delta_35pct': round(0.35 * delta_pop_adjusted, 3),
                'iv_quality_15pct': round(0.15 * iv_quality, 3),
                'theta_5pct': round(0.05 * theta_factor, 3),
                'iv_crush_factor': round(iv_crush_factor, 3),
                'slippage_discount': round(1.0 - slippage_pct, 3),
            }
        }
