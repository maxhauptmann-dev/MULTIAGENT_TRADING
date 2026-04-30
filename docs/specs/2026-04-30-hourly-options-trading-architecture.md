# Hourly Multi-Timeframe Options Trading Architecture

**Datum:** 2026-04-30  
**Status:** Design Document  
**Scope:** Complete refactor of trading system to support hourly rebalancing with technical analysis-driven options strategies

---

## 1. Ziel & Anforderungen

### Hauptziel
Automatisierter Trading-Bot der **stündlich** technische Signale generiert und automatisch Stock- und Options-Positionen verwaltet, um Intraday-Bewegungen zu kapitalisieren.

### Anforderungen
- **Stündliches Rebalancing** (nicht täglich wie jetzt)
- **Multi-Timeframe Analyse** (hourly Signale + daily Kontext)
- **Technische Indikatoren** (RSI, MACD, ATR, Moving Averages)
- **Options-Strategien** (Directional Calls/Puts, Spreads, Straddles)
- **Integrated Risk Management** (Greeks, Portfolio-Limits, Stop-Loss/Take-Profit)
- **Automatische Execution** (Stock + Options Orders)
- **Separate Hedging & Independent Trading** (Put-Schutz für Aktien + unabhängige Richtungswetten)

### Success Criteria
1. ✅ Bot läuft stündlich (nicht täglich)
2. ✅ Jedes Signal basiert auf 3+ Indikatoren (RSI/MACD/ATR)
3. ✅ Mindestens 3 Options-Strategien implementiert (Call, Put, Spread)
4. ✅ Portfolio-Delta immer innerhalb ±0.30
5. ✅ Alle Positionen haben explizite Stop-Loss/Take-Profit
6. ✅ Min. 80% der generierten Signale werden automatisch ausgeführt

---

## 2. System-Architektur

### 2.1 Komponenten-Übersicht

```
┌──────────────────────────────────────────────────────────────┐
│              TradingOrchestrator                             │
│  (Zentrale Koordination - stündlich via Scheduler)           │
└──────────────────┬───────────────────────────────────────────┘
                   │
           ┌───────┴────────┬─────────────┬──────────────┐
           ▼                ▼             ▼              ▼
      DataFetcher    AnalyticsEngine  StrategyEngine  RiskManager
      • 1h candles   • RSI/MACD/ATR   • Signal Gen    • Greeks
      • 1d candles   • Multi-TF       • POP Scoring   • Portfolio
      • IV           • Trend detect   • Trade Plans   • Exposure
      • Cached                        • Sizing        • Limits
           │                ▼             ▼              ▼
           └────────────────┬─────────────┴──────────────┘
                            │
                    ┌───────┴────────┐
                    ▼                ▼
               ExecutionEngine   PositionMonitor
               • Place Orders    • Track Stocks
               • Log Trades      • Track Options
               • Error Handling  • Database
```

### 2.2 Neue Module (5 Dateien)

| Modul | Zweck | Key Classes |
|-------|-------|-------------|
| `trading_orchestrator.py` | Zentrale Koordination, Scheduler | `TradingOrchestrator` |
| `data_fetcher.py` | Alpaca-Daten (Kerzen, IV, Positions) | `DataFetcher` |
| `analytics_engine.py` | Technische Indikatoren + Trend-Analyse | `AnalyticsEngine`, `TechnicalIndicators` |
| `strategy_engine.py` | Signal-Generierung (hourly + daily) | `StrategyEngine`, `SignalGenerator` |
| `risk_manager.py` | Greeks, Portfolio-Limits, Validierung | `RiskManager`, `GreeksCalculator` |

### 2.3 Bestehende Module (angepasst)

