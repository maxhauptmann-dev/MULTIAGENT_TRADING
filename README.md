# AI_TRADING – Hierarchisches Multi-Agent-Modell


AI_TRADING

Hierarchical Multi-Agent Trading System
AI_TRADING is a signal-driven, hierarchical multi-agent framework for market analysis, trade planning, and (optional) execution.
It combines market data, news, and multiple specialized AI agents to generate structured, risk-aware trade and options plans.
The system is designed to mirror how a professional discretionary or systematic trader reasons — but in a modular, testable, and scalable architecture.

## Architekturübersicht

```text
+--------------------------------------------------+
| Lead Agent (MAIN_USER_AGENT.start)               |
|  - Orchestrator / UI                             |
+--------------------------------------------------+
                |
     +-------------------------------+
     |              Modes            |
     +-------------------------------+
       |                            |
       |                            |
       v                            v
+-------------------------------+   +--------------------------------+
| Einzelmodus                   |   | Scannermodus                   |
| run_single_symbol_mode()      |   | DEF_SCANNER_MODE.run_scanner_  |
| (trading_agents_with_gpt)     |   | mode()                         |
+-------------------------------+   +--------------------------------+
       |                                    |
       |                                    |
       |                                    +-----------------------------+
       |                                    | Universe Manager            |
       |                                    | load_universe / combine_    |
       |                                    | universes → Watchlist       |
       |                                    +-----------------------------+
       |                                    |
       |                           pro Symbol (parallel, safe_call_gpt)
       |                                    |
       v                                    v
+-----------------------------+      +-----------------------------+
| Data Layer                  |      | Data Layer                  |
| DEF_DATA_AGENT.DataAgent    |      | DEF_DATA_AGENT.DataAgent    |
|  - IBKR Socket get_conid    |      |  - IBKR Socket get_conid    |
|  - get_history → candles    |      |  - get_history → candles    |
|  - market_meta.last_close   |      |  - market_meta.last_close   |
+-----------------------------+      +-----------------------------+
       |                                    |
       v                                    v
+-----------------------------+      +-----------------------------+
| News Layer                  |      | News Layer                  |
| DEF_NEWS_CLIENT.NewsClient  |      | DEF_NEWS_CLIENT.NewsClient  |
|  - Finnhub + SerpAPI        |      |  - Finnhub + SerpAPI        |
|  - get_combined_news()      |      |  - get_combined_news()      |
+-----------------------------+      +-----------------------------+
       |                                    |
       v                                    v
+---------------------------------------------------------------+
| Analyse-Agents                                                |
| (DEF_GPT_AGENTS / safe_call_gpt_agent)                        |
|                                                               |
|  - regime_agent                                               |
|  - trend_dow_agent                                            |
|  - sr_formations_agent                                        |
|  - momentum_agent                                             |
|  - volume_oi_agent                                            |
|  - candlestick_agent                                          |
|  - intermarket_agent                                          |
+---------------------------------------------------------------+
       |
       v
+-----------------------------+
| Synthese                    |
| synthese_agent → Marktbild  |
+-----------------------------+
       |
       v
+-----------------------------+
| Signal Scanner              |
| signal_scanner_agent        |
+-----------------------------+
       |
       v
+-----------------------------+
| Handels-Plan                |
| handels_agent → trade_plan  |
+-----------------------------+
       |
       | Sanity Checks & Sizing
       v
+-----------------------------+
| Risk Management             |
| risk.compute_position_size  |
|  - qty aus Stop-Distanz     |
+-----------------------------+
       |
       v
+-----------------------------+
| Options-Plan                |
| DEF_OPTIONS_AGENT           |
| build_options_plan()        |
+-----------------------------+
       |
       v
+-----------------------------+
| Execution (optional Paper)  |
| ExecutionAgent.execute_     |
| trade_plan() → IBKR / …     |
+-----------------------------+
```

## ExecutionAgent & Broker Safety

The ExecutionAgent now mirrors production rails: it validates each trade plan, enforces quantity caps, performs broker-specific pre-flight checks (IBKR conid lookup + buying-power guard, OANDA/Alpaca/Tradier API assertions), and falls back to a structured simulator when `EXECUTION_MODE=simulate` or the broker preference is `simulate`.

### Required environment

Copy `.env.sample` → `.env` and fill in your own secrets (never commit `.env`):

| Variable | Purpose |
| --- | --- |
| `EXECUTION_MODE` | `simulate` (default), `paper`, or `live`. |
| `PAPER_EXECUTE` | Must be `1` to allow paper/live execution. Acts as a safety switch. |
| `MAX_QTY_CAP` | Absolute position-size clamp enforced before routing. |
| `IBKR_BASE_URL`, `IBKR_ACCOUNT_ID` | Client Portal / Gateway endpoint + paper account id. |
| `OANDA_API_KEY`, `OANDA_ACCOUNT_ID` | Practice credentials for FX orders. |
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Alpaca paper keys (equities / options). |
| `TRADIER_API_KEY`, `TRADIER_ACCOUNT_ID` | Tradier sandbox keys. |

> ⚠️ Replace placeholders in `.env` with your own **secret** keys locally. Rotate any keys that were ever checked into git.

### Optional dependencies

- `pip install openai` is required when you actually call the GPT agents. Without it, the helpers stay importable but return an `openai_missing` error object.
- `pip install ibapi` is required for the IBKR `DataAgent`. When it is missing you can still run the ExecutionAgent + simulate tests, but `run_single_symbol_mode` will raise a helpful error instead of silently failing.

### Smoke test (simulation)

```bash
python TEST_EXECUTE_SIMULATE.py
```

The script forces `EXECUTION_MODE=simulate`, exercises quantity capping, and asserts that every result is either `simulated`, `blocked`, `sent`, or `no_trade`.

### Paper / Live steps

1. Start IBKR Client Portal API (paper) or equivalent broker sandbox.
2. Set `EXECUTION_MODE=paper` and `PAPER_EXECUTE=1` in a local shell.
3. Re-run `TEST_EXECUTE_SIMULATE.py` (should now block if PAPER_EXECUTE unset, otherwise attempt to hit the broker).
4. Use `trading_agents_with_gpt.run_single_symbol_mode(..., auto_execute=True)` to route real trade plans once confident.

