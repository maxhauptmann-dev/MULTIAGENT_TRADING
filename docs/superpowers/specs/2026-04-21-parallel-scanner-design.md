# Parallel Scanner Design

**Date:** 2026-04-21

## Goal

Process multiple symbols concurrently in `run_scanner_mode()` to reduce scan time from ~10 min (20 symbols sequential) to ~2–3 min.

## Architecture

Extract per-symbol logic from the `for` loop into a private `_process_symbol()` function. Replace the loop with `ThreadPoolExecutor(max_workers=N)` where N defaults to 4 and is configurable via `SCANNER_MAX_WORKERS` env var.

## Thread Safety

| Component | Issue | Fix |
|-----------|-------|-----|
| GPT semaphore | none — already thread-safe | no change |
| CircuitBreaker (risk.py) | `n_errors`/`n_losses` counters not locked | add `threading.Lock` |
| PositionMonitor SQLite | `check_same_thread` default is True | pass `check_same_thread=False` to sqlite3.connect |

## Files Changed

- `DEF_SCANNER_MODE.py` — extract `_process_symbol()`, add ThreadPoolExecutor loop, read `SCANNER_MAX_WORKERS`
- `risk.py` — add `threading.Lock` to CircuitBreaker
- `position_monitor.py` — `check_same_thread=False`
- `.env.sample` — add `SCANNER_MAX_WORKERS=4`

## Interface Contract

`run_scanner_mode()` return value is unchanged: `{"setups": [...]}`. Callers in `MAIN_USER_AGENT.py` require no changes.

## Concurrency Limit

Default 4 workers. GPT semaphore (3 concurrent calls) acts as an additional back-pressure mechanism, so symbols don't flood the OpenAI API even with more workers.
