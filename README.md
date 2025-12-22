AI_TRADING
├─ MAIN_USER_AGENT.py
│  ├─ start()
│  │  ├─ Einzelmodus → trading_agents_with_gpt.run_single_symbol_mode()
│  │  └─ Scannermodus → DEF_SCANNER_MODE.run_scanner_mode()
│  ├─ format_single_result()
│  └─ format_scanner_results()
│
├─ trading_agents_with_gpt.py
│  ├─ _data_agent = DataAgent()
│  ├─ _news_client = NewsClient()
│  ├─ _options_agent = OptionsAgent()
│  ├─ _execution_agent = ExecutionAgent()
│  └─ run_single_symbol_mode(symbol, account_info, ...)
│     ├─ DataAgent.fetch() → market_data, market_meta(last_close,…)
│     ├─ NewsClient.get_combined_news() → recent_news
│     ├─ DEF_GPT_AGENTS.call_gpt_agent()
│     │  ├─ regime_agent
│     │  ├─ trend_dow_agent
│     │  ├─ sr_formations_agent
│     │  ├─ momentum_agent
│     │  ├─ volume_oi_agent
│     │  ├─ candlestick_agent
│     │  └─ intermarket_agent
│     ├─ synthese_agent → synthese_output
│     ├─ signal_scanner_agent → signal_output
│     ├─ handels_agent → trade_plan
│     ├─ DEF_OPTIONS_AGENT.OptionsAgent.build_options_plan() → options_plan
│     └─ (optional) ExecutionAgent.execute_trade_plan() → Paper/Sim-Order
│
├─ DEF_SCANNER_MODE.py
│  ├─ _data_agent / _news_client / _options_agent / _execution_agent
│  ├─ _scanner_cb = risk.CircuitBreaker
│  └─ run_scanner_mode(watchlist, account_info, ...)
│     ├─ pro Symbol:
│     │  ├─ DataAgent.fetch()
│     │  ├─ NewsClient.get_combined_news()
│     │  ├─ safe_call_gpt_agent(...) parallel (run_calls_parallel)
│     │  ├─ synthese_agent → synthese_output
│     │  ├─ signal_scanner_agent → signal_output
│     │  ├─ handels_agent → trade_plan
│     │  ├─ risk.compute_position_size() → position_sizing
│     │  ├─ OptionsAgent.build_options_plan() → options_plan
│     │  └─ (optional) ExecutionAgent.execute_trade_plan()
│     └─ CircuitBreaker überwacht Fehler/Losses, Cooldown
│
├─ DEF_DATA_AGENT.py
│  ├─ IBKRClient (EWrapper/EClient) → Socket Events/Historie
│  ├─ IBKRApi.get_conid() / get_history()
│  └─ DataAgent.fetch() → normalisierte candles + meta
│
├─ DEF_NEWS_CLIENT.py
│  ├─ Finnhub company-news
│  └─ SerpAPI google_news
│     └─ get_combined_news() → gemergte/sortierte News
│
├─ DEF_GPT_AGENTS.py
│  ├─ PROMPTS je Agent
│  ├─ call_gpt_agent() (synchron)
│  ├─ safe_call_gpt_agent() (Semaphore/Retry)
│  └─ run_calls_parallel() (ThreadPool)
│
├─ DEF_OPTIONS_AGENT.py
│  └─ OptionsAgent.build_options_plan() → POP, DTE, Delta, Strike
│
├─ risk.py
│  ├─ compute_position_size(account_size, max_risk, entry, stop) → qty
│  └─ CircuitBreaker(n_errors, n_losses, cooldown)
│
├─ universe_manager.py
│  ├─ load_universe(name) → List[str]
│  ├─ combine_universes(names) → deduplizierte Liste
│  └─ manager = Manager()
│
├─ universes/
│  ├─ sp500.json
│  ├─ nasdaq100.json
│  ├─ semis.json
│  ├─ dax.json
│  └─ commodities.json
│
├─ Tests
│  ├─ TEST_ENV.py
│  ├─ TEST_FINNHUB.py
│  ├─ TEST_SERPAPI.py
│  ├─ TEST_IBKR_DATA.py
│  └─ TEST_SCANNER_MODE.py
│
└─ .env (Keys/Config)
   ├─ OPENAI_API_KEY / FINNHUB_API_KEY / SERPAPI_API_KEY
   ├─ IBKR_BASE_URL (Client Portal API)
   └─ optional: IBKR_SOCKET_HOST / IBKR_SOCKET_PORT / Broker-Keys
