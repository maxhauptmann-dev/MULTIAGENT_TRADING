# DEF_SCANNER_MODE.py

from typing import List, Dict, Any
from functools import partial

# ...existing code...
from DEF_DATA_AGENT import DataAgent
from trading_agents_with_gpt import (
    ExecutionAgent,
    _map_timeframe_to_ibkr,
)
from DEF_GPT_AGENTS import call_gpt_agent, run_calls_parallel, safe_call_gpt_agent, GPT_CONCURRENCY
from DEF_NEWS_CLIENT import NewsClient
from DEF_OPTIONS_AGENT import OptionsAgent
from universe_manager import load_universe, combine_universes, manager as universe_manager
# ...existing code...

# >>> NEU: Risk-Utilities importieren
from risk import compute_position_size, CircuitBreaker

# Eigene Instanzen NUR für den Scanner
_data_agent = DataAgent()
_execution_agent = ExecutionAgent()
_news_client = NewsClient()
_options_agent = OptionsAgent()

# >>> NEU: CircuitBreaker für den Scanner
_scanner_cb = CircuitBreaker(n_errors=8, n_losses=3, cooldown_seconds=1800)

def run_scanner_mode(
    watchlist: List[str],
    account_info: Dict[str, Any],
    timeframe: str = "1D",
    asset_type: str = "stock",
    market_hint: str = "US",
    auto_execute: bool = False,
) -> Dict[str, Any]:
    """
    Modus B – Scanner:
    - iteriert über Watchlist
    - pro Symbol: DataAgent → Analyse → Synthese → Signal
    - nur bei Signal != "none": Handels-Agent → Trade-Plan (+ optional Execution)
    """
    setups: List[Dict[str, Any]] = []
    bar_size, days = _map_timeframe_to_ibkr(timeframe)

    for symbol in watchlist:
        try:
            market_data = _data_agent.fetch(
                symbol=symbol,
                timeframe=timeframe,
                asset_type=asset_type,
                market_hint=market_hint,
            )

            # News holen (kleineres Fenster)
            combined_news = _news_client.get_combined_news(
                symbol=symbol,
                days_back=3,
                limit_per_source=10,
            )

            recent_news = [
                {
                    "headline": item.get("headline"),
                    "source": item.get("source"),
                    "published_at": item.get("published_at"),
                    "summary": item.get("summary"),
                    "url": item.get("url"),
                    "provider": item.get("provider"),
                }
                for item in combined_news
                if item.get("headline")
            ]

            # News-Analyse (safe)
            news_input = {"symbol": symbol, "recent_news": recent_news}
            news_output = safe_call_gpt_agent("news_agent", news_input)

            # Parallel: mehrere Analyse-Agents
            agent_tasks = [
                partial(safe_call_gpt_agent, "regime_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "trend_dow_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "sr_formations_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "momentum_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "volume_oi_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "candlestick_agent", {"symbol": symbol, "market_data": market_data}),
                partial(safe_call_gpt_agent, "intermarket_agent", {"symbol": symbol, "market_data": market_data}),
            ]

            agent_results = run_calls_parallel(
                agent_tasks,
                max_workers=min(GPT_CONCURRENCY, len(agent_tasks), 3),
                per_call_timeout=20.0,
            )

            regime_output = agent_results[0] or {"error": "no_result"}
            trend_output = agent_results[1] or {"error": "no_result"}
            sr_output = agent_results[2] or {"error": "no_result"}
            momentum_output = agent_results[3] or {"error": "no_result"}
            volume_output = agent_results[4] or {"error": "no_result"}
            candle_output = agent_results[5] or {"error": "no_result"}
            intermarket_output = agent_results[6] or {"error": "no_result"}

            # Synthese (safe)
            synth_input = {
                "symbol": symbol,
                "regime_output": regime_output,
                "trend_output": trend_output,
                "sr_output": sr_output,
                "momentum_output": momentum_output,
                "volume_output": volume_output,
                "candlestick_output": candle_output,
                "intermarket_output": intermarket_output,
                "news_output": news_output,
            }
            synthese_output = safe_call_gpt_agent("synthese_agent", synth_input)

            # Signal (safe)
            signal_output = safe_call_gpt_agent(
                "signal_scanner_agent",
                {"symbol": symbol, "synthese_output": synthese_output},
            )

            # Handels-Plan (safe)
            handels_input = {
                "symbol": symbol,
                "synthese_output": synthese_output,
                "signal_output": signal_output,
                "account_info": account_info,
            }
            trade_plan = safe_call_gpt_agent("handels_agent", handels_input)

            # >>> NEU: CircuitBreaker erzwingen
            if not _scanner_cb.allow():
                trade_plan = {"action": "no_trade", "reason": "circuit_breaker_open"}

            # >>> NEU: Positionsgröße berechnen und validieren
            if isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
                acct_size = float(account_info.get("account_size", 0))
                max_risk = float(account_info.get("max_risk_per_trade", 0.01))

                # last_close aus candles oder meta
                last_close = None
                try:
                    candles = market_data.get("candles") or market_data.get("data") or []
                    if candles:
                        last_close = float(candles[-1].get("close"))
                    else:
                        last_close = float(market_data.get("meta", {}).get("last_close"))
                except Exception:
                    last_close = None

                # Stop-Loss aus Trade-Plan
                sl = None
                try:
                    sl = float(trade_plan.get("stop_loss", {}).get("price"))
                except Exception:
                    sl = None

                sizing = compute_position_size(acct_size, max_risk, last_close, sl)
                if sizing.get("qty", 0) == 0:
                    trade_plan["action"] = "no_trade"
                    trade_plan.setdefault("warnings", []).append("position_size_zero_or_invalid")
                else:
                    trade_plan.setdefault("position_sizing", {}).update({
                        "max_risk_amount": sizing["max_risk_amount"],
                        "risk_per_share": sizing["risk_per_share"],
                        "contracts_or_shares": sizing["qty"],
                    })

            # Options-Plan (analytisch)
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
                options_plan = None

            if options_plan is not None and isinstance(trade_plan, dict):
                trade_plan["options_plan"] = options_plan

            execution_result = None
            if auto_execute and isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
                broker_pref = account_info.get("broker_preference")
                execution_result = _execution_agent.execute_trade_plan(trade_plan, broker_pref)

            setups.append(
                {
                    "symbol": symbol,
                    "news_output": news_output,
                    "regime_output": regime_output,
                    "synthese_output": synthese_output,
                    "signal_output": signal_output,
                    "trade_plan": trade_plan,
                    "execution_result": execution_result,
                }
            )

        except Exception as e:
            print(f"[Scanner] Fehler bei {symbol}: {e}")
            # >>> NEU: Fehler im CircuitBreaker zählen
            _scanner_cb.record_error()

    return {"setups": setups}


if __name__ == "__main__":
    print("Teste Universen...")
    print("SP500:", load_universe("sp500"))
    print("Semis:", load_universe("semis"))
    print("Kombiniert:", combine_universes(["sp500", "semis"]))