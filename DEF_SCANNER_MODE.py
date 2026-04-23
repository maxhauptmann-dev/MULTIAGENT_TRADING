# DEF_SCANNER_MODE.py

import os
import concurrent.futures
from typing import List, Dict, Any, Optional
from functools import partial

from DEF_DATA_AGENT import DataAgent
from trading_agents_with_gpt import (
    ExecutionAgent,
    _map_timeframe_to_ibkr,
)
from DEF_GPT_AGENTS import run_calls_parallel, safe_call_gpt_agent, GPT_CONCURRENCY
from DEF_NEWS_CLIENT import NewsClient
from DEF_OPTIONS_AGENT import OptionsAgent
from universe_manager import load_universe, combine_universes, manager as universe_manager

from risk import compute_position_size, compute_kelly_size, CircuitBreaker
from DEF_INDICATORS import compute_indicators, compute_market_regime
import position_monitor as _pm_module

# Eigene Instanzen NUR für den Scanner
_data_agent = DataAgent()
_execution_agent = ExecutionAgent()
_news_client = NewsClient()
_options_agent = OptionsAgent()

# CircuitBreaker für den Scanner
_scanner_cb = CircuitBreaker(n_errors=8, n_losses=3, cooldown_seconds=1800)

# Position-Monitor initialisieren falls noch nicht geschehen
if _pm_module.monitor is None:
    _pm_module.monitor = _pm_module.PositionMonitor(
        execution_agent=_execution_agent,
        circuit_breaker=_scanner_cb,
    )

# Anzahl paralleler Symbol-Threads (default 4, via .env konfigurierbar)
_SCANNER_MAX_WORKERS       = int(os.getenv("SCANNER_MAX_WORKERS", "4"))
_MAX_POSITIONS_PER_SECTOR  = int(os.getenv("MAX_POSITIONS_PER_SECTOR", "2"))


