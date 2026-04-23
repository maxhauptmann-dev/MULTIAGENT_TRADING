# Risk Management V3 Design — Adaptive & Robust

**Date:** 2026-04-22  
**Status:** Design Phase  
**Scope:** Portfolio drawdown limits, adaptive Kelly, intelligent trailing stops, correlation filtering

---

## 1. Portfolio Risk Limits (Max Daily Drawdown)

### Problem
Current system has no portfolio-level circuit breaker. A losing streak can erode 10%+ of account without any pause.

### Solution: Daily Drawdown Monitor

**Implementation:**
- Track daily high water mark (best equity seen in current day)
- Calculate current drawdown: `(current_equity - daily_hwm) / daily_hwm`
- If drawdown exceeds threshold (e.g., -5%), pause new trades for remainder of day
- Reset daily HWM at market open (9:30 AM ET)

**Configuration:**
```python
PORTFOLIO_MAX_DAILY_DRAWDOWN = 0.05  # 5%
PORTFOLIO_MAX_MONTHLY_DRAWDOWN = 0.15  # 15%
```

**Behavior:**
- At -5% drawdown: Allow only *closing* trades, block new *opening* trades
- At -10% drawdown: Complete halt, also cancel pending orders
- Reset at: Market open or manual reset (command line)

**Storage:** SQLite table `portfolio_metrics` tracking:
- `date` (YYYY-MM-DD)
- `daily_high_water_mark` (REAL)
- `monthly_high_water_mark` (REAL)
- `drawdown_triggered_at` (TIMESTAMP or NULL)
- `status` (open | paused | halted)

---

## 2. Adaptive Kelly Criterion

### Problem
Current Kelly is static: `f = (p - (1-p)/b) / 2`, capped at `max_risk_per_trade`.  
With 56% win rate, this gives small positions. But during winning streaks, could be larger; during drawdowns, should shrink.

### Solution: Dynamic Kelly Fraction

**Formula:**
```
kelly_base = (win_prob - (1 - win_prob) / reward_ratio) / 2
kelly_adjusted = kelly_base * drawdown_factor * streak_factor
kelly_final = min(kelly_adjusted, max_risk_per_trade)
```

**Factors:**

1. **Drawdown Factor** (decay during losses):
   ```
   current_dd = (current_equity - monthly_hwm) / monthly_hwm
   if current_dd < 0:
       dd_factor = max(0.3, 1 + current_dd)  # At -5% DD, multiply by 0.95
   else:
       dd_factor = 1.0
   ```

2. **Streak Factor** (increase during wins, cap at 1.5x):
   ```
   recent_wins = count of last 10 closed trades that were profitable
   streak_factor = 1.0 + (recent_wins / 20)  # Max 1.5x at 10/10 wins
   ```

**Capped Ranges:**
- Minimum Kelly: 0.003 (protect against overleverage in downturns)
- Maximum Kelly: min(0.25, base * 1.5) (never risk >25% per trade, max 1.5x multiplier)

**Example Scenarios:**
- Win rate 56%, RR 1.5: base Kelly = 0.065 (6.5%)
  - At -5% monthly DD: 6.5% × 0.95 × 1.0 = **6.18%**
  - During 8/10 win streak: 6.5% × 1.0 × 1.4 = **9.1%**
  - At -10% DD + 2/10 streak: 6.5% × 0.9 × 1.1 = **6.44%** (protected)

**Storage:** Log to positions table:
- `kelly_fraction_used` (REAL) — for post-analysis

---

## 3. Intelligent Trailing Stop

### Problem
Current trailing stop:
- Only Long positions
- Fixed ATR multiplier (2.0)
- Doesn't lock in profits or adapt to volatility regimes

### Solution: Adaptive Trailing with Profit Locks

**For Long Positions:**

