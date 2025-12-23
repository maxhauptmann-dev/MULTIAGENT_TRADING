"""
trading_agents_with_gpt.py

Multi-Agent-Trading-Architektur:

- DataAgent  → holt Marktdaten von moomoo / IBKR / OANDA / Alpaca / Tradier
- ExecutionAgent → baut Broker-Orders (IBKR / OANDA / Alpaca / Tradier)
- GPT-Agents (über OpenAI API):
    - regime_agent
    - trend_dow_agent
    - sr_formations_agent
    - momentum_agent
    - volume_oi_agent
    - candlestick_agent
    - intermarket_agent
    - synthese_agent
    - signal_scanner_agent
    - handels_agent

Der User-Agent & Orchestrator sitzen typischerweise in deinem Chat-Flow (z. B. im Agent-Builder)
und rufen die Python-Funktionen `run_single_symbol_mode` bzw. `run_scanner_mode` auf.
"""

import os
from typing import Dict, Any, List, Optional, Tuple

import requests
import urllib3
from dotenv import load_dotenv

from DEF_OPTIONS_AGENT import OptionsAgent
from DEF_NEWS_CLIENT import NewsClient
from DEF_GPT_AGENTS import call_gpt_agent
from DEF_DATA_AGENT import DataAgent  # IBKR Socket/History
from risk import compute_position_size

load_dotenv()

# Execution-Schutz
PAPER_EXECUTE = os.getenv("PAPER_EXECUTE", "0").lower() in {"1", "true", "yes"}
MAX_QTY_CAP = int(os.getenv("MAX_QTY_CAP", "0") or 0)

# ============================================================
# 1. Broker-Config & HTTP-Utils
# ============================================================

CONFIG = {
    "ibkr": {
        # IBKR Client Portal API / Gateway
        "base_url": os.getenv("IBKR_BASE_URL", "https://localhost:5000/v1/api"),
    },
    "oanda": {
        "base_url": os.getenv("OANDA_BASE_URL", "https://api-fxtrade.oanda.com"),
        "api_key": os.getenv("OANDA_API_KEY"),
        "account_id": os.getenv("OANDA_ACCOUNT_ID"),
    },
    "alpaca": {
        "base_url": os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        "data_url": os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets"),
        "api_key": os.getenv("ALPACA_API_KEY"),
        "api_secret": os.getenv("ALPACA_API_SECRET"),
    },
    "tradier": {
        "base_url": os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1"),
        "api_key": os.getenv("TRADIER_API_KEY"),
        "account_id": os.getenv("TRADIER_ACCOUNT_ID"),
    },
}


def _assert_env(name: str, value: Optional[str]):
    if not value:
        raise RuntimeError(f"Umgebungsvariable {name} ist nicht gesetzt.")


# Warnung für self-signed Zertifikat unterdrücken (IBKR localhost)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# eine Session benutzen → Cookies bleiben erhalten
session = requests.Session()


def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    resp = session.get(url, headers=headers or {}, verify=False)
    print(f"[HTTP GET] {url} -> {resp.status_code}")
    if resp.status_code == 401:
        raise RuntimeError(
            f"IBKR: 401 Unauthorized für {url} – Session ist für diese Anfrage noch nicht authentifiziert."
        )
    if not resp.ok:
        raise RuntimeError(f"GET {url} failed: {resp.status_code} {resp.text}")
    return resp.json()


