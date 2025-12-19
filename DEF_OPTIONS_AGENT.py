# DEF_OPTIONS_AGENT.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


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
        today = datetime.utcnow().date()
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
        bias = synth.get("overall_bias")
        bias_conf = synth.get("overall_confidence")
        sig = signal.get("short_term_signal")
        style = signal.get("entry_style")
        sent = news.get("overall_sentiment")

        return (
            f"{option_type.upper()}-Setup basierend auf "
            f"Bias={bias} (Conf={bias_conf}), "
            f"Signal={sig} / Entry-Stil={style}, "
            f"News-Sentiment={sent}."
        )