1. **Adaptive ATR Multiplier:**
   ```
   atr_14 = current ATR(14)
   vix_level = current VIX level (from market context)
   
   if vix_level < 15:  # Low volatility, tighter stop
       mult = 1.5
   elif vix_level < 20:
       mult = 2.0
   elif vix_level < 30:
       mult = 2.5
   else:  # High volatility, wider stop
       mult = 3.0
   
   trailing_sl = highest_price - (mult * atr_14)
   ```

2. **Profit Lock-In Levels:**
   ```
   profit_pct = (current_price - entry_price) / entry_price
   
   if profit_pct >= 0.05:  # +5% profit
       # Move SL to breakeven (entry_price)
       trailing_sl = max(trailing_sl, entry_price)
   
   if profit_pct >= 0.10:  # +10% profit
       # Move SL to entry + 2% (lock in 2% min profit)
       trailing_sl = max(trailing_sl, entry_price * 1.02)
   
   if profit_pct >= 0.20:  # +20% profit
       # Aggressive: SL at entry + 10%
       trailing_sl = max(trailing_sl, entry_price * 1.10)
   ```

3. **Short Positions (new):**
   ```
   # Mirror logic for shorts
   if vix_level < 15:
       mult = 1.5
   ...
   
   trailing_sl = lowest_price + (mult * atr_14)  # +, not -
   
   # Profit locks
   if profit_pct >= 0.05:
       trailing_sl = min(trailing_sl, entry_price)  # Min, not max
   ...
   ```

**Storage:** Update positions table:
- `atr_multiplier_used` (REAL)
- `profit_locked_at_pct` (REAL or NULL)
- `lowest_price` (REAL) — for shorts

---

## 4. Correlation Filter (Real Correlations)

### Problem
Current approach: `MAX_POSITIONS_PER_SECTOR = 2` (hard cap).  
Better: Measure actual correlation between candidate trade and open positions.

### Solution: Real Correlation Matrix

**On Each Trade Entry Signal:**

1. **Calculate Correlation:**
   ```python
   # Get last 60 days of returns for candidate symbol
   candidate_returns = yfinance(symbol, period="60d").pct_change()
   
   # Get returns for each open position
   for open_pos in positions:
       open_returns = yfinance(open_pos.symbol, period="60d").pct_change()
       correlation = candidate_returns.corr(open_returns)
       
       if correlation > 0.70:  # High correlation threshold
           # Decision tree below
   ```

2. **Decision Tree:**
   ```
   if max_correlation > 0.85:
       action = "REJECT"  # Too similar, skip trade
       reason = f"Correlation {max_correlation:.2f} to {most_correlated_symbol}"
   
   elif max_correlation > 0.70:
       action = "REDUCE_SIZE"  # Reduce position size by 30%
       reduced_qty = proposed_qty * 0.70
       reason = f"Correlation {max_correlation:.2f}, reducing size"
   
   else:  # < 0.70
       action = "ACCEPT"
       reason = f"Low correlation (max {max_correlation:.2f})"
   
   # Also check sector diversity (still keep MAX_POSITIONS_PER_SECTOR as hard cap)
   if positions_in_sector >= MAX_POSITIONS_PER_SECTOR:
       action = "REJECT"
       reason = f"Sector limit hit ({MAX_POSITIONS_PER_SECTOR})"
   ```

3. **Correlation Decay:**
   - Recalculate correlations every 10 trading days (markets evolve)
   - Cache correlations in table `correlation_matrix`:
     - `symbol_a`, `symbol_b`, `correlation`, `calculated_at`

**Storage:** New table `correlation_checks`:
- `trade_id` (FK to positions)
- `candidate_symbol`
- `max_correlation`
- `action` (ACCEPT | REJECT | REDUCE_SIZE)
- `checked_at`

---

## 5. Integration Flow

### New Entry Point: Enhanced `execute_trade_plan()`

