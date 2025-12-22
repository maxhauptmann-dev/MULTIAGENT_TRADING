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