| Modul | Änderung |
|-------|----------|
| `position_monitor.py` | Bleibt compatible, erweitert um hourly-Support; `OptionsPositionMonitor` wird stündlich gesynct |
| `DEF_INDICATORS.py` | Wird in `AnalyticsEngine` integriert; RSI/MACD/ATR Logik reused |
| `DEF_OPTIONS_AGENT.py` | Wird von `StrategyEngine` genutzt für Options-Plan Details |
| `api_server.py` | Flask API erweitert um `/orchestrator/status`, `/signals/last_hour` |

---

## 3. Detailliertes Design

### 3.1 TradingOrchestrator

**Verantwortlichkeit:** Zentrale Koordination, Scheduler, Fehlerbehandlung

```python
class TradingOrchestrator:
    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.analytics = AnalyticsEngine()
        self.strategy = StrategyEngine()
        self.risk_mgr = RiskManager()
        self.executor = ExecutionEngine()
        
    def run_hourly_cycle(self) -> Dict:
        """Läuft jede Stunde um X:00 UTC"""
        try:
            # 1. Fetch data
            market_data = self.data_fetcher.fetch_all_symbols()
            
            # 2. Analyze
            indicators = self.analytics.compute_all(market_data)
            
            # 3. Generate signals
            signals = self.strategy.generate_signals(indicators, market_data)
            
            # 4. Validate risks
            validated_signals = self.risk_mgr.validate(signals, current_positions)
            
            # 5. Execute
            results = self.executor.execute_signals(validated_signals)
            
            # 6. Log & Notify
            self._log_cycle(results)
            
            return {"status": "success", "signals_executed": len(results)}
        except Exception as e:
            self._handle_error(e)
            return {"status": "error", "reason": str(e)}
```

**Scheduler Integration:**
- Läuft via APScheduler (bereits in position_monitor.py vorhanden)
- Trigger: Täglich um 10:00 UTC (Markt-Open +30min), dann stündlich bis 20:00 UTC
- Fallback: Wenn Zyklus länger als 55 Sekunden dauert, nächste Stunde überspringen

---

### 3.2 DataFetcher

**Verantwortlichkeit:** Daten von Alpaca fetchen, cachen, validieren

```python
class DataFetcher:
    def __init__(self):
        self.alpaca_client = StockHistoricalDataClient(...)
        self.options_chain_cache = {}  # Symbol -> OptionChain
        self.cache_ttl = 3600  # 1 Stunde
        
    def fetch_all_symbols(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetcht Kerzen + IV für alle Symbole"""
        result = {}
        for symbol in symbols:
            result[symbol] = self.fetch_symbol(symbol)
        return result
    
    def fetch_symbol(self, symbol: str) -> MarketData:
        """Fetcht für 1 Symbol:
        - 1h candles (letzte 72h)
        - 1d candles (letzte 365 Tage)
        - Current IV (cached)
        - Current Price
        """
        return MarketData(
            symbol=symbol,
            hourly_candles=self._fetch_hourly(symbol),
            daily_candles=self._fetch_daily(symbol),
            iv=self._fetch_iv(symbol),
            price=self._fetch_price(symbol),
        )
    
    def _fetch_iv(self, symbol: str) -> float:
        """Gibt implied volatility zurück (cached für 1h)"""
        if symbol in self.options_chain_cache:
            cached = self.options_chain_cache[symbol]
            if cached['timestamp'] > time.time() - self.cache_ttl:
                return cached['iv']
        
        # Fetch from Alpaca options data
        iv = self._query_alpaca_options(symbol)
        self.options_chain_cache[symbol] = {
            'iv': iv,
            'timestamp': time.time()
        }
        return iv
```

**Daten-Struktur:**
```python
@dataclass
class MarketData:
    symbol: str
    hourly_candles: List[Candle]  # 72h zurück
    daily_candles: List[Candle]   # 365 Tage zurück
    iv: float                      # Implied Volatility %
    price: float                   # Current price
    timestamp: datetime
```

---

### 3.3 AnalyticsEngine

**Verantwortlichkeit:** Technische Indikatoren berechnen, Trends erkennen

