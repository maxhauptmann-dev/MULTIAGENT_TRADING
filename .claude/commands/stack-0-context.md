<!-- claude-setup 2.0.3 2026-04-26 -->
## Project

Config files: .env.example, .env.sample
Env vars: MAX_OPEN_POSITIONS, MAX_POSITION_SIZE_PCT

Structure:
mac_dashboard/ (6 files)
  mac_dashboard1/ (3 files)
  mac_dashboard1Tests/ (1 files)
  mac_dashboard1UITests/ (2 files)
api_server.py
BACKTEST.py
DEF_DATA_AGENT.py
DEF_GPT_AGENTS.py
DEF_INDICATORS.py
... +22 more

## Source samples

### universe_manager.py
```
from __future__ import annotations
from pathlib import Path
import json
from typing import List, Dict, Set, Optional
class UniverseNotFoundError(FileNotFoundError):
class UniverseManager:
def __init__(
def _normalize_name(self, name: str) -> str:
def _file_for_universe(self, normalized_name: str) -> Path:
def list_universes(self) -> List[str]:
def exists(self, name: str) -> bool:
def load_universe(self, name: str) -> List[str]:
def combine_universes(self, names: List[str]) -> List[str]:
def get(self, *names: str) -> List[str]:
def info(self) -> str:
def load_universe(name: str) -> List[str]:
def combine_universes(names: List[str]) -> List[str]:
```

### universe_loader.py
```
import json
from pathlib import Path
def load_universe(name: str) -> list[str]:
def combine_universes(names: list[str]) -> list[str]:
```

### trading_agents_with_gpt.py
```
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
from DEF_DATA_AGENT import DataAgent  # IBKR Socket/History
def _as_bool(value: Optional[str]) -> bool:
def _as_positive_float(value: Optional[str]) -> float:
def _assert_env(name: str, value: Optional[str]):
def http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
def http_post(url: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Any:
class ExecutionAgent:
def __init__(self) -> None:
def _should_simulate(self, broker: Optional[str]) -> bool:
def _ensure_paper_guard(self) -> None:
def _cap_quantity(self, qty: float) -> Tuple[float, Dict[str, Any]]:
def _validate_trade_plan(self, trade_plan: Dict[str, Any]) -> Dict[str, Any]:
def _determine_side(self, direction: Optional[str]) -> str:
def _ensure_ibkr_account(self) -> str:
def _ibkr_sec_type(self, instrument_type: str) -> str:
def _ibkr_conid(self, symbol: str, instrument_type: str) -> int:
def _ibkr_buying_power(self, account_id: str) -> Optional[float]:
def _place_ibkr_socket_order(
from DEF_DATA_AGENT import IBKRApi
def place_ibkr_order(
def place_oanda_order(self, symbol: str, side: str, units: float) -> Any:
@staticmethod
def _normalize_alpaca_order_type(order_type: str) -> str:
def place_alpaca_order(
def place_tradier_order(
def simulate_order(
def _check_portfolio_drawdown(self, portfolio_equity: float = 100000.0) -> Dict[str, Any]:
def _check_correlation_with_positions(self, symbol: str, db_path: str = "positions.db") -> Dict[str, Any]:
def _log_risk_decision(self, symbol: str, decision: str, details: str, outcome: str) -> None:
def execute_trade_plan(
def _map_timeframe_to_ibkr(timeframe: str) -> Tuple[str, int]:
from risk import CircuitBreaker as _CB
def run_single_symbol_mode(
from DEF_ML_SIGNAL import _engine as _ml_engine
```

### scheduler.py
```
import logging
import os
import signal
import sys
from typing import List
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
def _lazy_imports():
from DEF_SCANNER_MODE import run_scanner_mode
from MAIN_USER_AGENT import format_scanner_results
from universe_manager import manager as universe_manager
import position_monitor as _pm
def _env_list(key: str, default: str) -> List[str]:
def _build_account_info() -> dict:
def job_scan(market: str) -> None:
def job_flatten() -> None:
def job_backtest() -> None:
from BACKTEST import fetch_candles_yfinance, run_backtest, print_report
from pathlib import Path
from datetime import datetime
class TradingScheduler:
def __init__(self) -> None:
def _register_jobs(self) -> None:
def start(self) -> None:
def stop(self) -> None:
def main() -> None:
def _on_signal(signum, _frame):
```

