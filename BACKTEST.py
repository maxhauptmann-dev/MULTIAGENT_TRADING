"""
BACKTEST.py

Historischer Backtest der Indikator-Strategie.

Kein GPT – deterministische, regelbasierte Signale aus denselben
Indikatoren (RSI, MACD, EMA, ATR, ADX) wie im Live-System.

Datenquellen:
  - yfinance (empfohlen, pip install yfinance)
  - oder: vorberechnete Candles-Liste aus DataAgent

Starten:
  python BACKTEST.py

Oder aus einem anderen Modul:
  from BACKTEST import run_backtest, fetch_candles_yfinance
  result = run_backtest(candles, account_size=100_000)
  print_report(result)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from DEF_INDICATORS import _AVAILABLE as _TA_AVAILABLE

# ── Daten-Helper ──────────────────────────────────────────────────────────────

def fetch_candles_yfinance(
    symbol: str,
    period: str = "90d",
    interval: str = "1d",
) -> List[Dict[str, Any]]:
    """
    Lädt historische OHLCV-Daten via yfinance.
    period: "1y", "2y", "5y", "90d" usw. (swing trading: 90d statt 2y)
    interval: "1d", "1h", "15m" usw.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError(
            "yfinance fehlt. Bitte installieren: pip install yfinance"
        )

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        raise RuntimeError(f"Keine Daten für {symbol} von yfinance erhalten.")

    df = df.reset_index()
    date_col = "Datetime" if "Datetime" in df.columns else "Date"

    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": str(row[date_col]),
            "open":   float(row["Open"]),
            "high":   float(row["High"]),
            "low":    float(row["Low"]),
            "close":  float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return candles


# ── Indikator-Berechnung (vektorisiert für Backtest) ──────────────────────────