```python
class AnalyticsEngine:
    def compute_all(self, market_data: Dict[str, MarketData]) -> Dict[str, Analysis]:
        """Für jedes Symbol: Indikatoren + Trend-Signal"""
        results = {}
        for symbol, data in market_data.items():
            results[symbol] = self._analyze_symbol(symbol, data)
        return results
    
    def _analyze_symbol(self, symbol: str, data: MarketData) -> Analysis:
        """Berechnet für 1 Symbol"""
        hourly = self._compute_indicators(data.hourly_candles, tf="1h")
        daily = self._compute_indicators(data.daily_candles, tf="1d")
        
        return Analysis(
            symbol=symbol,
            hourly=hourly,
            daily=daily,
            trend=self._detect_trend(hourly, daily),
            volatility_regime=self._assess_volatility(data.iv),
        )
    
    def _compute_indicators(self, candles: List[Candle], tf: str) -> IndicatorSet:
        """RSI(14), MACD(12,26,9), ATR(14), EMA(20,50,200)"""
        df = self._to_dataframe(candles)
        
        return IndicatorSet(
            rsi_14=self._rsi(df['close'], 14),
            macd=self._macd(df['close']),
            atr_14=self._atr(df['high'], df['low'], df['close']),
            ema_20=self._ema(df['close'], 20),
            ema_50=self._ema(df['close'], 50),
            ema_200=self._ema(df['close'], 200),
            bb_upper=..., bb_lower=...,  # Bollinger Bands
        )
```

**Trend-Detection Logik:**
```python
def _detect_trend(self, hourly: IndicatorSet, daily: IndicatorSet) -> str:
    """
    Returns: "strong_bull", "bull", "neutral", "bear", "strong_bear"
    """
    hourly_signal = self._signal_from_indicators(hourly)  # +1 (bull), 0 (neutral), -1 (bear)
    daily_signal = self._signal_from_indicators(daily)
    
    combined = hourly_signal + (daily_signal * 0.5)  # Hourly 2x weight
    
    if combined >= 1.0:
        return "strong_bull"
    elif combined >= 0.5:
        return "bull"
    # ... etc
```

---

### 3.4 StrategyEngine

**Verantwortlichkeit:** Signale generieren basierend auf Indikatoren, entscheiden welche Strategie

```python
class StrategyEngine:
    def __init__(self):
        self.options_agent = OptionsAgent()  # Reuse existing
    
    def generate_signals(self, indicators: Dict[str, Analysis], 
                        market_data: Dict[str, MarketData]) -> List[Signal]:
        """Generiert Signale für jedes Symbol"""
        signals = []
        
        for symbol, analysis in indicators.items():
            signal = self._decide_strategy(symbol, analysis, market_data[symbol])
            if signal:
                signals.append(signal)
        
        return signals
    
    def _decide_strategy(self, symbol: str, analysis: Analysis, 
                        data: MarketData) -> Optional[Signal]:
        """
        Logik:
        1. Ist hourly stark + daily positiv? → BULL_CALL_SPREAD
        2. Ist hourly schwach + daily positiv? → PROTECTIVE_PUT (für existing stock)
        3. Ist hourly stark + daily negativ? → BEAR_PUT_SPREAD
        4. Ist hourly schwach + daily negativ? → STAY_OUT
        """
        
        hourly_trend = analysis.hourly_signal  # -1, 0, 1
        daily_trend = analysis.daily_signal
        
        if hourly_trend > 0 and daily_trend > 0:
            return self._build_bull_call_spread(symbol, analysis, data)
        elif hourly_trend > 0 and daily_trend < 0:
            return self._build_protective_put(symbol, analysis, data)
        elif hourly_trend < 0 and daily_trend < 0:
            return self._build_bear_put_spread(symbol, analysis, data)
        else:
            return None  # Hold, no signal
    
    def _build_bull_call_spread(self, symbol: str, 
                               analysis: Analysis, 
                               data: MarketData) -> Signal:
        """
        Strategy: Buy ATM Call, Sell OTM Call
        - Lower cost than naked call
        - Capped upside but acceptable
        """
        
        # Use OptionsAgent to get details
        plan = self.options_agent.build_options_plan(
            symbol=symbol,
            trade_plan={"action": "open_position", "direction": "long"},
            synthese_output={"signal": "bullish"},
            signal_output=analysis.to_dict(),
            account_info=self._get_account_info(),
        )
        
        # Extract contracts
        long_call = self._fetch_contract(symbol, "call", delta=0.50, dte_range=(20, 45))
        short_call = self._fetch_contract(symbol, "call", delta=0.20, dte_range=(20, 45))
        
        return Signal(
            symbol=symbol,
            strategy_type="BULL_CALL_SPREAD",
            legs=[
                SignalLeg(type="call", side="BUY", strike=long_call.strike, contracts=1),
                SignalLeg(type="call", side="SELL", strike=short_call.strike, contracts=1),
            ],
            max_risk=abs(long_call.bid - short_call.ask) * 100,  # Per spread
            target_profit=abs(long_call.bid - short_call.ask) * 100 * 0.33,
            dte_target=30,
            reason=f"Hourly {analysis.hourly_trend} + Daily {analysis.daily_trend}",
        )
```

