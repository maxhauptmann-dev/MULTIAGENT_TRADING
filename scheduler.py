"""
scheduler.py

Automatischer Trading-Daemon:
  - Startet täglich zur Marktöffnung den Scanner
  - Position-Monitor läuft im Hintergrund (SL/TP-Überwachung)
  - Optional: alle Intraday-Positionen vor Börsenschluss flatten

Konfiguration via .env:
  SCHEDULER_MARKETS          US,EU       Kommagetrennt
  SCHEDULER_UNIVERSE         sp500       Universum(en) kommagetrennt
  SCHEDULER_TIMEFRAME        1D
  SCHEDULER_AUTO_EXECUTE     0           1 = echte Orders senden
  SCHEDULER_FLATTEN_INTRADAY 0           1 = Positionen vor Schluss schließen
  ACCOUNT_SIZE               100000
  MAX_RISK_PER_TRADE         0.01
  BROKER_PREFERENCE          ibkr

Starten:
  python scheduler.py
"""

import logging
import os
import signal
import sys
from typing import List

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    print(
        "[scheduler] APScheduler fehlt. Bitte installieren:\n"
        "  pip install apscheduler"
    )
    sys.exit(1)

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("TradingScheduler")


# ── Lazy imports (nach load_dotenv, damit .env geladen ist) ───────────────────

def _lazy_imports():
    from DEF_SCANNER_MODE import run_scanner_mode
    from MAIN_USER_AGENT import format_scanner_results
    from universe_manager import manager as universe_manager
    import position_monitor as _pm
    return run_scanner_mode, format_scanner_results, universe_manager, _pm


# ── Config ────────────────────────────────────────────────────────────────────

def _env_list(key: str, default: str) -> List[str]:
    return [x.strip() for x in os.getenv(key, default).split(",") if x.strip()]


MARKETS = _env_list("SCHEDULER_MARKETS", "US")
UNIVERSES = _env_list("SCHEDULER_UNIVERSE", "sp500")
TIMEFRAME = os.getenv("SCHEDULER_TIMEFRAME", "1D")
AUTO_EXECUTE = os.getenv("SCHEDULER_AUTO_EXECUTE", "0") == "1"
FLATTEN_INTRADAY = os.getenv("SCHEDULER_FLATTEN_INTRADAY", "0") == "1"


def _build_account_info() -> dict:
    return {
        "account_size": float(os.getenv("ACCOUNT_SIZE", "100000")),
        "max_risk_per_trade": float(os.getenv("MAX_RISK_PER_TRADE", "0.01")),
        "broker_preference": os.getenv("BROKER_PREFERENCE", "ibkr"),
    }


# ── Job-Funktionen ────────────────────────────────────────────────────────────

def job_scan(market: str) -> None:
    """Läuft zur Marktöffnung: Scanner über konfigurierte Universen."""
    run_scanner_mode, format_scanner_results, universe_manager, _pm = _lazy_imports()

    logger.info("[Job] Scan startet – Markt=%s, Universen=%s", market, UNIVERSES)

    try:
        watchlist = universe_manager.get(*UNIVERSES)
    except Exception as exc:
        logger.error("[Job] Universum laden fehlgeschlagen: %s", exc)
        return

    if not watchlist:
        logger.warning("[Job] Watchlist leer – Scan abgebrochen.")
        return

    account_info = _build_account_info()
    market_hint = "EU" if market == "EU" else "US"

    logger.info("[Job] %d Symbole | auto_execute=%s", len(watchlist), AUTO_EXECUTE)

    try:
        result = run_scanner_mode(
            watchlist=watchlist,
            account_info=account_info,
            timeframe=TIMEFRAME,
            asset_type="stock",
            market_hint=market_hint,
            auto_execute=AUTO_EXECUTE,
        )
        format_scanner_results(result)

        if _pm.monitor:
            s = _pm.monitor.stats()
            logger.info(
                "[Job] Stats nach Scan: offen=%d | P&L=%+.2f | Win-Rate=%s",
                s["open"],
                s["total_pnl"],
                f"{s['win_rate']:.1%}" if s["win_rate"] is not None else "n/a",
            )
    except Exception as exc:
        logger.error("[Job] Scanner-Fehler: %s", exc, exc_info=True)


def job_flatten() -> None:
    """Schließt alle offenen Positionen (vor Börsenschluss)."""
    _, _, _, _pm = _lazy_imports()

    if _pm.monitor is None:
        return

    closed = _pm.monitor.close_all_open(reason="manual")
    if closed:
        logger.info("[Job] Flatten: %d Position(en) geschlossen.", len(closed))
        for r in closed:
            logger.info("  %s P&L=%+.2f", r.get("symbol"), r.get("pnl", 0))
    else:
        logger.info("[Job] Flatten: keine offenen Positionen.")


