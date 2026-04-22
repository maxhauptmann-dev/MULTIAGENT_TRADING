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

import logging
import os
from typing import Dict, Any, List, Optional, Tuple
from functools import partial

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from DEF_OPTIONS_AGENT import OptionsAgent
from DEF_NEWS_CLIENT import NewsClient
from DEF_GPT_AGENTS import safe_call_gpt_agent, run_calls_parallel
from DEF_INDICATORS import compute_indicators, calculate_symbol_correlation
from risk import compute_adaptive_kelly_size, PortfolioMetrics
import position_monitor as _pm_module
import sqlite3
from datetime import datetime, timezone

try:
    from DEF_DATA_AGENT import DataAgent  # IBKR Socket/History
except ImportError:  # pragma: no cover - optional dependency (requires ibapi)
    DataAgent = None  # type: ignore[assignment]

load_dotenv()


def _as_bool(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_positive_float(value: Optional[str]) -> float:
    try:
        parsed = float(value) if value not in (None, "") else 0.0
    except ValueError:
        parsed = 0.0
    return parsed if parsed > 0 else 0.0


LOG_LEVEL = os.getenv("TRADING_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("ExecutionAgent")

EXECUTION_MODE = os.getenv("EXECUTION_MODE", "simulate").strip().lower()
PAPER_EXECUTE = _as_bool(os.getenv("PAPER_EXECUTE", "0"))
MAX_QTY_CAP = _as_positive_float(os.getenv("MAX_QTY_CAP"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
HTTP_RETRY_TOTAL = int(os.getenv("HTTP_RETRY_TOTAL", "3"))

# ============================================================
# 1. Broker-Config & HTTP-Utils
# ============================================================

CONFIG = {
    "ibkr": {
        # IBKR Client Portal API / Gateway
        "base_url": os.getenv("IBKR_BASE_URL", "https://localhost:5003/v1/api"),
        "account_id": os.getenv("IBKR_ACCOUNT_ID"),
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

# eine Session mit Retries benutzen → Cookies + resilient HTTP
session = requests.Session()
retry_strategy = Retry(
    total=HTTP_RETRY_TOTAL,
    backoff_factor=0.4,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({"User-Agent": "ExecutionAgent/1.0", "Accept": "application/json"})


def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    try:
        resp = session.get(url, headers=headers or {}, timeout=HTTP_TIMEOUT, verify=False)
    except requests.RequestException as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc

    logger.debug("[HTTP GET] %s -> %s", url, resp.status_code)
    if resp.status_code == 401:
        raise RuntimeError(
            f"IBKR: 401 Unauthorized für {url} – Session ist für diese Anfrage noch nicht authentifiziert."
        )
    if not resp.ok:
        raise RuntimeError(f"GET {url} failed: {resp.status_code} {resp.text}")
    return resp.json()


def http_post(url: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Any:
    try:
        resp = session.post(
            url,
            json=body,
            headers=headers or {},
            timeout=HTTP_TIMEOUT,
            verify=False,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc

    logger.debug("[HTTP POST] %s -> %s", url, resp.status_code)
    if resp.status_code == 401:
        raise RuntimeError(
            f"IBKR: 401 Unauthorized für {url} – Session ist für diese Anfrage noch nicht authentifiziert."
        )
    if not resp.ok:
        raise RuntimeError(f"POST {url} failed: {resp.status_code} {resp.text}")
    if resp.text:
        return resp.json()
    return {}



# ============================================================
# 3. ExecutionAgent – Broker-Orders
# ============================================================
class ExecutionAgent:
    """Routes trade plans to the selected broker with guardrails and logging."""

    def __init__(self) -> None:
        # Read runtime environment at instantiation time so tests can change os.environ
        # Betriebsmodus: "simulate" (default), "paper", "live"
        self.mode = os.getenv("EXECUTION_MODE", "simulate").strip().lower()
        # PAPER_EXECUTE muss gesetzt sein, um paper/live Ausführung zu erlauben
        self.paper_guard = _as_bool(os.getenv("PAPER_EXECUTE", "0"))
        # Max qty cap (None = kein Cap)
        max_qty = _as_positive_float(os.getenv("MAX_QTY_CAP", None))
        self.max_qty_cap = max_qty if max_qty > 0 else None
        self.ibkr_conid_cache: Dict[str, int] = {}
        self.ibkr_account_id = CONFIG["ibkr"].get("account_id")
        # Instance logger
        self.logger = logger

    # ---------- internal helpers ----------
    def _should_simulate(self, broker: Optional[str]) -> bool:
        return self.mode == "simulate" or (broker or "").lower() == "simulate"

    def _ensure_paper_guard(self) -> None:
        if self.mode in {"paper", "live"} and not self.paper_guard:
            raise RuntimeError(
                "Ausführung blockiert: PAPER_EXECUTE=1 erforderlich, um Paper/Live Orders zu senden."
            )

    def _cap_quantity(self, qty: float) -> Tuple[float, Dict[str, Any]]:
        info: Dict[str, Any] = {}
        if self.max_qty_cap is not None and qty > self.max_qty_cap:
            info = {"capped": True, "requested_qty": qty, "used_qty": self.max_qty_cap}
            logger.warning("Qty %s über MAX_QTY_CAP %s – capped.", qty, self.max_qty_cap)
            return float(self.max_qty_cap), info
        return qty, info

    def _validate_trade_plan(self, trade_plan: Dict[str, Any]) -> Dict[str, Any]:
        if not trade_plan:
            raise ValueError("trade_plan fehlt")
        if trade_plan.get("action") not in {"open_position", "close_position"}:
            raise ValueError("trade_plan verlangt keine offene/geschlossene Position")
        if not trade_plan.get("symbol"):
            raise ValueError("Symbol fehlt im trade_plan")
        sizing = trade_plan.get("position_sizing") or {}
        try:
            qty = float(sizing.get("contracts_or_shares") or 0)
        except Exception:
            qty = 0.0
        if qty <= 0:
            raise ValueError("Positionsgröße <= 0")
        return {"qty": qty, "sizing": sizing}

    def _determine_side(self, direction: Optional[str]) -> str:
        return "SELL" if (direction or "").lower() == "short" else "BUY"

    # ---------- IBKR helpers ----------
    def _ensure_ibkr_account(self) -> str:
        if self.ibkr_account_id:
            return self.ibkr_account_id
        base = CONFIG["ibkr"]["base_url"]
        data = http_get(f"{base}/iserver/accounts")
        accounts = data.get("accounts") if isinstance(data, dict) else data
        if not accounts:
            raise RuntimeError("IBKR liefert keine Accounts zurück – Client Portal Session aktiv?")
        if isinstance(accounts, list):
            self.ibkr_account_id = accounts[0]
        elif isinstance(accounts, dict) and accounts.get("accounts"):
            self.ibkr_account_id = accounts["accounts"][0]
        else:
            raise RuntimeError("IBKR Accounts Response unbekanntes Format")
        return self.ibkr_account_id

    def _ibkr_sec_type(self, instrument_type: str) -> str:
        mapping = {
            "stock": "STK",
            "equity": "STK",
            "option": "OPT",
            "options": "OPT",
            "future": "FUT",
            "fx": "CASH",
            "forex": "CASH",
        }
        return mapping.get((instrument_type or "stock").lower(), "STK")

    def _ibkr_conid(self, symbol: str, instrument_type: str) -> int:
        cache_key = f"{symbol}_{instrument_type}"
        if cache_key in self.ibkr_conid_cache:
            return self.ibkr_conid_cache[cache_key]
        base = CONFIG["ibkr"]["base_url"]
        body = {
            "symbol": symbol,
            "name": False,
            "secType": self._ibkr_sec_type(instrument_type),
            "exchange": "SMART",
        }
        results = http_post(f"{base}/iserver/secdef/search", body)
        if not results:
            raise RuntimeError(f"IBKR: kein secdef Ergebnis für {symbol}")
        first = results[0]
        conid = int(first.get("conid") or first.get("conidex"))
        self.ibkr_conid_cache[cache_key] = conid
        return conid

    def _ibkr_buying_power(self, account_id: str) -> Optional[float]:
        base = CONFIG["ibkr"]["base_url"]
        try:
            summary = http_get(f"{base}/iserver/account/{account_id}/summary")
            for item in summary.get("accountSummary", []):
                if item.get("tag") == "BuyingPower":
                    return float(item.get("value"))
        except Exception as exc:
            logger.warning("IBKR Buying Power Check fehlgeschlagen: %s", exc)
        return None

    # ---------- broker calls ----------
    def _place_ibkr_socket_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
    ) -> Any:
        """Order über TWS Socket API (ibapi, Port 7497) — kein Client Portal nötig."""
        from DEF_DATA_AGENT import IBKRApi
        api = IBKRApi(
            host=os.getenv("IBKR_SOCKET_HOST", "127.0.0.1"),
            port=int(os.getenv("IBKR_SOCKET_PORT", "7497")),
            client_id=8,
        )
        return api.place_order(symbol, side, float(quantity), order_type, limit_price)

    def place_ibkr_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        instrument_type: str,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
    ) -> Any:
        # Client Portal (REST) versuchen, bei Fehler auf TWS Socket fallback
        try:
            account_id = self._ensure_ibkr_account()
            buying_power = self._ibkr_buying_power(account_id)
            if buying_power is not None and limit_price is not None:
                est_cost = float(quantity) * float(limit_price)
                if est_cost > buying_power:
                    raise RuntimeError(
                        f"IBKR Buying Power ({buying_power}) reicht nicht für Order ({est_cost})."
                    )

            base = CONFIG["ibkr"]["base_url"]
            conid = self._ibkr_conid(symbol, instrument_type)
            body = {
                "orders": [
                    {
                        "account": account_id,
                        "conid": conid,
                        "orderType": order_type,
                        "side": side.lower(),
                        "tif": "DAY",
                        "quantity": quantity,
                        "outsideRTH": False,
                    }
                ]
            }
            if order_type in {"LMT", "LIMIT"} and limit_price is not None:
                body["orders"][0]["price"] = limit_price
            return http_post(f"{base}/iserver/account/{account_id}/orders", body)

        except Exception as exc:
            logger.warning(
                "[ExecutionAgent] Client Portal nicht erreichbar (%s) – "
                "verwende TWS Socket (Port %s).",
                exc, os.getenv("IBKR_SOCKET_PORT", "7497"),
            )
            return self._place_ibkr_socket_order(symbol, side, quantity, order_type, limit_price)

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
        if order_type in {"limit", "stop_limit"} and limit_price is not None:
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
        if order_type.lower() == "limit" and limit_price is not None:
            body["price"] = limit_price

        return http_post(
            url,
            body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    def simulate_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        broker: str = "simulated",
    ) -> Dict[str, Any]:
        receipt = {
            "status": "simulated",
            "broker": broker,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "mock_fill_price": limit_price,
            "message": "Simulationsmodus – kein Broker-Call durchgeführt.",
        }
        logger.info("[ExecutionAgent] %s", receipt)
        return receipt

    # ---------- public API ----------
    def _check_portfolio_drawdown(self, portfolio_equity: float = 100000.0) -> Dict[str, Any]:
        """Check portfolio drawdown status. Returns {allow_new_trades, status, ...}"""
        pm = PortfolioMetrics()
        return pm.update_equity(portfolio_equity)

    def _check_correlation_with_positions(self, symbol: str, db_path: str = "positions.db") -> Dict[str, Any]:
        """
        Check correlation of candidate symbol with open positions.
        Returns {action: ACCEPT|REJECT|REDUCE_SIZE, max_correlation, details}
        """
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            open_pos = conn.execute("SELECT symbol FROM positions WHERE status='open'").fetchall()
            conn.close()
        except Exception:
            return {"action": "ACCEPT", "reason": "DB error, allowing trade"}

        if not open_pos:
            return {"action": "ACCEPT", "reason": "No open positions", "max_correlation": 0.0}

        max_corr = 0.0
        most_correlated = None

        for row in open_pos:
            open_symbol = row[0]
            if open_symbol == symbol:
                continue
            corr = calculate_symbol_correlation(symbol, open_symbol, period="60d")
            if corr is not None and corr > max_corr:
                max_corr = corr
                most_correlated = open_symbol

        if max_corr > 0.85:
            return {
                "action": "REJECT",
                "max_correlation": round(max_corr, 4),
                "reason": f"Correlation {max_corr:.2f} to {most_correlated} exceeds 0.85"
            }
        elif max_corr > 0.70:
            return {
                "action": "REDUCE_SIZE",
                "max_correlation": round(max_corr, 4),
                "reduction_factor": 0.70,
                "reason": f"Correlation {max_corr:.2f} to {most_correlated}, reducing size"
            }
        else:
            return {
                "action": "ACCEPT",
                "max_correlation": round(max_corr, 4),
                "reason": f"Low correlation (max {max_corr:.2f})"
            }

    def _log_risk_decision(self, symbol: str, decision: str, details: str, outcome: str) -> None:
        """Log risk decision to audit table"""
        try:
            conn = sqlite3.connect("positions.db", check_same_thread=False)
            conn.execute(
                """INSERT INTO risk_audit_log (timestamp, symbol, decision, details, outcome)
                   VALUES (?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), symbol, decision, details, outcome)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def execute_trade_plan(
        self,
        trade_plan: Dict[str, Any],
        broker_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            validation = self._validate_trade_plan(trade_plan)
        except ValueError as exc:
            return {"status": "no_trade", "reason": str(exc)}

        symbol = trade_plan.get("symbol")
        instrument_type = (trade_plan.get("instrument_type") or "stock").lower()
        direction = trade_plan.get("direction") or "long"
        side = self._determine_side(direction)
        qty = validation["qty"]
        order_type = (trade_plan.get("order_type") or "MKT").upper()
        limit_price = trade_plan.get("limit_price")
        entry_price = trade_plan.get("entry", {}).get("trigger_price")
        stop_price = trade_plan.get("stop_loss", {}).get("price")

        preferred = (broker_preference or trade_plan.get("broker")) or "ibkr"
        preferred = preferred.lower()

        # Simulation-Short-Circuit
        if self._should_simulate(preferred):
            receipt = self.simulate_order(symbol, side, qty, order_type, limit_price, broker="simulated")
            return {"status": "simulated", "broker": "simulated", "raw": receipt}

        # Papier/LIVE Guard
        try:
            self._ensure_paper_guard()
        except RuntimeError as exc:
            return {"status": "blocked", "reason": str(exc)}

        # ── RISK MANAGEMENT V3 CHECKS ──────────────────────────────────────
        account_size = float(os.getenv("ACCOUNT_SIZE", "100000"))

        # 1) Portfolio Drawdown Check
        portfolio_dd = self._check_portfolio_drawdown(account_size)
        if portfolio_dd["status"] == "halted":
            self._log_risk_decision(symbol, "portfolio_halted", str(portfolio_dd), "REJECT")
            return {"status": "blocked", "reason": f"Portfolio halted: {portfolio_dd['daily_drawdown_pct']}% DD"}
        elif portfolio_dd["status"] == "paused" and trade_plan.get("action") == "open_position":
            self._log_risk_decision(symbol, "portfolio_paused", str(portfolio_dd), "REJECT")
            return {"status": "blocked", "reason": f"Portfolio paused: {portfolio_dd['daily_drawdown_pct']}% DD (close-only)"}

        # 2) Adaptive Kelly Sizing
        if trade_plan.get("action") == "open_position" and entry_price and stop_price:
            kelly_result = compute_adaptive_kelly_size(
                account_size=account_size,
                buy_probability=0.56,  # From ML model accuracy
                rr_ratio=1.91,  # From trade plan
                max_risk_per_trade=float(os.getenv("MAX_RISK_PER_TRADE", "0.01")),
                entry_price=entry_price,
                stop_price=stop_price,
                monthly_drawdown_pct=portfolio_dd.get("monthly_drawdown_pct", 0) / 100,
                recent_win_count=5,  # TODO: Calculate from DB
                recent_trade_count=10
            )
            kelly_qty = kelly_result.get("qty", 0)
            if kelly_qty < qty:
                qty = kelly_qty
                self._log_risk_decision(
                    symbol, "adaptive_kelly",
                    f"Kelly: {kelly_result.get('kelly_fraction_adjusted', 0)}, DD: {portfolio_dd.get('monthly_drawdown_pct', 0)}%",
                    "MODIFIED"
                )
                logger.info(f"[ExecutionAgent] Kelly sizing: {kelly_qty} shares (down from {validation['qty']})")

        # 3) Correlation Filter (only for opening new positions)
        if trade_plan.get("action") == "open_position":
            corr_check = self._check_correlation_with_positions(symbol)
            if corr_check["action"] == "REJECT":
                self._log_risk_decision(symbol, "correlation_reject", str(corr_check), "REJECT")
                return {"status": "blocked", "reason": corr_check["reason"]}
            elif corr_check["action"] == "REDUCE_SIZE":
                qty = int(qty * corr_check["reduction_factor"])
                self._log_risk_decision(symbol, "correlation_reduce", str(corr_check), "MODIFIED")
                logger.info(f"[ExecutionAgent] Correlation reduction: {qty} shares ({corr_check['reason']})")

        # Cap Quantity
        qty, cap_info = self._cap_quantity(qty)
        if cap_info:
            validation["sizing"].update(cap_info)

        try:
            if instrument_type in {"fx", "forex"}:
                res = self.place_oanda_order(symbol, side, qty)
                self._log_risk_decision(symbol, "execution_oanda", "", "SENT")
                return {"status": "sent", "broker": "oanda", "raw": res}

            if preferred == "alpaca":
                res = self.place_alpaca_order(symbol, side, qty, order_type.lower(), limit_price)
                self._log_risk_decision(symbol, "execution_alpaca", f"qty={qty}", "SENT")
                return {"status": "sent", "broker": "alpaca", "raw": res}

            if preferred == "tradier":
                res = self.place_tradier_order(symbol, side, qty, order_type.lower(), limit_price)
                self._log_risk_decision(symbol, "execution_tradier", f"qty={qty}", "SENT")
                return {"status": "sent", "broker": "tradier", "raw": res}

            # Default IBKR path
            res = self.place_ibkr_order(symbol, side, qty, instrument_type, order_type, limit_price)
            self._log_risk_decision(symbol, "execution_ibkr", f"qty={qty}", "SENT")
            return {"status": "sent", "broker": "ibkr", "raw": res}
        except Exception as exc:
            logger.exception("Execution Fehler: %s", exc)
            self._log_risk_decision(symbol, "execution_error", str(exc), "ERROR")
            return {"status": "error", "reason": str(exc)}
# ...existing code...

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
_options_agent = OptionsAgent()
_execution_agent = ExecutionAgent()

# Position-Monitor Singleton initialisieren
from risk import CircuitBreaker as _CB
_single_cb = _CB(n_errors=8, n_losses=3, cooldown_seconds=1800)
_pm_module.monitor = _pm_module.PositionMonitor(
    execution_agent=_execution_agent,
    circuit_breaker=_single_cb,
    check_interval_seconds=int(os.getenv("MONITOR_INTERVAL_SECONDS", "60")),
)

if DataAgent is not None:
    _data_agent = DataAgent()
else:
    _data_agent = None
    logger.warning(
        "DataAgent/ibapi nicht verfügbar – run_single_symbol_mode wird ohne Marktdaten nicht funktionieren."
    )


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

    if _data_agent is None:
        raise RuntimeError(
            "DataAgent ist nicht verfügbar (ibapi fehlt). Bitte `pip install ibapi` und DEF_DATA_AGENT aktivieren."
        )

    # Timeframe → IBKR-Param (bar_size + days)
    bar_size, days = _map_timeframe_to_ibkr(timeframe)

    # 1) Marktdaten über IBKR-Socket-DataAgent
    market_data = _data_agent.fetch(
        symbol=symbol,
        asset_type=asset_type,
        market_hint=market_hint,
        timeframe=timeframe,
    )

    # Indikatoren berechnen und in market_data einbetten
    candles = market_data.get("candles") or []
    indicators = compute_indicators(candles)
    market_data["indicators"] = indicators

    # Markt-Meta inkl. letztem Schlusskurs + ATR ableiten
    market_meta = dict(market_data.get("meta") or {})
    market_meta["atr_14"]  = indicators.get("atr_14")
    market_meta["atr_pct"] = indicators.get("atr_pct")
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
    news_output = safe_call_gpt_agent("news_agent", {"symbol": symbol, "recent_news": recent_news})

    # 3) Analyse-Agents (parallel statt sequenziell)
    agent_tasks = [
        partial(safe_call_gpt_agent, "regime_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "trend_dow_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "sr_formations_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "momentum_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "volume_oi_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "candlestick_agent", {"symbol": symbol, "market_data": market_data}),
        partial(safe_call_gpt_agent, "intermarket_agent", {"symbol": symbol, "market_data": market_data}),
    ]
    agent_results = run_calls_parallel(agent_tasks, max_workers=3, per_call_timeout=30.0)

    regime_output = agent_results[0] or {"error": "no_result"}
    trend_output = agent_results[1] or {"error": "no_result"}
    sr_output = agent_results[2] or {"error": "no_result"}
    momentum_output = agent_results[3] or {"error": "no_result"}
    volume_output = agent_results[4] or {"error": "no_result"}
    candle_output = agent_results[5] or {"error": "no_result"}
    intermarket_output = agent_results[6] or {"error": "no_result"}

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
    synthese_output = safe_call_gpt_agent("synthese_agent", synth_input)

    # 5) Signal — ML-Modell, GPT als Fallback
    from DEF_ML_SIGNAL import _engine as _ml_engine
    if _ml_engine.is_loaded:
        signal_output = _ml_engine.predict(candles, symbol=symbol)
    else:
        signal_output = safe_call_gpt_agent(
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
    trade_plan = safe_call_gpt_agent("handels_agent", handels_input)

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

    # ATR für Trailing Stop einspeichern
    if isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
        trade_plan["_atr_14"] = market_meta.get("atr_14")

    execution_result = None
    if auto_execute and isinstance(trade_plan, dict) and trade_plan.get("action") == "open_position":
        broker_pref = account_info.get("broker_preference")
        execution_result = _execution_agent.execute_trade_plan(trade_plan, broker_pref)
        if _pm_module.monitor:
            _pm_module.monitor.open_position(trade_plan, execution_result)

    return {
        "symbol": symbol,
        "market_meta": market_meta,  # enthält last_close usw.
        "news_output": news_output,
        "synthese_output": synthese_output,
        "signal_output": signal_output,
        "trade_plan": trade_plan,
        "execution_result": execution_result,
    }