**Supported Strategien:**
1. **BULL_CALL_SPREAD** — Buy ATM Call, Sell OTM Call (bullish, capped risk)
2. **BEAR_PUT_SPREAD** — Sell ATM Put, Buy OTM Put (bearish, capped risk)
3. **PROTECTIVE_PUT** — Buy Put für existing stock (hedging)
4. **DIRECTIONAL_CALL** — Single Call (bullish, unlimited upside)
5. **DIRECTIONAL_PUT** — Single Put (bearish, unlimited downside protection)
6. **STRADDLE** — Buy Call + Put (neutral, bet on volatility)

---

### 3.5 RiskManager

**Verantwortlichkeit:** Greeks validieren, Portfolio-Limits durchsetzen, Stop-Loss/Take-Profit prüfen

```python
class RiskManager:
    PORTFOLIO_LIMITS = {
        "max_delta": 0.30,           # ±30% directional exposure
        "max_single_delta": 0.20,    # Max 20% per position
        "max_theta_bleed": 500,      # Max $500/day time decay loss
        "max_gamma": 0.10,           # Vega risk limit
        "max_positions": 5,          # Concurrent option positions
        "min_dte": 14,               # No expirations < 14 days
        "max_cost_per_trade": 0.02,  # 2% of capital per trade
    }
    
    def validate(self, signals: List[Signal], 
                current_positions: Dict) -> List[Signal]:
        """Filteriert Signale basierend auf Risk Constraints"""
        
        valid_signals = []
        
        for signal in signals:
            # 1. Greeks check
            greeks = self._calculate_greeks(signal)
            if not self._check_greeks_limits(greeks):
                logger.warning(f"[RiskManager] {signal.symbol}: Greeks limits exceeded")
                continue
            
            # 2. Portfolio impact check
            if not self._check_portfolio_impact(signal, current_positions):
                logger.warning(f"[RiskManager] {signal.symbol}: Would exceed portfolio delta")
                continue
            
            # 3. Cost check
            cost = self._estimate_cost(signal)
            if cost > self.PORTFOLIO_LIMITS["max_cost_per_trade"] * self._get_account_value():
                logger.warning(f"[RiskManager] {signal.symbol}: Too expensive ({cost})")
                continue
            
            # 4. Stop-Loss/Take-Profit validation
            if not signal.stop_loss or not signal.take_profit:
                signal.stop_loss = self._calculate_stop_loss(signal)
                signal.take_profit = self._calculate_take_profit(signal)
            
            valid_signals.append(signal)
        
        return valid_signals
    
    def _calculate_greeks(self, signal: Signal) -> Greeks:
        """Berechnet Delta/Gamma/Theta/Vega für die Strategie"""
        total_delta = 0
        total_gamma = 0
        total_theta = 0
        total_vega = 0
        
        for leg in signal.legs:
            contract_greeks = self._greeks_for_contract(leg)
            
            multiplier = 100  # Standard: 1 contract = 100 shares
            side_multiplier = 1 if leg.side == "BUY" else -1
            
            total_delta += contract_greeks.delta * multiplier * side_multiplier
            total_gamma += contract_greeks.gamma * multiplier * side_multiplier
            total_theta += contract_greeks.theta * multiplier * side_multiplier
            total_vega += contract_greeks.vega * multiplier * side_multiplier
        
        return Greeks(delta=total_delta, gamma=total_gamma, 
                     theta=total_theta, vega=total_vega)
    
    def _check_greeks_limits(self, greeks: Greeks) -> bool:
        """Prüft einzelne Position gegen Limits"""
        return (
            abs(greeks.delta) <= self.PORTFOLIO_LIMITS["max_single_delta"] and
            abs(greeks.gamma) <= self.PORTFOLIO_LIMITS["max_gamma"]
        )
    
    def _check_portfolio_impact(self, signal: Signal, 
                               current_positions: Dict) -> bool:
        """Prüft: würde neue Position das Portfolio-Delta überschreiten?"""
        new_greeks = self._calculate_greeks(signal)
        portfolio_delta = self._sum_portfolio_delta(current_positions)
        
        new_total_delta = portfolio_delta + new_greeks.delta
        
        return abs(new_total_delta) <= self.PORTFOLIO_LIMITS["max_delta"]
```