def _build_indicator_df(candles: List[Dict]) -> pd.DataFrame:
    """
    Baut DataFrame mit allen Indikatoren vektorisiert (einmalig, nicht bar-by-bar).
    """
    if not _TA_AVAILABLE:
        raise RuntimeError("pandas-ta fehlt. Bitte installieren: pip install pandas-ta")

    import pandas_ta as ta

    df = pd.DataFrame(candles)[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    df[["open", "high", "low", "close", "volume"]] = \
        df[["open", "high", "low", "close", "volume"]].astype(float)

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    # RSI(14)
    df["rsi"]        = ta.rsi(close, length=14)

    # MACD(12,26,9)
    macd_df          = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is not None:
        cols          = macd_df.columns.tolist()
        df["macd"]    = macd_df[cols[0]]
        df["macd_sig"]= macd_df[cols[2]]
        df["macd_hist"]= macd_df[cols[1]]

    # ATR(14)
    df["atr"]        = ta.atr(high, low, close, length=14)

    # EMAs
    df["ema20"]      = ta.ema(close, length=20)
    df["ema50"]      = ta.ema(close, length=50)

    # ADX(14)
    adx_df           = ta.adx(high, low, close, length=14)
    if adx_df is not None:
        df["adx"]    = adx_df[adx_df.columns[0]]

    # Volume MA(20)
    df["vol_ma20"]   = ta.sma(vol, length=20)
    df["vol_ratio"]  = vol / df["vol_ma20"]

    # MACD-Cross: +1 = bullish, -1 = bearish, 0 = kein Cross
    if "macd" in df.columns and "macd_sig" in df.columns:
        above          = (df["macd"] > df["macd_sig"]).astype(int)
        df["macd_cross"] = above.diff().fillna(0).astype(int)

    return df.dropna(subset=["rsi", "atr", "ema20", "ema50"]).reset_index(drop=True)


# ── Signal-Generierung ────────────────────────────────────────────────────────

def _generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    LONG-Entry-Bedingungen (alle müssen erfüllt sein):
      1. MACD bullish cross (+1) in dieser oder voriger Bar
      2. RSI zwischen 35 und 65  (nicht überkauft / überverkauft)
      3. EMA20 > EMA50           (Aufwärtstrend bestätigt)
      4. ADX > 20                (trendet, nicht seitwärts)
      5. Volume-Ratio > 1.0      (überdurchschnittliches Volumen)

    EXIT:
      - Stop-Loss:  entry - atr_stop_mult × ATR
      - Take-Profit: entry + atr_tp_mult × ATR
      - ODER: MACD bearish cross (-1)
    """
    # Frische MACD-Cross-Fenster (diese oder vorherige Bar)
    fresh_bull = (df["macd_cross"] == 1) | (df["macd_cross"].shift(1) == 1)

    df["signal"] = 0
    entry_mask = (
        fresh_bull
        & (df["rsi"] >= 35) & (df["rsi"] <= 65)
        & (df["ema20"] > df["ema50"])
        & (df.get("adx", pd.Series([30] * len(df))) > 20)
        & (df["vol_ratio"] > 1.0)
    )
    df.loc[entry_mask, "signal"] = 1
    return df


# ── Bar-by-Bar Simulation ─────────────────────────────────────────────────────

def _simulate(
    df: pd.DataFrame,
    account_size: float,
    max_risk_per_trade: float,
    atr_stop_mult: float,
    atr_tp_mult: float,
    commission_per_share: float,
) -> tuple[List[Dict], List[float]]:
    """
    Simuliert Trades bar-by-bar.
    Returns: (trade_log, equity_curve)
    """
    from risk import compute_position_size

    equity        = account_size
    equity_curve  = [equity]
    trade_log     = []
    in_position   = False
    entry_price   = stop_loss = take_profit = 0.0
    qty           = 0
    entry_bar     = 0
    entry_ts      = ""

    for i, row in df.iterrows():
        price = float(row["close"])

        if in_position:
            # Exit-Bedingungen prüfen (in dieser Reihenfolge: SL → TP → MACD-Exit)
            reason = None
            exit_price = price

            if price <= stop_loss:
                reason     = "stop_loss"
                exit_price = stop_loss  # SL immer exakt

            elif price >= take_profit:
                reason     = "take_profit"
                exit_price = take_profit  # TP immer exakt

            elif row.get("macd_cross", 0) == -1:
                reason     = "macd_exit"

            if reason:
                pnl = (exit_price - entry_price) * qty \
                      - (commission_per_share * qty * 2)
                equity += pnl
                trade_log.append({
                    "entry_ts":    entry_ts,
                    "exit_ts":     str(row["timestamp"]),
                    "entry_price": round(entry_price, 4),
                    "exit_price":  round(exit_price, 4),
                    "qty":         qty,
                    "stop_loss":   round(stop_loss, 4),
                    "take_profit": round(take_profit, 4),
                    "pnl":         round(pnl, 2),
                    "reason":      reason,
                    "bars_held":   i - entry_bar,
                })
                in_position = False

        elif row["signal"] == 1:
            # Entry
            atr = float(row["atr"])
            sl  = price - atr_stop_mult * atr
            tp  = price + atr_tp_mult  * atr

            sizing = compute_position_size(equity, max_risk_per_trade, price, sl)
            qty_new = sizing["qty"]
            if qty_new <= 0:
                equity_curve.append(equity)
                continue

            # Kein Trade wenn Kosten > 0.5% des Risikos
            cost = commission_per_share * qty_new * 2
            if cost > sizing["max_risk_amount"] * 0.5:
                equity_curve.append(equity)
                continue

            in_position  = True
            entry_price  = price
            stop_loss    = sl
            take_profit  = tp
            qty          = qty_new
            entry_bar    = i
            entry_ts     = str(row["timestamp"])

        equity_curve.append(equity)

    # Offene Position am Kursende schließen
    if in_position and len(df) > 0:
        last       = df.iloc[-1]
        exit_price = float(last["close"])
        pnl        = (exit_price - entry_price) * qty \
                     - (commission_per_share * qty * 2)
        equity    += pnl
        trade_log.append({
            "entry_ts":    entry_ts,
            "exit_ts":     str(last["timestamp"]),
            "entry_price": round(entry_price, 4),
            "exit_price":  round(exit_price, 4),
            "qty":         qty,
            "stop_loss":   round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "pnl":         round(pnl, 2),
            "reason":      "end_of_data",
            "bars_held":   len(df) - 1 - entry_bar,
        })
        equity_curve.append(equity)

    return trade_log, equity_curve


# ── Performance-Metriken ──────────────────────────────────────────────────────

def _compute_stats(
    trade_log: List[Dict],
    equity_curve: List[float],
    account_size: float,
) -> Dict[str, Any]:
    if not trade_log:
        return {"error": "Keine Trades simuliert – Strategie hat kein Signal erzeugt."}

    pnls     = [t["pnl"] for t in trade_log]
    wins     = [p for p in pnls if p > 0]
    losses   = [p for p in pnls if p <= 0]
    n        = len(pnls)

    total_return = (equity_curve[-1] - account_size) / account_size * 100
    win_rate     = len(wins) / n if n > 0 else 0
    avg_win      = sum(wins) / len(wins) if wins else 0
    avg_loss     = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
    expectancy   = sum(pnls) / n if n > 0 else 0
    avg_bars     = sum(t["bars_held"] for t in trade_log) / n if n > 0 else 0

    # Max Drawdown
    peak = account_size
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Sharpe Ratio (vereinfacht, tägliche Returns annualisiert)
    eq_series = pd.Series(equity_curve)
    daily_ret = eq_series.pct_change().dropna()
    sharpe = 0.0
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = round(daily_ret.mean() / daily_ret.std() * math.sqrt(252), 3)

    # Reason-Breakdown
    reasons: Dict[str, int] = {}
    for t in trade_log:
        r = t.get("reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1

    return {
        "total_trades":     n,
        "win_rate":         round(win_rate, 3),
        "total_return_pct": round(total_return, 2),
        "final_equity":     round(equity_curve[-1], 2),
        "profit_factor":    round(profit_factor, 3) if profit_factor != float("inf") else "∞",
        "expectancy":       round(expectancy, 2),
        "avg_win":          round(avg_win, 2),
        "avg_loss":         round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio":     sharpe,
        "avg_bars_held":    round(avg_bars, 1),
        "exit_reasons":     reasons,
    }


# ── Haupt-API ─────────────────────────────────────────────────────────────────

def run_backtest(
    candles: List[Dict[str, Any]],
    account_size: float = 100_000.0,
    max_risk_per_trade: float = 0.01,
    atr_stop_mult: float = 2.0,
    atr_tp_mult: float = 3.0,
    commission_per_share: float = 0.01,
) -> Dict[str, Any]:
    """
    Führt einen vollständigen Backtest durch.

    Args:
        candles:              OHLCV-Liste (wie DataAgent.fetch liefert)
        account_size:         Startkapital
        max_risk_per_trade:   Max. Risiko pro Trade (z.B. 0.01 = 1%)
        atr_stop_mult:        Stop-Loss = entry − mult × ATR
        atr_tp_mult:          Take-Profit = entry + mult × ATR
        commission_per_share: Kommission pro Aktie (Round-Trip × 2)

    Returns:
        {stats, trade_log, equity_curve, params}
    """
    if len(candles) < 60:
        return {"error": f"Zu wenige Candles ({len(candles)}), mindestens 60 nötig."}

    df = _build_indicator_df(candles)
    if len(df) < 50:
        return {"error": "Nach Indikator-Berechnung zu wenige Bars übrig."}

    df = _generate_signals(df)

    trade_log, equity_curve = _simulate(
        df, account_size, max_risk_per_trade,
        atr_stop_mult, atr_tp_mult, commission_per_share,
    )

    stats = _compute_stats(trade_log, equity_curve, account_size)

    return {
        "stats":        stats,
        "trade_log":    trade_log,
        "equity_curve": equity_curve,
        "params": {
            "account_size":         account_size,
            "max_risk_per_trade":   max_risk_per_trade,
            "atr_stop_mult":        atr_stop_mult,
            "atr_tp_mult":          atr_tp_mult,
            "commission_per_share": commission_per_share,
            "bars_tested":          len(df),
        },
    }


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(result: Dict[str, Any], symbol: str = "") -> None:
    """Gibt einen formatierten Performance-Report aus."""
    if "error" in result:
        print(f"[Backtest] Fehler: {result['error']}")
        return

    s = result["stats"]
    p = result["params"]
    trades = result["trade_log"]

    print(f"\n{'='*54}")
    print(f"  BACKTEST REPORT{f'  –  {symbol}' if symbol else ''}")
    print(f"{'='*54}")
    print(f"  Startkapital:      {p['account_size']:>12,.0f} €")
    print(f"  Endkapital:        {s['final_equity']:>12,.2f} €")
    print(f"  Gesamt-Return:     {s['total_return_pct']:>+11.2f} %")
    print(f"  Max Drawdown:      {s['max_drawdown_pct']:>11.2f} %")
    print(f"  Sharpe Ratio:      {s['sharpe_ratio']:>12.3f}")
    print(f"{'─'*54}")
    print(f"  Trades gesamt:     {s['total_trades']:>12}")
    print(f"  Win Rate:          {s['win_rate']:>11.1%}")
    print(f"  Profit Factor:     {str(s['profit_factor']):>12}")
    print(f"  Expectancy/Trade:  {s['expectancy']:>+11.2f} €")
    print(f"  Avg Win:           {s['avg_win']:>+11.2f} €")
    print(f"  Avg Loss:          {s['avg_loss']:>+11.2f} €")
    print(f"  Avg Haltedauer:    {s['avg_bars_held']:>10.1f} Bars")
    print(f"{'─'*54}")
    print(f"  Exit-Gründe:")
    for reason, cnt in s["exit_reasons"].items():
        pct = cnt / s["total_trades"] * 100
        print(f"    {reason:<20} {cnt:>4}  ({pct:.0f}%)")
    print(f"{'─'*54}")
    print(f"  Parameter:")
    print(f"    ATR Stop-Mult:   {p['atr_stop_mult']}×  |  ATR TP-Mult: {p['atr_tp_mult']}×")
    print(f"    Max Risk/Trade:  {p['max_risk_per_trade']:.1%}  |  Bars getestet: {p['bars_tested']}")
    print(f"{'='*54}\n")

    if trades:
        print("  Letzte 5 Trades:")
        print(f"  {'Entry':>10}  {'Exit':>10}  {'Entry€':>8}  {'Exit€':>8}  {'P&L':>8}  Grund")
        for t in trades[-5:]:
            entry_date = str(t["entry_ts"])[:10]
            exit_date  = str(t["exit_ts"])[:10]
            print(
                f"  {entry_date:>10}  {exit_date:>10}  "
                f"{t['entry_price']:>8.2f}  {t['exit_price']:>8.2f}  "
                f"{t['pnl']:>+8.2f}  {t['reason']}"
            )
        print()


def plot_equity_curve(result: Dict[str, Any], symbol: str = "") -> None:
    """Zeichnet Equity-Kurve + Drawdown (benötigt matplotlib)."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        print("[Backtest] matplotlib fehlt: pip install matplotlib")
        return

    if "error" in result or not result.get("equity_curve"):
        print("[Backtest] Keine Daten für Chart.")
        return

    eq  = result["equity_curve"]
    acc = result["params"]["account_size"]

    # Drawdown-Serie
    peak = acc
    dd   = []
    for e in eq:
        peak = max(peak, e)
        dd.append((peak - e) / peak * 100)

    fig = plt.figure(figsize=(12, 7))
    gs  = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.05)

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(eq, color="#2196F3", linewidth=1.5, label="Equity")
    ax1.axhline(acc, color="gray", linestyle="--", linewidth=0.8, label="Startkapital")
    ax1.set_ylabel("Kapital (€)")
    ax1.set_title(f"Backtest Equity-Kurve{f'  –  {symbol}' if symbol else ''}")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax1.set_xticklabels([])

    ax2 = fig.add_subplot(gs[1])
    ax2.fill_between(range(len(dd)), dd, color="#F44336", alpha=0.6)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Bars")
    ax2.grid(alpha=0.3)
    ax2.invert_yaxis()

    s = result["stats"]
    fig.text(
        0.99, 0.99,
        f"Return: {s['total_return_pct']:+.1f}%  |  "
        f"MaxDD: {s['max_drawdown_pct']:.1f}%  |  "
        f"Sharpe: {s['sharpe_ratio']:.2f}  |  "
        f"WinRate: {s['win_rate']:.1%}",
        ha="right", va="top", fontsize=9, color="dimgray",
    )

    plt.tight_layout()
    plt.show()