def _process_symbol(
    symbol: str,
    account_info: Dict[str, Any],
    timeframe: str,
    asset_type: str,
    market_hint: str,
    auto_execute: bool,
    market_regime: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Verarbeitet ein einzelnes Symbol vollständig. Thread-safe."""
    if market_regime is None:
        market_regime = {}
    try:
        market_data = _data_agent.fetch(
            symbol=symbol,
            timeframe=timeframe,
            asset_type=asset_type,
            market_hint=market_hint,
        )

        candles = market_data.get("candles") or []

        # Indikatoren berechnen und einbetten
        indicators = compute_indicators(candles)
        market_data["indicators"] = indicators

        # market_meta aufbauen
        market_meta = dict(market_data.get("meta") or {})
        market_meta["atr_14"]  = indicators.get("atr_14")
        market_meta["atr_pct"] = indicators.get("atr_pct")
        if candles:
            last = candles[-1]
            try:
                market_meta["last_close"] = float(last["close"])
                market_meta["last_open"]  = float(last["open"])
                market_meta["last_high"]  = float(last["high"])
                market_meta["last_low"]   = float(last["low"])
            except Exception:
                market_meta["last_close"] = None
        else:
            market_meta["last_close"] = market_meta.get("last_close")

        # News holen
        combined_news = _news_client.get_combined_news(
            symbol=symbol,
            days_back=3,
            limit_per_source=10,
        )
        recent_news = [
            {
                "headline": item.get("headline"),
                "source":   item.get("source"),
                "published_at": item.get("published_at"),
                "summary":  item.get("summary"),
                "url":      item.get("url"),
                "provider": item.get("provider"),
            }
            for item in combined_news
            if item.get("headline")
        ]

        # News-Agent
        news_output = safe_call_gpt_agent("news_agent", {"symbol": symbol, "recent_news": recent_news})

        # Analyse-Agents parallel
        agent_tasks = [
            partial(safe_call_gpt_agent, "regime_agent",        {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "trend_dow_agent",     {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "sr_formations_agent", {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "momentum_agent",      {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "volume_oi_agent",     {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "candlestick_agent",   {"symbol": symbol, "market_data": market_data}),
            partial(safe_call_gpt_agent, "intermarket_agent",   {"symbol": symbol, "market_data": market_data}),
        ]
        agent_results = run_calls_parallel(agent_tasks, max_workers=min(GPT_CONCURRENCY, 3), per_call_timeout=20.0)

        regime_output      = agent_results[0] or {"error": "no_result"}
        trend_output       = agent_results[1] or {"error": "no_result"}
        sr_output          = agent_results[2] or {"error": "no_result"}
        momentum_output    = agent_results[3] or {"error": "no_result"}
        volume_output      = agent_results[4] or {"error": "no_result"}
        candle_output      = agent_results[5] or {"error": "no_result"}
        intermarket_output = agent_results[6] or {"error": "no_result"}

        # Synthese
        synth_input = {
            "symbol":              symbol,
            "regime_output":       regime_output,
            "trend_output":        trend_output,
            "sr_output":           sr_output,
            "momentum_output":     momentum_output,
            "volume_output":       volume_output,
            "candlestick_output":  candle_output,
            "intermarket_output":  intermarket_output,
            "news_output":         news_output,
        }
        synthese_output = safe_call_gpt_agent("synthese_agent", synth_input)

        # Signal — ML zuerst, GPT als Fallback
        from DEF_ML_SIGNAL import _engine as _ml_engine
        if _ml_engine.is_loaded and candles:
            signal_output = _ml_engine.predict(candles, symbol=symbol)
        else:
            signal_output = safe_call_gpt_agent(
                "signal_scanner_agent",
                {"symbol": symbol, "synthese_output": synthese_output},
            )

        # Handels-Plan – mit Market-Regime Gate
        handels_input = {
            "symbol":          symbol,
            "synthese_output": synthese_output,
            "signal_output":   signal_output,
            "account_info":    account_info,
            "market_meta":     market_meta,
            "market_regime":   market_regime.get("regime", "neutral"),
            "market_regime_info": market_regime,
        }

        # Sentiment-Gating: News-Sentiment vs Market-Regime
        news_sentiment = news_output.get("overall_sentiment", 0) if isinstance(news_output, dict) else 0
        regime_str = market_regime.get("regime", "neutral")
        size_reduction_factor = 1.0

        if regime_str == "bull" and news_sentiment < -0.6:
            size_reduction_factor = 0.5
            handels_input["sentiment_gate_warning"] = "negative_sentiment_in_bull_market"
        elif regime_str == "bear" and news_sentiment < -0.3:
            size_reduction_factor = 1.2
            handels_input["sentiment_gate_bonus"] = "negative_sentiment_aligned_with_bear"

        trade_plan = safe_call_gpt_agent("handels_agent", handels_input)

        # CircuitBreaker
        if not _scanner_cb.allow():
            trade_plan = {"action": "no_trade", "reason": "circuit_breaker_open"}

        # Positionsgröße — Kelly wenn ML-Signal, sonst festes Risiko
        if isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
            acct_size  = float(account_info.get("account_size", 0))
            max_risk   = float(account_info.get("max_risk_per_trade", 0.01))
            last_close = market_meta.get("last_close")
            sl = None
            try:
                sl = float(trade_plan.get("stop_loss", {}).get("price"))
            except Exception:
                pass

            buy_prob = float(signal_output.get("buy_probability", 0)) if isinstance(signal_output, dict) else 0
            rr_ratio = None
            try:
                rr_ratio = float(trade_plan.get("take_profit", {}).get("reward_risk_ratio"))
            except Exception:
                pass

            # For short positions, use sell_probability = 1 - buy_probability
            direction = trade_plan.get("direction", "long")
            if direction == "short" and buy_prob > 0:
                sell_prob = 1.0 - buy_prob
                sizing = compute_kelly_size(acct_size, sell_prob, rr_ratio, max_risk, last_close, sl) if rr_ratio and rr_ratio > 0 else compute_position_size(acct_size, max_risk, last_close, sl)
            elif buy_prob > 0 and rr_ratio and rr_ratio > 0:
                sizing = compute_kelly_size(acct_size, buy_prob, rr_ratio, max_risk, last_close, sl)
            else:
                sizing = compute_position_size(acct_size, max_risk, last_close, sl)

            # Apply sentiment gate size reduction/increase
            if size_reduction_factor != 1.0:
                sizing["qty"] = max(1, int(sizing.get("qty", 0) * size_reduction_factor))

            if sizing.get("qty", 0) == 0:
                trade_plan["action"] = "no_trade"
                trade_plan.setdefault("warnings", []).append("position_size_zero_or_invalid")
            else:
                trade_plan.setdefault("position_sizing", {}).update({
                    "max_risk_amount":     sizing["max_risk_amount"],
                    "risk_per_share":      sizing["risk_per_share"],
                    "contracts_or_shares": sizing["qty"],
                })
                if "kelly_fraction" in sizing:
                    trade_plan["position_sizing"]["kelly_fraction"] = sizing["kelly_fraction"]

            # ATR für Trailing Stop in Position-Monitor speichern
            trade_plan["_atr_14"] = market_meta.get("atr_14")

            # Korrelations-Warning
            if _pm_module.monitor:
                from DEF_ML_SIGNAL import _get_sector_etf
                sector = _get_sector_etf(symbol)
                open_pos = _pm_module.monitor.get_open_positions()
                sector_count = sum(
                    1 for p in open_pos
                    if _get_sector_etf(p.get("symbol", "")) == sector
                )
                if sector_count >= _MAX_POSITIONS_PER_SECTOR:
                    trade_plan.setdefault("warnings", []).append(
                        f"sector_concentration: {sector_count} offene {sector}-Positionen"
                    )

        # Options-Plan
        options_plan = None
        try:
            options_plan = _options_agent.build_options_plan(
                symbol=symbol,
                trade_plan=trade_plan,
                synthese_output=synthese_output,
                signal_output=signal_output,
                news_output=news_output,
                account_info=account_info,
                market_meta=market_data.get("meta", {}),
            )
        except Exception as e:
            print(f"[OptionsAgent] Fehler bei {symbol} (Scanner): {e}")

        if options_plan is not None and isinstance(trade_plan, dict):
            trade_plan["options_plan"] = options_plan

        # Execution – skip if position already open
        execution_result = None
        if auto_execute and isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
            # Check if position already open to avoid duplicate buys
            if _pm_module.monitor:
                open_pos = _pm_module.monitor.get_open_positions()
                if any(p.get("symbol") == symbol for p in open_pos):
                    trade_plan["action"] = "no_trade"
                    trade_plan["reason"] = "position_already_open"

        if auto_execute and isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
            broker_pref = account_info.get("broker_preference")
            execution_result = _execution_agent.execute_trade_plan(trade_plan, broker_pref)
            if execution_result and execution_result.get("status") == "error":
                _scanner_cb.record_loss()
            elif _pm_module.monitor:
                _pm_module.monitor.open_position(trade_plan, execution_result)

        return {
            "symbol":          symbol,
            "news_output":     news_output,
            "regime_output":   regime_output,
            "synthese_output": synthese_output,
            "signal_output":   signal_output,
            "trade_plan":      trade_plan,
            "execution_result": execution_result,
        }

    except Exception as e:
        print(f"[Scanner] Fehler bei {symbol}: {e}")
        _scanner_cb.record_error()
        return None


def run_scanner_mode(
    watchlist: List[str],
    account_info: Dict[str, Any],
    timeframe: str = "1D",
    asset_type: str = "stock",
    market_hint: str = "US",
    auto_execute: bool = False,
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Modus B – Scanner (parallel):
    Verarbeitet Symbole gleichzeitig in max_workers Threads.
    Fetches market regime once at start and applies to all symbols.
    """
    workers = max_workers or _SCANNER_MAX_WORKERS
    workers = max(1, min(workers, len(watchlist)))

    # Fetch market regime once (SPY/QQQ trend)
    market_regime = compute_market_regime()
    regime = market_regime.get("regime", "neutral")
    spy_vs = market_regime.get("spy_vs_ema20", 0.0)
    vix = market_regime.get("vix", 20.0)
    print(f"[Scanner] Market Regime: {regime.upper()} | SPY vs EMA20: {spy_vs:+.2f}% | VIX: {vix:.2f}")

    print(f"[Scanner] Starte: {len(watchlist)} Symbole, {workers} parallele Threads")

    setups: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_symbol,
                symbol, account_info, timeframe, asset_type, market_hint, auto_execute, market_regime,
            ): symbol
            for symbol in watchlist
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                setups.append(result)

    return {"setups": setups}


if __name__ == "__main__":
    print("Teste Universen...")
    print("SP500:", load_universe("sp500"))
    print("Semis:", load_universe("semis"))
    print("Kombiniert:", combine_universes(["sp500", "semis"]))