```
1. [EXISTING] Validate trade plan
2. [EXISTING] Check if simulation/paper/live
3. [EXISTING] Check paper guard

4. [NEW] Check portfolio drawdown status
   → If halted, reject trade
   → If paused, allow close-only

5. [NEW] Calculate adaptive Kelly size
   → Apply drawdown + streak factors
   → Compare to raw position size, use smaller

6. [NEW] Check correlation with open positions
   → If high correlation, reduce size or reject

7. [EXISTING] Check sector limits
   → Hard cap still applies

8. [NEW] Pre-populate trailing stop params
   → Calculate VIX-adaptive ATR multiplier
   → Set profit lock-in levels

9. [EXISTING] Execute order via broker
10. [NEW] Log all risk decisions to audit table

11. [EXISTING] Open position in monitor + DB
    → Store kelly_fraction_used, atr_multiplier, etc.
```

---

## 6. Data Model Changes

### New Tables

**portfolio_metrics:**
```sql
CREATE TABLE portfolio_metrics (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,  -- YYYY-MM-DD
    daily_high_water_mark REAL,
    monthly_high_water_mark REAL,
    drawdown_status TEXT,  -- open | paused | halted
    drawdown_triggered_at TIMESTAMP,
    status_reset_at TIMESTAMP
);
```

**correlation_matrix:**
```sql
CREATE TABLE correlation_matrix (
    id INTEGER PRIMARY KEY,
    symbol_a TEXT NOT NULL,
    symbol_b TEXT NOT NULL,
    correlation REAL,
    calculated_at TIMESTAMP,
    UNIQUE(symbol_a, symbol_b)
);
```

**risk_audit_log:**
```sql
CREATE TABLE risk_audit_log (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    symbol TEXT,
    decision TEXT,  -- kelly_factor, correlation_reject, drawdown_pause, etc.
    details TEXT,  -- JSON: {kelly_base: 0.065, dd_factor: 0.95, ...}
    outcome TEXT  -- ACCEPT | REJECT | MODIFIED
);
```

### Modified Columns (positions table)

Already exists: `atr_14`, `highest_price`

Add:
- `atr_multiplier_used` REAL
- `kelly_fraction_used` REAL
- `profit_locked_at_pct` REAL
- `lowest_price` REAL (for shorts)
- `correlation_check_json` TEXT (store correlation results at entry)

---

## 7. Files to Modify/Create

1. **risk.py** — Add:
   - `compute_adaptive_kelly_size()` with drawdown + streak factors
   - `PortfolioMetrics` class (daily/monthly HWM tracking)
   - `CorrelationMatrix` helper

2. **position_monitor.py** — Add:
   - Trailing stop logic for shorts
   - Adaptive ATR multiplier (VIX-based)
   - Profit lock-in levels
   - Daily HWM updates

3. **trading_agents_with_gpt.py** — Modify:
   - `execute_trade_plan()` to call risk checks before execution
   - Add correlation filtering step

4. **DEF_INDICATORS.py** (or new file) — Add:
   - `get_vix_level()` helper
   - `calculate_correlation()` helper

5. **scheduler.py** (if exists) — Add:
   - Daily reset logic for portfolio metrics
   - Monthly reset for monthly HWM

---

## 8. Success Criteria

- ✅ Portfolio never drawdowns >5% intraday (or configured limit)
- ✅ Kelly sizes adapt during winning/losing streaks (10-20% variance)
- ✅ Trailing stops tighter in low-vol, wider in high-vol (20%+ variance in mult)
- ✅ Correlated trades rejected or size-reduced (e.g., two Tech stocks not both held)
- ✅ All risk decisions logged for post-trade analysis

---

## 9. Rollout Plan

**Phase 1:** Portfolio drawdown limits + logging (no hard halt, just warn)  
**Phase 2:** Adaptive Kelly + trailing stops (parallel with existing system)  
**Phase 3:** Correlation filtering (test on paper trading first)  
**Phase 4:** Full integration, enable halt behavior

---

## 10. Future (Tier 3)

- Gradueller Circuit Breaker (reduce position size over cooldown, not binary off)
- Multi-leg correlation (sector + market regime + volatility clustering)
- Dynamic max_risk_per_trade based on monthly Sharpe ratio