**Greeks Reference:**
- **Delta** (Δ): Richtungsrisiko pro $1 Preisbewegung (0-1 für Calls, 0 zu -1 für Puts)
- **Gamma** (Γ): Wie schnell Delta sich ändert
- **Theta** (Θ): Täglicher Zeitverfall (negativ für Käufer, positiv für Verkäufer)
- **Vega** (ν): Sensitivität gegenüber IV Änderungen

---

### 3.6 ExecutionEngine

**Verantwortlichkeit:** Validated Signals → Alpaca Orders

```python
class ExecutionEngine:
    def execute_signals(self, signals: List[Signal]) -> List[ExecutionResult]:
        """Platziert Orders für alle validierten Signale"""
        results = []
        
        for signal in signals:
            try:
                result = self._execute_signal(signal)
                results.append(result)
            except Exception as e:
                logger.error(f"[Executor] {signal.symbol}: {e}")
                results.append(ExecutionResult(
                    signal=signal,
                    status="FAILED",
                    error=str(e),
                ))
        
        return results
    
    def _execute_signal(self, signal: Signal) -> ExecutionResult:
        """Platziert alle Legs einer Strategie"""
        
        order_ids = []
        
        for leg in signal.legs:
            order = self._build_order(signal, leg)
            
            # Place via Alpaca API
            response = self.alpaca_client.submit_order(order)
            order_ids.append(response.id)
            
            logger.info(f"[Executor] {signal.symbol} {leg.side} {leg.type}: "
                       f"Order {response.id} placed")
        
        # Save to database
        self._save_execution(signal, order_ids)
        
        return ExecutionResult(
            signal=signal,
            status="EXECUTED",
            order_ids=order_ids,
        )
    
    def _build_order(self, signal: Signal, leg: SignalLeg) -> Order:
        """Konstruiert Alpaca Order basierend auf Signal-Leg"""
        # OCC Symbol: AAPL260517C00200000
        occ_symbol = self._build_occ_symbol(
            underlying=signal.symbol,
            expiry=signal.expiry_date,
            option_type=leg.type,
            strike=leg.strike,
        )
        
        return Order(
            symbol=occ_symbol,
            qty=leg.contracts,
            side=leg.side.upper(),  # BUY or SELL
            order_type="limit",  # Use limit for options
            time_in_force="day",
            limit_price=self._estimate_option_price(occ_symbol),
        )
```