def http_post(url: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Any:
    resp = session.post(url, json=body, headers=headers or {}, verify=False)
    print(f"[HTTP POST] {url} -> {resp.status_code}")
    if resp.status_code == 401:
        raise RuntimeError(
            f"IBKR: 401 Unauthorized für {url} – Session ist für diese Anfrage noch nicht authentifiziert."
        )
    if not resp.ok:
        raise RuntimeError(f"POST {url} failed: {resp.status_code} {resp.text}")
    return resp.json()


# ============================================================
# 3. ExecutionAgent – Broker-Orders
# ============================================================

class ExecutionAgent:
    def place_ibkr_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
    ) -> Any:
        base = CONFIG["ibkr"]["base_url"]
        url = f"{base}/iserver/account/orders"
        body = {
            "orders": [
                {
                    "symbol": symbol,
                    "side": side,             # "BUY" / "SELL"
                    "orderType": order_type,  # "MKT", "LMT", ...
                    "quantity": quantity,
                    "lmtPrice": limit_price,
                }
            ]
        }
        return http_post(url, body)

    def place_oanda_order(self, symbol: str, side: str, units: float) -> Any:
        api_key = CONFIG["oanda"]["api_key"]
        account_id = CONFIG["oanda"]["account_id"]
        _assert_env("OANDA_API_KEY", api_key)
        _assert_env("OANDA_ACCOUNT_ID", account_id)

        base = CONFIG["oanda"]["base_url"]
        url = f"{base}/v3/accounts/{account_id}/orders"
        body = {
            "order": {
                "instrument": symbol,
                "units": str(units if side.upper() == "BUY" else -abs(units)),
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        return http_post(url, body, headers={"Authorization": f"Bearer {api_key}"})

    def place_alpaca_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Any:
        api_key = CONFIG["alpaca"]["api_key"]
        api_secret = CONFIG["alpaca"]["api_secret"]
        _assert_env("ALPACA_API_KEY", api_key)
        _assert_env("ALPACA_API_SECRET", api_secret)

        base = CONFIG["alpaca"]["base_url"]
        url = f"{base}/v2/orders"
        body = {
            "symbol": symbol,
            "side": side.lower(),
            "type": order_type,
            "qty": qty,
            "time_in_force": "day",
        }
        if order_type == "limit" and limit_price is not None:
            body["limit_price"] = limit_price

        return http_post(
            url,
            body,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
            },
        )

    def place_tradier_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Any:
        api_key = CONFIG["tradier"]["api_key"]
        account_id = CONFIG["tradier"]["account_id"]
        _assert_env("TRADIER_API_KEY", api_key)
        _assert_env("TRADIER_ACCOUNT_ID", account_id)

        base = CONFIG["tradier"]["base_url"]
        url = f"{base}/accounts/{account_id}/orders"
        body = {
            "class": "equity",
            "symbol": symbol,
            "side": side.lower(),
            "quantity": qty,
            "type": order_type.lower(),
            "duration": "day",
        }
        if order_type == "limit" and limit_price is not None:
            body["price"] = limit_price

        return http_post(
            url,
            body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    def execute_trade_plan(
        self,
        trade_plan: Dict[str, Any],
        broker_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not trade_plan or trade_plan.get("action") != "open_position":
            return {"status": "no_trade", "reason": "Keine offene Position laut trade_plan."}

        if not PAPER_EXECUTE:
            return {
                "status": "blocked",
                "reason": "PAPER_EXECUTE ist nicht gesetzt – Ausführung gesperrt.",
            }

        symbol = trade_plan.get("symbol")
        direction = trade_plan.get("direction") or "long"
        instrument_type = trade_plan.get("instrument_type") or "stock"
        sizing = trade_plan.get("position_sizing") or {}
        qty = sizing.get("contracts_or_shares", 0)

        original_qty = qty
        if MAX_QTY_CAP > 0 and qty > MAX_QTY_CAP:
            qty = MAX_QTY_CAP
            sizing["capped"] = True
            sizing["requested_qty"] = original_qty
            sizing["used_qty"] = qty

        if not symbol or qty <= 0:
            return {"status": "error", "reason": "Symbol oder Positionsgröße fehlt."}

        side = "SELL" if direction == "short" else "BUY"

        # Routing: FX → OANDA
        if instrument_type == "fx":
            res = self.place_oanda_order(symbol, side, qty)
            return {"status": "sent", "broker": "oanda", "raw": res}

        # US-Optionen → Alpaca / Tradier (wenn gewünscht)
        if broker_preference == "alpaca":
            res = self.place_alpaca_order(symbol, side, qty)
            return {"status": "sent", "broker": "alpaca", "raw": res}

        if broker_preference == "tradier":
            res = self.place_tradier_order(symbol, side, qty)
            return {"status": "sent", "broker": "tradier", "raw": res}

        # Default: IBKR
        res = self.place_ibkr_order(symbol, side, qty)
        return {"status": "sent", "broker": "ibkr", "raw": res}


# ============================================================
# 4. Timeframe Mapping
# ============================================================

def _map_timeframe_to_ibkr(timeframe: str) -> Tuple[str, int]:
    """
    Mappt dein Timeframe (z.B. '1D', '1H', '5m') auf
    - IBKR barSizeSetting (z.B. '1 day', '1 hour', '5 mins')
    - und eine sinnvolle Anzahl Tage für die Historie.
    """
    tf = (timeframe or "").lower().strip()

    # Tageschart → 180 Tage
    if tf in ("1d", "d1", "1day", "1 day"):
        return "1 day", 180

    # Stundenchart → 60 Tage
    if tf in ("1h", "h1", "1hour", "1 hour"):
        return "1 hour", 60

    # 5-Minuten-Chart → 10 Tage
    if tf in ("5m", "5min", "5 mins", "5 minutes"):
        return "5 mins", 10

    # Fallback: alles Andere einfach durchreichen, 120 Tage
    return timeframe, 120


# ============================================================
# 5. Orchestrator-Funktionen
# ============================================================

_news_client = NewsClient()
_data_agent = DataAgent()
_execution_agent = ExecutionAgent()
_options_agent = OptionsAgent()


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _validate_and_size_trade_plan(
    trade_plan: Dict[str, Any],
    account_info: Dict[str, Any],
    market_meta: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(trade_plan, dict):
        return trade_plan

    last_close = _safe_float((market_meta or {}).get("last_close"))
    entry_price = _safe_float((trade_plan.get("entry") or {}).get("trigger_price"))
    stop_price = _safe_float((trade_plan.get("stop_loss") or {}).get("price"))
    direction = (trade_plan.get("direction") or "long").lower()

    flags = []
    action = trade_plan.get("action")

    if last_close is None:
        flags.append("last_close_missing")
    if entry_price is None:
        flags.append("entry_missing")
    if stop_price is None:
        flags.append("stop_missing")

    if flags:
        trade_plan["sanity_flags"] = flags
        trade_plan["action"] = "no_trade"
        trade_plan["sanity_reason"] = "Preis-Informationen fehlen (entry/stop/last_close)."
        return trade_plan

    # Entry vs. Marktpreis sanity: ±5%
    entry_deviation = abs(entry_price - last_close) / max(last_close, 1e-9)
    if entry_deviation > 0.05:
        flags.append("entry_far_from_last_close")

    # Stop-Distanz sanity: < 15% vom Marktpreis
    stop_dist_pct = abs(entry_price - stop_price) / max(last_close, 1e-9)
    if stop_dist_pct > 0.15:
        flags.append("stop_too_far")

    # Richtungskonsistenz
    if direction == "long" and stop_price >= entry_price:
        flags.append("stop_not_below_entry_for_long")
    if direction == "short" and stop_price <= entry_price:
        flags.append("stop_not_above_entry_for_short")

    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        flags.append("invalid_risk_per_share")

    if flags:
        trade_plan["sanity_flags"] = flags
        trade_plan["action"] = "no_trade"
        trade_plan["sanity_reason"] = ", ".join(flags)
        return trade_plan

    # Positionsgröße konservativ berechnen
    size_info = compute_position_size(
        account_size=account_info.get("account_size", 0),
        max_risk_per_trade=account_info.get("max_risk_per_trade", 0),
        entry_price=entry_price,
        stop_price=stop_price,
    )

    trade_plan["position_sizing"] = {
        "max_risk_amount": size_info.get("max_risk_amount"),
        "risk_per_share": size_info.get("risk_per_share"),
        "contracts_or_shares": size_info.get("qty", 0),
    }

    trade_plan["sanity_flags"] = flags
    return trade_plan


def run_single_symbol_mode(
    symbol: str,
    account_info: Dict[str, Any],
    timeframe: str = "1D",
    asset_type: str = "stock",
    market_hint: str = "US",
    auto_execute: bool = False,
) -> Dict[str, Any]:
    """
    Modus A – Einzelaktie:
    1. DataAgent holt Marktdaten.
    2. Analyse-Agents: Regime, Trend, S/R, Momentum, Volumen, Candles, Intermarket.
    3. Synthese-Agent → Marktbild.
    4. Signal-Scanner-Agent.
    5. Handels-Agent: Trade-Plan.
    6. Optional: Execution-Agent → Order-API.
    """

    # Timeframe → IBKR-Param (bar_size + days)
    bar_size, days = _map_timeframe_to_ibkr(timeframe)

    # 1) Marktdaten über IBKR-Socket-DataAgent
    market_data = _data_agent.fetch(
        symbol=symbol,
        asset_type=asset_type,
        market_hint=market_hint,
        timeframe=timeframe,
    )

    # Markt-Meta inkl. letztem Schlusskurs ableiten
    candles = market_data.get("candles") or []
    market_meta = dict(market_data.get("meta") or {})
    if candles:
        last = candles[-1]
        try:
            market_meta["last_close"] = float(last["close"])
            market_meta["last_open"] = float(last["open"])
            market_meta["last_high"] = float(last["high"])
            market_meta["last_low"] = float(last["low"])
        except Exception:
            market_meta["last_close"] = None
    else:
        market_meta["last_close"] = market_meta.get("last_close")

    # 2) News einsammeln
    combined_news = _news_client.get_combined_news(
        symbol=symbol,
        days_back=5,
        limit_per_source=20,
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
        for item in (combined_news or [])
        if item.get("headline")
    ]
    news_output = call_gpt_agent("news_agent", {"symbol": symbol, "recent_news": recent_news})

    # 3) Analyse-Agents
    regime_output = call_gpt_agent("regime_agent", {"symbol": symbol, "market_data": market_data})
    trend_output = call_gpt_agent("trend_dow_agent", {"symbol": symbol, "market_data": market_data})
    sr_output = call_gpt_agent("sr_formations_agent", {"symbol": symbol, "market_data": market_data})
    momentum_output = call_gpt_agent("momentum_agent", {"symbol": symbol, "market_data": market_data})
    volume_output = call_gpt_agent("volume_oi_agent", {"symbol": symbol, "market_data": market_data})
    candle_output = call_gpt_agent("candlestick_agent", {"symbol": symbol, "market_data": market_data})
    intermarket_output = call_gpt_agent("intermarket_agent", {"symbol": symbol, "market_data": market_data})

    # 4) Synthese
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
    synthese_output = call_gpt_agent("synthese_agent", synth_input)

    # 5) Signal
    signal_output = call_gpt_agent(
        "signal_scanner_agent",
        {"symbol": symbol, "synthese_output": synthese_output},
    )

    # 6) Handel
    handels_input = {
        "symbol": symbol,
        "synthese_output": synthese_output,
        "signal_output": signal_output,
        "account_info": account_info,
        "market_meta": market_meta,
    }
    trade_plan = call_gpt_agent("handels_agent", handels_input)

    # Sanity-Checks + konservative Positionsgröße
    trade_plan = _validate_and_size_trade_plan(trade_plan, account_info, market_meta)

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
            market_meta=market_meta,
        )
    except Exception as e:
        print(f"[OptionsAgent] Fehler bei {symbol}: {e}")
        options_plan = None

    if options_plan is not None and isinstance(trade_plan, dict):
        trade_plan["options_plan"] = options_plan

    execution_result = None
    if auto_execute and isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
        broker_pref = account_info.get("broker_preference")
        execution_result = _execution_agent.execute_trade_plan(trade_plan, broker_pref)

    return {
        "symbol": symbol,
        "market_meta": market_meta,  # enthält last_close usw.
        "news_output": news_output,
        "synthese_output": synthese_output,
        "signal_output": signal_output,
        "trade_plan": trade_plan,
        "execution_result": execution_result,
    }