# AI_TRADING – Hierarchisches Multi‑Agent‑Modell

```mermaid
flowchart TD
  A[Lead Agent<br/>(MAIN_USER_AGENT.start)] --> B{Modus}
  B --> C[Einzelmodus<br/>(trading_agents_with_gpt.run_single_symbol_mode)]
  B --> D[Scannermodus<br/>(DEF_SCANNER_MODE.run_scanner_mode)]

  %% Scanner: Universen
  A --> U[Universe Manager<br/>(universe_manager)]
  U --> D

  %% Data & News
  C --> E[Data Layer<br/>DEF_DATA_AGENT.DataAgent.fetch()]
  D --> E
  E --> F[News Layer<br/>DEF_NEWS_CLIENT.NewsClient.get_combined_news()]

  %% Analyse-Agents
  F --> G[Analyse‑Agents (DEF_GPT_AGENTS)<br/>regime · trend_dow · sr_formations · momentum · volume_oi · candlestick · intermarket]
  G --> H[Synthese‑Agent<br/>(synthese_agent)]
  H --> I[Signal‑Scanner<br/>(signal_scanner_agent)]
  I --> J[Handels‑Agent<br/>(handels_agent) → trade_plan]

  %% Risk & Options
  J --> K[Risk Management<br/>risk.compute_position_size()]
  D --> CB[[CircuitBreaker<br/>(risk.CircuitBreaker)]]
  J --> L[Options‑Plan<br/>DEF_OPTIONS_AGENT.build_options_plan()]

  %% Execution
  L --> M{auto_execute?}
  M -- ja --> N[ExecutionAgent.execute_trade_plan()<br/>→ IBKR / OANDA / Alpaca / Tradier]
  M -- nein --> O[Output (Plan/Analysen)]
```

## ASCII (Fallback)

```text
AI_TRADING
├─ MAIN_USER_AGENT.start (Lead/Orchestrator)
│  ├─ Einzelmodus → trading_agents_with_gpt.run_single_symbol_mode()
│  └─ Scannermodus → DEF_SCANNER_MODE.run_scanner_mode()
│     └─ Universe Manager → Watchlist (sp500, nasdaq100, semis, dax, commodities)
│
├─ Data Layer → DEF_DATA_AGENT.DataAgent.fetch() → candles, market_meta.last_close
├─ News Layer → DEF_NEWS_CLIENT.NewsClient.get_combined_news()
├─ Analyse‑Agents (DEF_GPT_AGENTS.call/safe_call)
│  ├─ regime · trend_dow · sr_formations · momentum · volume_oi · candlestick · intermarket
│  └─ Synthese → Signal → Handels‑Plan
├─ Risk → risk.compute_position_size() ; Scanner: risk.CircuitBreaker
├─ Options → DEF_OPTIONS_AGENT.build_options_plan()
└─ Execution (optional) → ExecutionAgent.execute_trade_plan() → IBKR/OANDA/Alpaca/Tradier
```
