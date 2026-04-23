"""
TRAIN_MODEL.py

Lädt historische Daten via yfinance und trainiert das universelle XGBoost-Modell (V2).
Neu: VIX + SPY + Sektor-ETF als Markt-Kontext-Features.

Nutzung:
  python TRAIN_MODEL.py
  python TRAIN_MODEL.py --period 5y --forward_days 5 --min_return 0.01
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Dict, List, Any, Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("TrainModel")

# ── Symbol-Listen ─────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS: List[str] = [
    # US Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "AMD", "INTC", "ORCL", "CRM", "ADBE", "AVGO", "QCOM",
    # Comm Services
    "NFLX", "DIS", "CMCSA",
    # Financials
    "JPM", "BAC", "GS", "V", "MA", "MS", "BLK", "AXP",
    # Energy
    "XOM", "CVX", "COP",
    # Health
    "JNJ", "UNH", "PFE", "ABBV", "TMO", "MRK", "LLY",
    # Consumer
    "WMT", "KO", "PEP", "COST", "PG", "HD", "MCD", "NKE",
    # Industrials
    "CAT", "BA", "HON", "UPS",
    # Broad ETFs
    "SPY", "QQQ", "IWM",
    # Sektor-ETFs (auch als Trainingsdaten)
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLC", "XLI",
    # EU
    "SAP", "ASML", "SIE.DE", "ALV.DE",
]

# Alle Sektor-ETFs die als Kontext gebraucht werden
_CONTEXT_SECTOR_ETFS: List[str] = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLC", "XLI",
]


# ── Daten laden ───────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, period: str, interval: str) -> List[Dict[str, Any]]:
    """Lädt OHLCV-Candles via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance fehlt: pip install yfinance")

    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if df is None or df.empty:
        return []

    df = df.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else "Date"
    candles = []
    for _, row in df.iterrows():
        try:
            ts_str = row[ts_col].isoformat()
        except Exception:
            ts_str = str(row[ts_col])
        candles.append({
            "timestamp": ts_str,
            "open":   float(row["Open"]),
            "high":   float(row["High"]),
            "low":    float(row["Low"]),
            "close":  float(row["Close"]),
            "volume": float(row.get("Volume", 0)),
        })
    return candles


def _fetch_market_contexts(
    period: str, interval: str
) -> Dict[str, "pd.DataFrame"]:
    """
    Lädt VIX + SPY + alle Sektor-ETFs und baut market_ctx DataFrames.
    Gibt {sector_etf: ctx_df} zurück, inkl. "SPY" als Fallback.
    """
    from DEF_ML_SIGNAL import _build_market_ctx

    logger.info("Lade Markt-Kontext: ^VIX, SPY + %d Sektor-ETFs …", len(_CONTEXT_SECTOR_ETFS))

    vix_candles = _fetch_candles("^VIX", period=period, interval=interval)
    spy_candles = _fetch_candles("SPY",  period=period, interval=interval)

    if not vix_candles:
        logger.warning("^VIX konnte nicht geladen werden – Kontext-Features fehlen.")
    if not spy_candles:
        logger.warning("SPY konnte nicht geladen werden – Kontext-Features fehlen.")

    ctxs: Dict[str, pd.DataFrame] = {}

    # Basis-Kontext (kein spezifischer Sektor)
    ctxs["SPY"] = _build_market_ctx(vix_candles, spy_candles, None)

    # Sektor-spezifische Kontexte
    for etf in _CONTEXT_SECTOR_ETFS:
        sec_candles = _fetch_candles(etf, period=period, interval=interval)
        if sec_candles:
            ctxs[etf] = _build_market_ctx(vix_candles, spy_candles, sec_candles)
            logger.info("  Kontext %-6s  %d Tage", etf, len(sec_candles))
        else:
            ctxs[etf] = ctxs["SPY"]
            logger.warning("  Kontext %-6s  nicht geladen – nutze SPY", etf)

    return ctxs


# ── Haupt-Training ────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Trainiert das universelle XGBoost-Handelsmodell V2.")
    parser.add_argument("--symbols",      nargs="*", default=None)
    parser.add_argument("--period",       default="5y")
    parser.add_argument("--interval",     default="1d")
    parser.add_argument("--forward_days", type=int,   default=5)
    parser.add_argument("--min_return",   type=float, default=0.01)
    parser.add_argument("--model_name",   default="universal")
    args = parser.parse_args(argv)

    symbols = args.symbols if args.symbols else DEFAULT_SYMBOLS
    logger.info("Lade %d Symbole (%s, %s) …", len(symbols), args.period, args.interval)

    # ── Symbol-Daten laden ────────────────────────────────────────────────────
    symbols_candles: Dict[str, List[Dict[str, Any]]] = {}
    for sym in symbols:
        candles = _fetch_candles(sym, period=args.period, interval=args.interval)
        if candles:
            symbols_candles[sym] = candles
            logger.info("  %-12s  %d Candles", sym, len(candles))
        else:
            logger.warning("  %-12s  übersprungen", sym)

    if not symbols_candles:
        logger.error("Keine nutzbaren Daten – Training abgebrochen.")
        sys.exit(1)

    # ── Markt-Kontext laden ───────────────────────────────────────────────────
    market_ctx_by_sector = _fetch_market_contexts(args.period, args.interval)

    # ── Training ──────────────────────────────────────────────────────────────
    from DEF_ML_SIGNAL import MLSignalEngine

    engine = MLSignalEngine()
    logger.info(
        "Starte Training V2: %d Symbole, forward_days=%d, min_return=%.3f",
        len(symbols_candles), args.forward_days, args.min_return,
    )

    try:
        metrics = engine.train(
            symbols_candles=symbols_candles,
            market_ctx_by_sector=market_ctx_by_sector,
            forward_days=args.forward_days,
            min_return=args.min_return,
        )
    except Exception as exc:
        logger.error("Training fehlgeschlagen: %s", exc)
        sys.exit(1)

    # ── Ergebnis ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 57)
    print("  TRAINING V2 ABGESCHLOSSEN")
    print("=" * 57)
    print(f"  Symbole:           {metrics['n_symbols']}")
    print(f"  Samples (gesamt):  {metrics['n_samples']}")
    print(f"  Features:          {metrics['n_features']}")
    print(f"  Horizont:          {metrics['forward_days']} Tage  (min_return={metrics['min_return']:.1%})")
    print(f"  Best Iteration:    {metrics['best_iteration']}")
    print(f"  Test-Accuracy:     {metrics['test_accuracy']:.4f}")
    print(f"  AUC-ROC:           {metrics['auc_roc']:.4f}")
    print(f"  CV-Accuracy:       {metrics['cv_accuracy_mean']:.4f}  ± {metrics['cv_accuracy_std']:.4f}")
    print("\n  Top-Features:")
    for feat, imp in metrics["top_features"][:10]:
        bar = "#" * int(imp * 400)
        print(f"    {feat:<28}  {imp:.4f}  {bar}")
    print("=" * 57)

    engine.save(args.model_name)
    print(f"\n  Gespeichert: models/{args.model_name}_model.joblib\n")


if __name__ == "__main__":
    main()
