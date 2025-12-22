AI_TRADING (Hierarchisches Multi‑Agent‑Modell)

+--------------------------------------------------+
| Lead Agent (MAIN_USER_AGENT.start)               |
|  - Orchestrator / UI                             |
+--------------------------------------------------+
                |
     +-------------------------------+
     |               Modes           |
     +-------------------------------+
       |                            |
       |                            |
       v                            v
+-------------------------------+   +--------------------------------+
| Einzelmodus                   |   | Scannermodus                   |
| run_single_symbol_mode()      |   | DEF_SCANNER_MODE.run_scanner_ |
| (trading_agents_with_gpt)     |   | mode()                         |
+-------------------------------+   +--------------------------------+
       |                                    |
       |                                    |
       |                                    +-----------------------------+
       |                                    | Universe Manager            |
       |                                    | load_universe/combine_      |
       |                                    | universes → Watchlist       |
       |                                    +-----------------------------+
       |                                    |
       |                           pro Symbol (parallel, safe_call_gpt) ────────────────┐
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Data Layer                  |                                              | Data Layer                  |
| DEF_DATA_AGENT.DataAgent    |                                              | DEF_DATA_AGENT.DataAgent    |
|  - IBKR Socket get_conid    |                                              |  - IBKR Socket get_conid    |
|  - get_history → candles    |                                              |  - get_history → candles    |
|  - market_meta.last_close   |                                              |  - market_meta.last_close   |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| News Layer                  |                                              | News Layer                  |
| DEF_NEWS_CLIENT.NewsClient  |                                              | DEF_NEWS_CLIENT.NewsClient  |
|  - Finnhub + SerpAPI        |                                              |  - Finnhub + SerpAPI        |
|  - get_combined_news()      |                                              |  - get_combined_news()      |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+---------------------------------------------------------------+           +---------------------------------------------------------------+
| Analyse‑Agents (DEF_GPT_AGENTS.call_gpt_agent)                |           | Analyse‑Agents (safe_call_gpt_agent, run_calls_parallel)     |
|  - regime_agent                                               |           |  - regime / trend / S/R / momentum / volume / candles /      |
|  - trend_dow_agent                                            |           |    intermarket                                               |
|  - sr_formations_agent                                        |           +---------------------------------------------------------------+
|  - momentum_agent                                             |
|  - volume_oi_agent                                            |
|  - candlestick_agent                                          |
|  - intermarket_agent                                          |
+---------------------------------------------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Synthese                    |                                              | Synthese                    |
| synthese_agent → Marktbild  |                                              | synthese_agent → Marktbild  |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Signal Scanner              |                                              | Signal Scanner              |
| signal_scanner_agent        |                                              | signal_scanner_agent        |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Handels‑Plan                |                                              | Handels‑Plan                |
| handels_agent → trade_plan  |                                              | handels_agent → trade_plan  |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       | Sanity + Sizing                                                               | CircuitBreaker (risk.CircuitBreaker)
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Risk Management             |                                              | Risk Management             |
| risk.compute_position_size  |                                              | risk.compute_position_size  |
|  - qty aus Stop‑Distanz     |                                              |  - qty aus Stop‑Distanz     |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Options‑Plan                |                                              | Options‑Plan                |
| DEF_OPTIONS_AGENT           |                                              | DEF_OPTIONS_AGENT           |
| build_options_plan()        |                                              | build_options_plan()        |
+-----------------------------+                                              +-----------------------------+
       |                                                                                |
       v                                                                                v
+-----------------------------+                                              +-----------------------------+
| Execution (optional Paper)  |                                              | Execution (optional Paper)  |
| ExecutionAgent.execute_     |                                              | ExecutionAgent.execute_     |
| trade_plan() → IBKR/…       |                                              | trade_plan() → IBKR/…       |
+-----------------------------+                                              +-----------------------------+



- .env: OPENAI_API_KEY, IBKR_BASE_URL, FINNHUB_API_KEY, SERPAPI_API_KEY, optional IBKR_SOCKET_HOST/PORT
- universes/: sp500.json, nasdaq100.json, semis.json, dax.json, commodities.json
