"""
DEF_INDICATORS.py

Berechnet technische Indikatoren aus OHLCV-Candles via pandas-ta.
Gibt ein flaches Dict zurück, das direkt in market_data["indicators"] gespeichert wird.

Installation: pip install pandas pandas-ta
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import pandas as pd
    import pandas_ta as ta
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _last(series) -> Optional[float]:
    """Letzter nicht-NaN Wert einer Series, gerundet auf 4 Stellen."""
    if series is None:
        return None
    clean = series.dropna()
    return round(float(clean.iloc[-1]), 4) if len(clean) > 0 else None


def compute_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Berechnet: RSI, MACD, ATR, EMA(20/50/200), Bollinger Bands,
               Volume-Ratio, ADX, Stochastic.

    Args:
        candles: Liste von Dicts mit Schlüsseln open/high/low/close/volume.

    Returns:
        Dict mit rohen Werten + abgeleiteten Signalen.
        Bei Fehler: {"error": "...", "candle_count": N}
    """
    n = len(candles)

    if not _AVAILABLE:
        return {
            "error": "pandas-ta nicht installiert – pip install pandas pandas-ta",
            "candle_count": n,
        }

    if n < 20:
        return {"error": f"zu wenige Candles ({n} < 20)", "candle_count": n}

    try:
        df = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    except Exception as exc:
        return {"error": f"DataFrame-Fehler: {exc}", "candle_count": n}

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]
    result: Dict[str, Any] = {"candle_count": n}

    # ── RSI(14) ───────────────────────────────────────────────────────────────
    rsi_val = _last(ta.rsi(close, length=14))
    result["rsi_14"] = rsi_val
    if rsi_val is not None:
        result["rsi_zone"] = (
            "overbought" if rsi_val >= 70
            else "oversold" if rsi_val <= 30
            else "neutral"
        )

    # ── MACD(12,26,9) ─────────────────────────────────────────────────────────
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        cols = macd_df.columns.tolist()
        macd_v = _last(macd_df[cols[0]])
        macd_s = _last(macd_df[cols[2]])
        result["macd_value"]  = macd_v
        result["macd_signal"] = macd_s
        result["macd_hist"]   = _last(macd_df[cols[1]])
        if macd_v is not None and macd_s is not None:
            result["macd_cross"] = (
                "bullish" if macd_v > macd_s
                else "bearish" if macd_v < macd_s
                else "neutral"
            )

    # ── ATR(14) ───────────────────────────────────────────────────────────────
    atr_val   = _last(ta.atr(high, low, close, length=14))
    last_close = _last(close)
    result["atr_14"]    = atr_val
    result["last_close"] = last_close
    if atr_val and last_close:
        result["atr_pct"] = round(atr_val / last_close * 100, 3)

    # ── EMAs (20 / 50 / 200) ─────────────────────────────────────────────────
    for p in (20, 50, 200):
        result[f"ema_{p}"] = _last(ta.ema(close, length=p)) if n >= p else None

    e20, e50, e200 = result.get("ema_20"), result.get("ema_50"), result.get("ema_200")
    if e20 and e50:
        if e20 > e50:
            result["ema_trend"] = "bullish" if (e200 is None or e50 > e200) else "mixed_bullish"
        else:
            result["ema_trend"] = "bearish" if (e200 is None or e50 < e200) else "mixed_bearish"
    if last_close and e20:
        result["price_vs_ema20_pct"] = round((last_close - e20) / e20 * 100, 3)

    # ── Bollinger Bands(20, 2) ────────────────────────────────────────────────
    bb = ta.bbands(close, length=20, std=2)
    if bb is not None and not bb.empty:
        cols = bb.columns.tolist()
        result["bb_lower"]     = _last(bb[cols[0]])
        result["bb_mid"]       = _last(bb[cols[1]])
        result["bb_upper"]     = _last(bb[cols[2]])
        result["bb_bandwidth"] = _last(bb[cols[3]])
        result["bb_pct"]       = _last(bb[cols[4]])  # 0=unteres Band, 1=oberes Band

    # ── Volume-Ratio (aktuell vs. MA20) ──────────────────────────────────────
    vol_ma = _last(ta.sma(vol, length=20))
    last_vol = float(vol.iloc[-1]) if len(vol) > 0 else None
    if vol_ma and last_vol and vol_ma > 0:
        result["volume_ratio"] = round(last_vol / vol_ma, 3)

    # ── ADX(14) – Trendstärke ────────────────────────────────────────────────
    adx_df = ta.adx(high, low, close, length=14)
    if adx_df is not None and not adx_df.empty:
        adx_val = _last(adx_df[adx_df.columns[0]])
        result["adx"] = adx_val
        if adx_val is not None:
            result["adx_strength"] = "strong" if adx_val > 25 else "weak"

    # ── Stochastic(14, 3, 3) ─────────────────────────────────────────────────
    stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
    if stoch is not None and not stoch.empty:
        cols = stoch.columns.tolist()
        sk = _last(stoch[cols[0]])
        sd = _last(stoch[cols[1]])
        result["stoch_k"] = sk
        result["stoch_d"] = sd
        if sk is not None and sd is not None:
            if sk >= 80:
                result["stoch_signal"] = "overbought"
            elif sk <= 20:
                result["stoch_signal"] = "oversold"
            elif sk > sd:
                result["stoch_signal"] = "bullish"
            elif sk < sd:
                result["stoch_signal"] = "bearish"
            else:
                result["stoch_signal"] = "neutral"

    return result


# ── VIX Helper (für adaptive Trailing Stops) ──────────────────────────────────

def get_vix_level(vix_value: Optional[float] = None) -> float:
    """
    Fetches VIX level (or uses provided value) for adaptive ATR multipliers.
    Falls back to yfinance if no value provided.
    Returns: VIX value (default 20 if fetch fails)
    """
    if vix_value is not None:
        return float(vix_value)

    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX").history(period="1d")
        if not vix.empty:
            return float(vix["Close"].iloc[-1])
    except Exception:
        pass

    return 20.0  # Neutral fallback


def get_adaptive_atr_multiplier(vix_value: float) -> float:
    """
    Adapts ATR multiplier for trailing stops based on VIX level.
    Returns: ATR multiplier (1.5 to 3.0)
    """
    vix = float(vix_value)
    if vix < 15:
        return 1.5
    elif vix < 20:
        return 2.0
    elif vix < 30:
        return 2.5
    else:
        return 3.0


# ── Correlation Helper ───────────────────────────────────────────────────────

def calculate_symbol_correlation(symbol_a: str, symbol_b: str, period: str = "60d") -> Optional[float]:
    """
    Calculates Pearson correlation between two symbols over period.
    Args:
        symbol_a, symbol_b: Ticker symbols (e.g., "AAPL", "MSFT")
        period: yfinance period (default "60d" for 60 days)
    Returns:
        Correlation coefficient (-1 to 1) or None if calc fails
    """
    try:
        import yfinance as yf
        import pandas as pd

        df_a = yf.download(symbol_a, period=period, progress=False)["Close"]
        df_b = yf.download(symbol_b, period=period, progress=False)["Close"]

        # Align dates
        df_a = df_a.pct_change().dropna()
        df_b = df_b.pct_change().dropna()

        # Align indices
        common_idx = df_a.index.intersection(df_b.index)
        if len(common_idx) < 20:  # Need enough data points
            return None

        corr = df_a[common_idx].corr(df_b[common_idx])
        return float(corr) if pd.notna(corr) else None

    except Exception:
        return None