### risk.py
```
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time
import math
from datetime import datetime, timezone
import sqlite3
def compute_position_size(account_size: float,
def compute_kelly_size(
def compute_adaptive_kelly_size(
@dataclass
class CircuitBreaker:
def __post_init__(self) -> None:
def allow(self) -> bool:
def record_error(self) -> None:
def record_loss(self) -> None:
def reset(self) -> None:
def _reset_locked(self) -> None:
def _trip_locked(self, reason: str) -> None:
def _trip(self, reason: str) -> None:
def state(self) -> Dict[str, Any]:
@dataclass
class PortfolioMetrics:
def __post_init__(self):
def _connect(self):
def update_equity(self, current_equity: float) -> Dict[str, Any]:
def reset_daily(self, new_equity: float) -> None:
def reset_monthly(self, new_equity: float) -> None:
```

### position_monitor.py
```
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv
def _connect() -> sqlite3.Connection:
def _init_db() -> None:
class PositionMonitor:
def __init__(
def open_position(
def close_position(
def get_open_positions(self) -> List[Dict[str, Any]]:
def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
def check_positions(self) -> List[Dict[str, Any]]:
from DEF_INDICATORS import get_vix_level, get_adaptive_atr_multiplier
def close_all_open(self, reason: str = "manual") -> List[Dict[str, Any]]:
def stats(self) -> Dict[str, Any]:
def start(self) -> None:
def stop(self) -> None:
def _loop(self) -> None:
def _get_price(self, symbol: str) -> Optional[float]:
import yfinance as yf
```

### api_server.py
```
import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Dict, Any, List, Optional
from flask import Flask, jsonify, request
from dotenv import load_dotenv
def _connect_db():
def _json_response(data: Any, status: str = "ok") -> dict:
def _get_current_price(symbol: str) -> Optional[float]:
import yfinance as yf
@app.route("/api/positions", methods=["GET"])
def get_positions():
@app.route("/api/market-regime", methods=["GET"])
def get_market_regime():
from DEF_INDICATORS import compute_market_regime
@app.route("/api/trades-today", methods=["GET"])
def get_trades_today():
@app.route("/api/scanner-status", methods=["GET"])
def get_scanner_status():
@app.route("/api/logs/tail", methods=["GET"])
def get_logs_tail():
@app.route("/api/trigger-scan", methods=["POST"])
def trigger_scan():
def run_scan():
from DEF_SCANNER_MODE import run_scanner_mode
from universe_manager import load_universe
@app.route("/api/health", methods=["GET"])
def health():
```

### TRAIN_MODEL.py
```
from __future__ import annotations
import argparse
import logging
import sys
from typing import Dict, List, Any, Optional
import pandas as pd
def _fetch_candles(symbol: str, period: str, interval: str) -> List[Dict[str, Any]]:
import yfinance as yf
def _fetch_market_contexts(
from DEF_ML_SIGNAL import _build_market_ctx
def main(argv: Optional[List[str]] = None) -> None:
from DEF_ML_SIGNAL import MLSignalEngine
```

### TEST_SERPAPI.py
```
import os
import requests
from dotenv import load_dotenv
```

### TEST_SCANNER_MODE.py
```
from pprint import pprint
from DEF_SCANNER_MODE import run_scanner_mode
```

### TEST_IBKR_DATA.py
```
from DEF_DATA_AGENT import DataAgent
```

### TEST_FINNHUB.py
```
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
```

### TEST_EXECUTION_AGENT_RUN.py
```
import os
from trading_agents_with_gpt import ExecutionAgent
import pprint
```

### TEST_EXECUTE_SIMULATE.py
```
import os
from pprint import pprint
from trading_agents_with_gpt import ExecutionAgent
def run_case(title: str, plan: dict, broker: str | None = None):
```

### TEST_ENV.py
```
from dotenv import load_dotenv
import os
import os
from dotenv import load_dotenv
```
