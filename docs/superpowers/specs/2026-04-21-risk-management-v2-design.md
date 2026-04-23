# Risk Management V2 Design

**Date:** 2026-04-21

## Components

### 1. Trailing Stop (position_monitor.py)
- New DB columns: `highest_price` (peak since open), `atr_14` (stored at open)
- Background thread updates `highest_price` on each price check
- New stop = `highest_price - TRAILING_STOP_ATR_MULT × atr_14` (default 2.0)
- Breach → close with status `closed_trailing_stop`

### 2. Kelly Criterion (risk.py)
- New function `compute_kelly_size(account_size, buy_prob, rr_ratio, max_risk)`
- Formula: `f = max(0, (p - (1-p)/b) / 2)` — Half-Kelly, floor 0, cap at max_risk
- Used when ML signal available; fallback to fixed % otherwise

### 3. Correlation Filter (DEF_SCANNER_MODE.py + trading_agents_with_gpt.py)
- After trade plan: count open positions in same sector (via _SECTOR_MAP)
- If ≥ MAX_POSITIONS_PER_SECTOR (default 2): add warning, do not block

## Files Changed
- `position_monitor.py` — DB migration + trailing stop logic
- `risk.py` — compute_kelly_size()
- `DEF_SCANNER_MODE.py` — Kelly + correlation warning
- `trading_agents_with_gpt.py` — Kelly integration
- `.env.sample` — TRAILING_STOP_ATR_MULT, MAX_POSITIONS_PER_SECTOR