---

## 4. Data Flow Beispiel

### Beispiel-Szenario (11:00 UTC)

```
11:00 UTC - Hourly Cycle startet

1. DataFetcher.fetch_all_symbols(['AAPL', 'TSLA', 'GOOGL', ...])
   → Returns:
     {
       'AAPL': {
         hourly_candles: [...last 72h 1h-candles],
         daily_candles: [...last 365d],
         iv: 0.24,
         price: 185.50,
       },
       ...
     }

2. AnalyticsEngine.compute_all(market_data)
   → Returns:
     {
       'AAPL': {
         hourly: {
           rsi_14: 65,
           macd: {"value": 1.2, "signal": 0.8, "hist": 0.4},
           atr_14: 2.3,
           ema_20: 184.0,
           ema_50: 183.5,
           ema_200: 180.0,
         },
         daily: {
           rsi_14: 55,
           macd: {"value": 2.1, "signal": 1.9, "hist": 0.2},
           ...
         },
         trend: "strong_bull",  # Hourly bullish + daily bullish
       },
       ...
     }

3. StrategyEngine.generate_signals(indicators, market_data)
   → For AAPL: trend="strong_bull"
     → Decision: Build BULL_CALL_SPREAD
   → Returns:
     {
       symbol: 'AAPL',
       strategy_type: 'BULL_CALL_SPREAD',
       legs: [
         {side: 'BUY', type: 'call', strike: 185.0, contracts: 1},
         {side: 'SELL', type: 'call', strike: 187.0, contracts: 1},
       ],
       max_risk: $150,
       target_profit: $50,
     }

4. RiskManager.validate([AAPL_signal, TSLA_signal, ...])
   → Prüft: 
     - Greeks innerhalb Limits? ✓
     - Portfolio-Delta ok? ✓
     - Cost < 2% capital? ✓
   → Returns: [AAPL_signal_validated, ...]

5. ExecutionEngine.execute_signals(validated_signals)
   → For AAPL:
     - Place BUY order: AAPL260517C00185000 1 contract @ $2.50
     - Place SELL order: AAPL260517C00187000 1 contract @ $1.20
   → Net cost: ($2.50 - $1.20) * 100 = $130
   → Saves to database

11:05 UTC - Cycle complete
Logging: "Executed 3 signals, skipped 2 (Greeks limits)"
```

---

## 5. Integration mit Bestehenden System

### 5.1 Compatibility

- **PositionMonitor.py** bleibt unverändert, wird aber von TradingOrchestrator genutzt
- **OptionsPositionMonitor** wird stündlich gesynct (existing, nur versch. Interval)
- **DEF_OPTIONS_AGENT.py** wird von StrategyEngine reused
- **api_server.py** erweitert um neue Endpoints (kein Breaking Change)

### 5.2 Database Schema (erweitert)

```sql
-- Bestehende tables:
-- positions, orders, options_positions

-- Neue tables für Orchestrator:
CREATE TABLE hourly_signals (
  id INTEGER PRIMARY KEY,
  symbol TEXT,
  strategy_type TEXT,
  trend TEXT,
  greeks_delta REAL,
  greeks_gamma REAL,
  created_at TIMESTAMP,
  status TEXT  -- GENERATED, VALIDATED, EXECUTED, REJECTED
);

CREATE TABLE executed_strategies (
  id INTEGER PRIMARY KEY,
  signal_id INTEGER REFERENCES hourly_signals,
  order_ids TEXT,  -- JSON array
  entry_time TIMESTAMP,
  exit_time TIMESTAMP,
  pnl REAL,
  status TEXT
);
```

---

## 6. Risk Management Framework (Details)