# ── CLI-Modus ─────────────────────────────────────────────────────────────────

def _cli() -> None:
    import os
    print("=== Backtest-Modul ===")
    symbol    = input("Symbol (z.B. AAPL, MSFT) [AAPL]: ").strip().upper() or "AAPL"
    period    = input("Zeitraum (1y/2y/5y) [2y]: ").strip() or "2y"
    acc_raw   = input(f"Startkapital [100000]: ").strip()
    account   = float(acc_raw) if acc_raw else 100_000.0
    risk_raw  = input("Max Risiko/Trade % (z.B. 0.01 = 1%) [0.01]: ").strip()
    risk      = float(risk_raw) if risk_raw else 0.01
    stop_raw  = input("ATR Stop-Multiplikator [2.0]: ").strip()
    atr_stop  = float(stop_raw) if stop_raw else 2.0
    tp_raw    = input("ATR TP-Multiplikator [3.0]: ").strip()
    atr_tp    = float(tp_raw) if tp_raw else 3.0

    print(f"\nLade Daten für {symbol} ({period}) via yfinance...")
    try:
        candles = fetch_candles_yfinance(symbol, period=period)
    except Exception as exc:
        print(f"Fehler beim Laden: {exc}")
        return

    print(f"{len(candles)} Candles geladen. Berechne Indikatoren & simuliere...")
    result = run_backtest(
        candles,
        account_size=account,
        max_risk_per_trade=risk,
        atr_stop_mult=atr_stop,
        atr_tp_mult=atr_tp,
    )

    print_report(result, symbol)

    chart = input("Equity-Kurve anzeigen? [j/N]: ").strip().lower()
    if chart == "j":
        plot_equity_curve(result, symbol)


if __name__ == "__main__":
    _cli()