def job_backtest() -> None:
    """Führt Backtest für konfigurierte Symbole durch (täglich nach Marktschluss)."""
    from BACKTEST import fetch_candles_yfinance, run_backtest, print_report
    from pathlib import Path
    from datetime import datetime

    # Konfigurierte Backtest-Symbole
    backtest_symbols = _env_list("BACKTEST_SYMBOLS", "AAPL,MSFT,GOOGL,NVDA,TSLA")
    account_size = float(os.getenv("ACCOUNT_SIZE", "100000"))
    max_risk = float(os.getenv("MAX_RISK_PER_TRADE", "0.01"))

    logger.info("[Job] Backtest startet für: %s", ", ".join(backtest_symbols))

    # Logs-Verzeichnis erstellen
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_file = logs_dir / f"backtest_{timestamp}.txt"

    with open(report_file, "w") as f:
        f.write(f"Backtest Report – {datetime.utcnow().isoformat()}\n")
        f.write(f"Account Size: €{account_size:,.2f} | Max Risk/Trade: {max_risk:.1%}\n")
        f.write("=" * 60 + "\n\n")

        for symbol in backtest_symbols:
            try:
                logger.info("[Backtest] Lade Daten für %s...", symbol)
                candles = fetch_candles_yfinance(symbol, period="2y")

                result = run_backtest(
                    candles,
                    account_size=account_size,
                    max_risk_per_trade=max_risk,
                    atr_stop_mult=2.0,
                    atr_tp_mult=3.0,
                )

                if "error" in result:
                    msg = f"[Backtest] {symbol}: {result['error']}"
                    logger.warning(msg)
                    f.write(f"\n{symbol}: ERROR – {result['error']}\n")
                else:
                    s = result["stats"]
                    logger.info(
                        "[Backtest] %s: %d trades, %.1f%% win, %+.2f%% return, %.2f Sharpe",
                        symbol, s["total_trades"], s["win_rate"] * 100,
                        s["total_return_pct"], s["sharpe_ratio"]
                    )

                    f.write(f"\n{symbol}:\n")
                    f.write(f"  Trades: {s['total_trades']} | Win Rate: {s['win_rate']:.1%}\n")
                    f.write(f"  Return: {s['total_return_pct']:+.2f}% | Final Equity: €{s['final_equity']:,.2f}\n")
                    f.write(f"  Profit Factor: {s['profit_factor']} | Sharpe: {s['sharpe_ratio']:.3f}\n")
                    f.write(f"  Max Drawdown: {s['max_drawdown_pct']:.2f}% | Avg Win: €{s['avg_win']:.2f}\n")

            except Exception as exc:
                logger.error("[Backtest] %s Fehler: %s", symbol, exc, exc_info=False)
                f.write(f"\n{symbol}: EXCEPTION – {exc}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write(f"Report gespeichert: {report_file.name}\n")

    logger.info("[Job] Backtest abgeschlossen. Report: %s", report_file)


# ── TradingScheduler ──────────────────────────────────────────────────────────

class TradingScheduler:
    def __init__(self) -> None:
        self._sched = BlockingScheduler(timezone="UTC")
        self._register_jobs()

    def _register_jobs(self) -> None:
        if "US" in MARKETS:
            self._sched.add_job(
                lambda: job_scan("US"),
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour=9, minute=31,
                    timezone="America/New_York",
                ),
                id="us_open_scan",
                name="US Marktöffnung Scan",
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info("Job: US Scan @ 09:31 ET (Mo-Fr)")

            if FLATTEN_INTRADAY:
                self._sched.add_job(
                    job_flatten,
                    trigger=CronTrigger(
                        day_of_week="mon-fri",
                        hour=15, minute=55,
                        timezone="America/New_York",
                    ),
                    id="us_flatten",
                    name="US Positionen flatten",
                    replace_existing=True,
                    misfire_grace_time=120,
                )
                logger.info("Job: US Flatten @ 15:55 ET")

        if "EU" in MARKETS:
            self._sched.add_job(
                lambda: job_scan("EU"),
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour=9, minute=1,
                    timezone="Europe/Berlin",
                ),
                id="eu_open_scan",
                name="EU Marktöffnung Scan",
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info("Job: EU Scan @ 09:01 CET (Mo-Fr)")

            if FLATTEN_INTRADAY:
                self._sched.add_job(
                    job_flatten,
                    trigger=CronTrigger(
                        day_of_week="mon-fri",
                        hour=17, minute=25,
                        timezone="Europe/Berlin",
                    ),
                    id="eu_flatten",
                    name="EU Positionen flatten",
                    replace_existing=True,
                    misfire_grace_time=120,
                )
                logger.info("Job: EU Flatten @ 17:25 CET")

        # Backtest-Job (täglich nach Marktschluss)
        backtest_enabled = os.getenv("BACKTEST_ENABLED", "1") == "1"
        if backtest_enabled:
            backtest_hour = int(os.getenv("BACKTEST_HOUR", "21"))
            backtest_minute = int(os.getenv("BACKTEST_MINUTE", "0"))
            self._sched.add_job(
                job_backtest,
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour=backtest_hour, minute=backtest_minute,
                    timezone="UTC",
                ),
                id="daily_backtest",
                name="Täglicher Backtest",
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info("Job: Backtest @ %02d:%02d UTC (Mo-Fr)", backtest_hour, backtest_minute)

    def start(self) -> None:
        _, _, _, _pm = _lazy_imports()
        if _pm.monitor:
            _pm.monitor.start()
            logger.info("Position-Monitor gestartet.")

        logger.info(
            "Scheduler läuft. Märkte=%s | Universen=%s | Auto-Execute=%s | Flatten=%s",
            MARKETS, UNIVERSES, AUTO_EXECUTE, FLATTEN_INTRADAY,
        )
        self._sched.start()  # blockiert bis stop()

    def stop(self) -> None:
        logger.info("Beende Scheduler...")
        _, _, _, _pm = _lazy_imports()
        if _pm.monitor:
            _pm.monitor.stop()
        self._sched.shutdown(wait=False)
        logger.info("Scheduler gestoppt.")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main() -> None:
    scheduler = TradingScheduler()

    def _on_signal(signum, _frame):
        logger.info("Signal %d – beende.", signum)
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.stop()


if __name__ == "__main__":
    main()