### 6.1 Position-Level Limits

```
Per einzelne Position:
  - Max Risk: $500 (per spread)
  - Min DTE: 14 days
  - Max DTE: 60 days (theta decay zu schnell)
  - Single Delta: ±0.20
  - Cost: ≤ $500 (2% of $25k account)
```

### 6.2 Portfolio-Level Limits

```
Gesamtes Portfolio:
  - Max Portfolio Delta: ±0.30
    → Bedeutet: max 30% der Kapitalgewichtung in Richtungswetten
    → Oder: max $7,500 of $25k "on the line"
    
  - Max Theta Bleed: $500/day
    → Bedeutet: wir können max $500 pro Tag durch Zeitverfall verlieren
    
  - Max Concurrent Positions: 5 Option-Strategien
  
  - Max Gamma: 0.10
    → Bedeutet: wenn Stock um $1 bewegt, Delta ändert sich max um 0.10
    → Schützt vor "Gamma squeeze"
```

### 6.3 Stop-Loss & Take-Profit (Auto-Management)

```python
Signal has auto-generated S/L and T/P:
  BULL_CALL_SPREAD:
    Stop-Loss: -100% of max_risk (close if we lose $150)
    Take-Profit: 33% of max_risk (close when we earn $50)
    Time-Based Exit: Close if 80% of DTE expired with <50% of profit
```

---

## 7. Implementation Roadmap

### Phase 1: Fundament (Week 1)
- [ ] `data_fetcher.py` — Hourly/Daily candles + IV fetching
- [ ] `analytics_engine.py` — RSI/MACD/ATR + Trend detection
- [ ] Unit Tests für Indikatoren

### Phase 2: Signal-Generierung (Week 2)
- [ ] `strategy_engine.py` — Bull/Bear Spreads, Directional Calls/Puts
- [ ] `risk_manager.py` — Greeks calculation, Portfolio limits
- [ ] Integration mit existing OptionsAgent

### Phase 3: Automation (Week 3)
- [ ] `trading_orchestrator.py` — Scheduler, Orchestration
- [ ] ExecutionEngine — Order placement via Alpaca
- [ ] Database schema + API endpoints
- [ ] Testing auf Linux server

### Phase 4: Deployment (Week 4)
- [ ] Deploy auf Linux server (87.106.167.252)
- [ ] monitoring & Logging
- [ ] Live Trading in Paper Mode (mindestens 2 Wochen)
- [ ] Then: real money (optional, nach Approval)

---

## 8. Testing & Validation

### Unit Tests
- AnalyticsEngine: RSI/MACD/ATR Berechnung vs. known values
- StrategyEngine: Signal-Generierung mit Mock-Daten
- RiskManager: Greeks validation, Portfolio limits

### Integration Tests
- Full cycle mit Mock Alpaca API
- Order placement & confirmation
- Database persistence

### Acceptance Tests
- Live Paper Trading (2 weeks)
- Verify: 80%+ signals executed, Greeks within limits, daily logs complete

---

## 9. Open Questions & Entscheidungen

1. **Welche TOP-N Symbole?** Aktuell: TOP 5 (AAPL, MSFT, TSLA, GOOGL, NVDA) + dynamisch?
2. **IV Threshold für Straddles?** Min IV Rank > 20?
3. **News-Sentiment integrieren?** (Optional, für Spike-Trading)
4. **Profit-Taking Aggressivität?** 33% der max_risk oder flexibel?

---

## 10. Success Metrics (Post-Launch)

```
Weekly Review:
  - Total signals generated vs. executed (target: >80%)
  - Average Greeks compliance (target: 100%)
  - Average P&L per signal (target: +10-20%)
  - Max drawdown (target: <5% of capital)
  - Win rate (target: >55%)
```

---

**END OF DESIGN DOCUMENT**

Version: 1.0  
Author: AI Trading Bot Architect  
Date: 2026-04-30
