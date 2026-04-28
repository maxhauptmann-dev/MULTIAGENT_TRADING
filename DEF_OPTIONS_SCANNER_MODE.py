# DEF_OPTIONS_SCANNER_MODE.py
"""
Options Scanner — parallel options analysis and execution.
Runs independently from stock scanner, evaluates POP scores and contracts.
"""

import os
import concurrent.futures
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from DEF_DATA_AGENT import DataAgent
from trading_agents_with_gpt import ExecutionAgent
from DEF_GPT_AGENTS import safe_call_gpt_agent
from DEF_OPTIONS_AGENT import OptionsAgent
from DEF_INDICATORS import compute_market_regime
import position_monitor as _pm_module

# Eigene Instanzen für den Options-Scanner
_data_agent = DataAgent()
_execution_agent = ExecutionAgent()
_options_agent = OptionsAgent()

# Konfiguration
_SCANNER_MAX_WORKERS = int(os.getenv("SCANNER_MAX_WORKERS", "4"))
_MIN_POP = float(os.getenv("OPTIONS_MIN_POP", "0.65"))


def _process_options_symbol(
    symbol: str,
    account_info: Dict[str, Any],
    timeframe: str,
    market_hint: str,
    auto_execute: bool,
    market_regime: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Verarbeitet ein Symbol für Options-Analyse. Thread-safe."""
    if market_regime is None:
        market_regime = {}

    try:
        # Fetch market data für Synthese-Input
        market_data = _data_agent.fetch(
            symbol=symbol,
            timeframe=timeframe,
            asset_type="stock",
            market_hint=market_hint,
        )

        candles = market_data.get("candles") or []
        if len(candles) < 20:
            return {
                "symbol": symbol,
                "options_plan": None,
                "reason": "insufficient_data",
            }

        # Synthese-Input vorbereiten (vereinfacht für Options)
        from DEF_INDICATORS import compute_indicators

        indicators = compute_indicators(candles)
        market_data["indicators"] = indicators

        market_meta = dict(market_data.get("meta") or {})
        market_meta["atr_14"] = indicators.get("atr_14")
        market_meta["atr_pct"] = indicators.get("atr_pct")

        # Minimal synthese for options context
        synthese_input = {
            "symbol": symbol,
            "market_data": market_data,
            "market_meta": market_meta,
            "indicators": indicators,
            "market_regime": market_regime.get("regime", "neutral"),
            "timeframe": timeframe,
        }

        synthese_output = safe_call_gpt_agent("synthese_agent", synthese_input)

        signal_input = {
            "symbol": symbol,
            "market_data": market_data,
            "market_meta": market_meta,
            "indicators": indicators,
            "timeframe": timeframe,
        }
        signal_output = safe_call_gpt_agent("signal_agent", signal_input)

        # News-Sentiment (optional für Options)
        news_output = None
        try:
            from DEF_NEWS_CLIENT import NewsClient

            news_client = NewsClient()
            news_output = news_client.fetch_sentiment(symbol, limit=10)
        except Exception:
            news_output = None

        # Build Options Plan — hier ist der zentrale POP-Check
        options_plan = None
        try:
            options_plan = _options_agent.build_options_plan(
                symbol=symbol,
                trade_plan={"action": "open_position", "direction": "long"},  # Dummy trade plan für Options
                synthese_output=synthese_output,
                signal_output=signal_output,
                news_output=news_output,
                account_info=account_info,
                market_meta=market_meta,
            )
        except Exception as e:
            print(f"[OptionsAgent] {symbol}: {e}")
            return {
                "symbol": symbol,
                "options_plan": None,
                "reason": f"options_agent_error_{str(e)[:30]}",
            }

        # POP-Check: Nur wenn Score gut genug
        if not options_plan or not isinstance(options_plan, dict):
            return {
                "symbol": symbol,
                "options_plan": None,
                "reason": "no_options_plan",
            }

        pop_score = options_plan.get("pop_score", 0)
        if pop_score < _MIN_POP:
            return {
                "symbol": symbol,
                "options_plan": options_plan,
                "reason": f"pop_too_low_{pop_score:.2f}",
            }

        # Fetch best contract
        opt_type = options_plan.get("type", "call")
        dte_min = options_plan.get("dte_target", {}).get("min", 20)
        dte_max = options_plan.get("dte_target", {}).get("max", 45)
        delta_target = options_plan.get("delta_target", 0.5)

        contract = _execution_agent.fetch_best_option_contract(
            symbol, opt_type, dte_min, dte_max, delta_target
        )

        if not contract:
            return {
                "symbol": symbol,
                "options_plan": options_plan,
                "reason": "no_contract_found",
            }

        # Berechne IMPROVED POP mit allen realen Faktoren
        contract_delta = contract.get("delta", delta_target)
        analytical_pop = options_plan.get("pop_score", 0)
        dte = contract.get("dte", 30)
        strike = contract.get("strike", 0)

        # Für IV-Qualität benötigen wir IV-Daten - nutze Synthese-Output wenn verfügbar
        current_iv = 0.25  # Default
        iv_percentile = 0.5  # Default middle
        if market_meta:
            vol_level = market_data.get("volatility_level", "").lower()
            # Map volatility_level zu IV-Wert und Percentile
            if vol_level in ("high", "hoch"):
                current_iv = 0.40
                iv_percentile = 0.75
            elif vol_level in ("very_high", "extrem"):
                current_iv = 0.60
                iv_percentile = 0.85
            elif vol_level in ("low", "niedrig"):
                current_iv = 0.15
                iv_percentile = 0.25

        # Aktuelle Premium (vereinfacht: nutze mid-point Estimate)
        current_premium = 0.0
        if strike > 0:
            moneyness = abs(market_data.get("price", strike) - strike) / strike
            # Grobe Schätzung: ATM ~2-3%, OTM ~0.5-1.5%
            if moneyness < 0.01:
                current_premium = 2.5
            elif moneyness < 0.05:
                current_premium = 1.5
            else:
                current_premium = 0.75

        # IMPROVED POP Berechnung
        pop_result = _options_agent.calculate_improved_pop(
            option_type=opt_type,
            analytical_pop=analytical_pop,
            contract_delta=contract_delta,
            dte=dte,
            current_iv=current_iv,
            iv_percentile=iv_percentile,
            current_premium=current_premium,
            underlying_price=market_data.get("price", strike),
            strike=strike,
        )

        improved_pop = pop_result["pop"]

        # Aktualisiere options_plan mit ALLEN POP-Details
        options_plan["pop_score"] = improved_pop  # Update mit improved value
        options_plan["analytical_pop"] = round(analytical_pop, 3)
        options_plan["improved_pop_breakdown"] = pop_result
        options_plan["iv_environment"] = {
            "current_iv": round(current_iv, 3),
            "iv_percentile": round(iv_percentile, 3),
            "iv_crush_risk": pop_result.get("iv_crush_risk", 0),
        }

        # Nutze IMPROVED_POP für Threshold-Check
        if improved_pop < _MIN_POP:
            return {
                "symbol": symbol,
                "options_plan": options_plan,
                "contract": contract,
                "reason": f"improved_pop_too_low_{improved_pop:.2f}",
            }

        # Optional: Auto-Execute
        execution_result = None
        if auto_execute:
            contracts_count = options_plan.get("contracts", 1)
            try:
                occ_symbol = contract["occ_symbol"]
                execution_result = _execution_agent.place_alpaca_options_order(
                    occ_symbol, "buy", contracts_count
                )

                if execution_result and execution_result.get("id"):
                    # Register in options_monitor
                    if _pm_module.options_monitor:
                        _pm_module.options_monitor.open_option(
                            options_plan, contract, contracts_count
                        )

                    print(
                        f"[OptionsScanner] {symbol}: {occ_symbol} @ {contract['strike']} "
                        f"({contracts_count} contracts, DTE: {contract['dte']}, POP: {pop_score:.2f})"
                    )
            except Exception as e:
                print(f"[OptionsScanner] Execution error {symbol}: {e}")
                execution_result = {"error": str(e)}

        return {
            "symbol": symbol,
            "options_plan": options_plan,
            "contract": contract,
            "pop_score": pop_score,
            "execution_result": execution_result,
            "status": "success",
        }

    except Exception as e:
        print(f"[OptionsScanner] {symbol}: {e}")
        import traceback

        traceback.print_exc()
        return {
            "symbol": symbol,
            "options_plan": None,
            "reason": f"error_{str(e)[:30]}",
        }


def run_options_scanner_mode(
    watchlist: List[str],
    account_info: Dict[str, Any],
    timeframe: str = "1D",
    market_hint: str = "US",
    auto_execute: bool = False,
    max_workers: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Options Scanner — parallel options analysis.
    Evaluates POP scores and fetches contracts for symbols meeting threshold.
    """
    workers = max_workers or _SCANNER_MAX_WORKERS
    workers = max(1, min(workers, len(watchlist)))

    # Fetch market regime once
    market_regime = compute_market_regime()
    regime = market_regime.get("regime", "neutral")
    vix = market_regime.get("vix", 20.0)
    print(
        f"[OptionsScanner] Market: {regime.upper()} | VIX: {vix:.2f} | "
        f"Min POP: {_MIN_POP:.2f}"
    )

    print(f"[OptionsScanner] Starte: {len(watchlist)} Symbole, {workers} Threads")

    setups: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _process_options_symbol,
                symbol,
                account_info,
                timeframe,
                market_hint,
                auto_execute,
                market_regime,
            ): symbol
            for symbol in watchlist
        }

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                setups.append(result)

    # Summary
    successful = [s for s in setups if s.get("status") == "success"]
    executed = [
        s
        for s in successful
        if s.get("execution_result") and not s["execution_result"].get("error")
    ]
    print(
        f"[OptionsScanner] Abgeschlossen: {len(successful)}/{len(setups)} gescannt, "
        f"{len(executed)} ausgeführt"
    )

    return {
        "setups": setups,
        "summary": {
            "total_scanned": len(setups),
            "successful": len(successful),
            "executed": len(executed),
        },
    }


if __name__ == "__main__":
    # Test
    test_watchlist = ["AAPL", "MSFT", "GOOGL"]
    result = run_options_scanner_mode(
        test_watchlist,
        account_info={
            "account_size": 100000,
            "max_risk_per_trade": 0.01,
            "broker_preference": "alpaca",
        },
        auto_execute=False,
    )
    print("\nTest Results:")
    print(f"Setups: {len(result['setups'])}")
    for setup in result["setups"]:
        print(f"  {setup['symbol']}: {setup.get('reason', setup.get('status', 'unknown'))}")
