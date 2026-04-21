# ML-Modell V2 Design

**Date:** 2026-04-21

## Goal

Improve XGBoost signal accuracy from ~52% to 55%+ by expanding training data volume and adding market-context features (VIX, SPY trend, sector momentum).

## Data

- **Period:** 5y (was 3y) → ~1250 candles/symbol
- **Symbols:** 50+ covering US Large-Cap, sector ETFs (XLK, XLF, XLE, XLV, XLC, XLI, XLY, XLP, XLU, XLRE), EU ADRs
- **Market context:** `^VIX` and SPY fetched once per training run, merged into each symbol's DataFrame by date

Expected sample count: ~60,000 (was 14,700)

## New Features

Added to `_build_feature_df(candles, market_ctx=None)`:

| Feature | Source | Meaning |
|---------|--------|---------|
| `vix_level` | ^VIX close | Absolute fear/greed level |
| `vix_change_5d` | ^VIX pct_change(5) | VIX momentum |
| `spy_ema_ratio` | SPY ema20/ema50 | Market trend direction |
| `spy_vs_ema200_pct` | (SPY - ema200)/ema200 | Bull/bear regime |
| `sector_rel_strength` | sector_etf.pct(5) - spy.pct(5) | Sector rotation signal |
| `rsi_lag10`, `rsi_lag20` | rsi.shift(10/20) | Longer momentum memory |
| `macd_hist_lag10` | macd_hist.shift(10) | Longer MACD memory |
| `vol_ratio_lag10` | vol_ratio.shift(10) | Volume trend memory |

## Architecture

### Training (`TRAIN_MODEL.py`)
1. Fetch `^VIX` and `SPY` for the full period once
2. Build `market_ctx` DataFrame indexed by date with all market-context columns
3. Pass `market_ctx` to `_build_feature_df()` for each symbol
4. Merge on date after feature computation

### Prediction (`MLSignalEngine.predict()`)
1. Fetch last 60 days of `^VIX` and `SPY` via yfinance (cached for 15 min to avoid repeated calls)
2. Build `market_ctx` from those 60 days
3. Pass to `_build_feature_df()` with the symbol's candles

### Sector mapping
Each symbol maps to a sector ETF. Mapping stored as a dict in `DEF_ML_SIGNAL.py`. Unmapped symbols use SPY as proxy.

## Files Changed

- `DEF_ML_SIGNAL.py` — `_build_feature_df()` signature + new features + predict() fetches context
- `TRAIN_MODEL.py` — expanded symbol list, 5y period, market context fetch + pass-through

## Interface Contract

`MLSignalEngine.train()`, `predict()`, `save()`, `load()` signatures unchanged. `_build_feature_df()` gets an optional `market_ctx` parameter — backward compatible (defaults to None, features omitted if None).

## Success Criteria

- AUC-ROC > 0.55 on hold-out test set
- CV accuracy mean > 0.53
- Best iteration > 50 (model learns more before early stopping)
