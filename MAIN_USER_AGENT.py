# MAIN_USER_AGENT.py

from trading_agents_with_gpt import run_single_symbol_mode
from DEF_SCANNER_MODE import run_scanner_mode
from universe_manager import manager as universe_manager
import position_monitor as _pm_module

def format_single_result(result):
    symbol = result.get("symbol")
    synth = result.get("synthese_output", {})
    signal = result.get("signal_output", {})
    plan = result.get("trade_plan", {})
    news = result.get("news_output", {})
    options_plan = plan.get("options_plan") or {}

    print(f"\n=== EINZELMODUS RESULT FÜR {symbol} ===\n")

    print(f"Bias:        {synth.get('overall_bias')}  (Conf: {synth.get('overall_confidence')})")
    print(f"Signal:      {signal.get('short_term_signal')}  (Conf: {signal.get('confidence')})")
    print(f"Entry-Stil:  {signal.get('entry_style')}\n")

    action = plan.get("action")
    reason = plan.get("reason")

    print("--- TRADE PLAN ---")
    print(f"Aktion:      {action}")
    if isinstance(reason, str):
        print(f"Grund:       {reason}\n")
    else:
        print("Grund:       (keine Begründung geliefert)\n")

    # --------------------------------------
    # Wenn KEINE Position eröffnet wird
    # --------------------------------------
    if action != "open_position":
        print("Es wird KEINE Position eröffnet (no_trade).")

        print("\nWichtige Gründe:")
        for r in synth.get("key_reasons", [])[:5]:
            print(" -", r)

        print("\nRisiko-Hinweise:")
        for r in synth.get("risk_notes", [])[:5]:
            print(" -", r)

        print("\n📰 News-Überblick:")
        overall_sent = news.get("overall_sentiment")
        if overall_sent is None and not news:
            print("  (Keine News-Daten angebunden oder Agent hat nichts gefunden.)")
        else:
            print(f"  Gesamt-Sentiment: {overall_sent}")
            print("  Wichtige Events:")
            for ev in (news.get("key_events") or [])[:5]:
                print("   -", ev)
            print("  Risiko-Flags:")
            for rf in (news.get("risk_flags") or [])[:5]:
                print("   -", rf)

        # Falls trotzdem ein Options-Plan existieren sollte (theoretisch nicht der Fall):
        if options_plan:
            print("\n🔻 Options-Plan (analytisch):")
            print(f"  Typ:            {options_plan.get('type')}")
            print(f"  POP-Score:      {options_plan.get('pop_score')}")
            comp = options_plan.get("component_scores") or {}
            print(f"    Trend-Score:  {comp.get('trend_score')}")
            print(f"    Entry-Score:  {comp.get('entry_score')}")
            print(f"    News-Score:   {comp.get('news_score')}")
            print(f"    IV-Score:     {comp.get('iv_score')}")

            dte = options_plan.get("dte_target") or {}
            print(f"  DTE-Target:     {dte.get('min')}–{dte.get('max')} Tage")
            print(f"  Expiry-Hinweis: {dte.get('expiry_hint')}")
            print(f"  Delta-Target:   {options_plan.get('delta_target')}")
            print(f"  Strike-Präferenz: {options_plan.get('strike_preference')}")
            print(f"  Risikobudget:   {options_plan.get('position_risk_budget')}")
            print(f"  Begründung:     {options_plan.get('entry_reason')}")

        return  # sauber beenden

    # --------------------------------------
    # Ab hier NUR, wenn wirklich ein Trade geplant ist
    # --------------------------------------

    print("\n📰 News-Überblick:")
    overall_sent = news.get("overall_sentiment")
    if overall_sent is None and not news:
        print("  (Keine News-Daten angebunden oder Agent hat nichts gefunden.)")
    else:
        print(f"  Gesamt-Sentiment: {overall_sent}")
        print("  Wichtige Events:")
        for ev in (news.get("key_events") or [])[:5]:
            print("   -", ev)
        print("  Risiko-Flags:")
        for rf in (news.get("risk_flags") or [])[:5]:
            print("   -", rf)

    entry = plan.get("entry") or {}
    sl = plan.get("stop_loss") or {}
    tp = plan.get("take_profit") or {}
    size = plan.get("position_sizing") or {}

    print("\nEntry:")
    print(f"  Style:         {entry.get('style')}")
    print(f"  Trigger:       {entry.get('trigger_price')}\n")

    print("Risk Management:")
    print(f"  Stop-Loss:     {sl.get('price')}  (Risk/Share: {sl.get('risk_per_share')})")
    print(f"  Take-Profit:   {tp.get('target_price')}  (RRR: {tp.get('reward_risk_ratio')})\n")

    print("Position:")
    print(f"  Max Risk:      {size.get('max_risk_amount')}")
    print(f"  Größe:         {size.get('contracts_or_shares')}\n")

    print("Wichtige Gründe:")
    for r in synth.get("key_reasons", [])[:5]:
        print(" -", r)

    print("\nRisiko-Hinweise:")
    for r in synth.get("risk_notes", [])[:5]:
        print(" -", r)

    # ---------- Options-Plan anzeigen ----------
    if options_plan:
        print("\n🔻 Options-Plan (analytisch):")
        print(f"  Typ:            {options_plan.get('type')}")
        print(f"  POP-Score:      {options_plan.get('pop_score')}")
        comp = options_plan.get("component_scores") or {}
        print(f"    Trend-Score:  {comp.get('trend_score')}")
        print(f"    Entry-Score:  {comp.get('entry_score')}")
        print(f"    News-Score:   {comp.get('news_score')}")
        print(f"    IV-Score:     {comp.get('iv_score')}")

        dte = options_plan.get("dte_target") or {}
        print(f"  DTE-Target:     {dte.get('min')}–{dte.get('max')} Tage")
        print(f"  Expiry-Hinweis: {dte.get('expiry_hint')}")
        print(f"  Delta-Target:   {options_plan.get('delta_target')}")
        print(f"  Strike-Präferenz: {options_plan.get('strike_preference')}")
        print(f"  Risikobudget:   {options_plan.get('position_risk_budget')}")

        print(f"  Begründung:     {options_plan.get('entry_reason')}")


# =================================================================
# SCANNER-MODUS FORMATTER
# =================================================================

def format_scanner_results(result):
    setups = result.get("setups", [])

    print("\n=== SCANNER RESULT ===")
    print(f"Gefundene Setups: {len(setups)}")

    for i, s in enumerate(setups, start=1):
        symbol = s.get("symbol")
        synth = s.get("synthese_output", {})
        signal = s.get("signal_output", {})
        plan = s.get("trade_plan", {})
        news = s.get("news_output", {}) or {}

        nsent = news.get("overall_sentiment")
        nsent_str = f"{nsent:+.2f}" if isinstance(nsent, (int, float)) else "n/a"

        print("\n----------------------------")
        print(f"{i}) Symbol:        {symbol}")
        print(f"    Bias:          {synth.get('overall_bias')}  (Conf: {synth.get('overall_confidence')})")
        print(f"    Signal:        {signal.get('short_term_signal')}  (Conf: {signal.get('confidence')})")
        print(f"    Entry-Stil:    {signal.get('entry_style')}")
        print(f"    News-Sentiment: {nsent_str}")

        reason = plan.get("reason", "")
        if isinstance(reason, str) and reason.strip():
            print(f"    Grund:         {reason[:180]}...")

        entry = plan.get("entry") or {}
        sl = plan.get("stop_loss") or {}
        tp = plan.get("take_profit") or {}

        print(f"    Trigger:       {entry.get('trigger_price')}")
        print(f"    Stop-Loss:     {sl.get('price')}")
        print(f"    Take-Profit:   {tp.get('target_price')}")

        # News-Details
        key_events = news.get("key_events") or []
        if key_events:
            print("    News-Events:")
            for ev in key_events[:3]:
                print(f"       - {ev}")

        risk_flags = news.get("risk_flags") or []
        if risk_flags:
            print("    Risiko-Flags:")
            for rf in risk_flags[:3]:
                print(f"       - {rf}")

        # Optional: Options-Info im Scanner
        options_plan = plan.get("options_plan") or {}
        if options_plan:
            print(f"    Options-POP:   {options_plan.get('pop_score')}")
            print(f"    Opt-Typ:       {options_plan.get('type')} (Delta~{options_plan.get('delta_target')}, DTE {options_plan.get('dte_target', {}).get('min')}–{options_plan.get('dte_target', {}).get('max')})")


# =================================================================
# START-MENÜ
# =================================================================

def _print_monitor_stats() -> None:
    if _pm_module.monitor is None:
        return
    s = _pm_module.monitor.stats()
    print("\n=== Position-Monitor Stats ===")
    print(f"  Gesamt Trades:  {s['total_trades']}")
    print(f"  Offen:          {s['open']}")
    print(f"  Take-Profit:    {s['closed_take_profit']}")
    print(f"  Stop-Loss:      {s['closed_stop_loss']}")
    print(f"  Gesamt P&L:     {s['total_pnl']:+.2f}")
    wr = s["win_rate"]
    print(f"  Win-Rate:       {f'{wr:.1%}' if wr is not None else 'n/a'}")


def start():
    print("=== Trading Agent Orchestrator ===")
    print("1) Einzelmodus")
    print("2) Scannermodus (nach Universum)")
    print("3) Offene Positionen anzeigen")
    print("4) Trade-Historie anzeigen")
    print("5) Automatischer Scheduler starten (Daemon)")
    print("6) Backtest")
    print("7) ML-Modell trainieren")
    choice = input("Modus wählen (1-7): ").strip()

    # Monitor starten (Hintergrund-Thread für SL/TP-Überwachung)
    if _pm_module.monitor and not (_pm_module.monitor._thread and _pm_module.monitor._thread.is_alive()):
        _pm_module.monitor.start()
        print("[Monitor] Positions-Überwachung gestartet.")

    import os
    account_info = {
        "account_size": float(os.getenv("ACCOUNT_SIZE", "100000")),
        "max_risk_per_trade": float(os.getenv("MAX_RISK_PER_TRADE", "0.01")),
        "broker_preference": os.getenv("BROKER_PREFERENCE", "alpaca"),
    }

    # ---------------------------------------------------------
    # 1) EINZELMODUS
    # ---------------------------------------------------------
    if choice == "1":
        symbol = input("Symbol eingeben (z.B. AAPL): ").strip().upper()
        if not symbol:
            print("Kein Symbol eingegeben, Abbruch.")
            return

        timeframe = input("Timeframe (z.B. 1D, 4H, 1H) [Default 1D]: ").strip() or "1D"
        auto_ex = input("Auto-Execute aktivieren? (nur Simulate/Paper) [j/N]: ").strip().lower() == "j"

        result = run_single_symbol_mode(
            symbol=symbol,
            account_info=account_info,
            timeframe=timeframe,
            asset_type="stock",
            market_hint="US",
            auto_execute=auto_ex,
        )
        format_single_result(result)
        _print_monitor_stats()

    # ---------------------------------------------------------
    # 2) SCANNERMODUS – UNIVERSEN
    # ---------------------------------------------------------
    elif choice == "2":
        print("\nVerfügbare Universen (JSON-Dateien im ordner 'universes'):")
        available = universe_manager.list_universes()
        for name in available:
            print(f"  - {name}")
        if not available:
            print("  (Keine Universen gefunden – prüfe den 'universes'-Ordner.)")
            return

        print("\nDu kannst mehrere Universen kommagetrennt eingeben, z.B.:")
        print("  sp500, semis")
        universes_raw = input("Universum / Universen wählen: ").strip()

        if not universes_raw:
            print("Keine Universen gewählt, Abbruch.")
            return

        universe_names = [u.strip() for u in universes_raw.split(",") if u.strip()]

        try:
            # nutzt Aliasse wie 'S&P500', 'Rohstoffe' etc. aus universe_manager.ALIASES
            watchlist = universe_manager.get(*universe_names)
        except Exception as e:
            print(f"Fehler beim Laden der Universen: {e}")
            return

        if not watchlist:
            print("Watchlist ist leer, nichts zu scannen.")
            return

        print(f"\nScanner läuft über {len(watchlist)} Symbole.")
        # Nur zur Info max. die ersten 20 anzeigen:
        print("Beispiele:", ", ".join(watchlist[:20]))
        if len(watchlist) > 20:
            print("...")

        timeframe = input("Timeframe für Scanner [Default 1D]: ").strip() or "1D"
        auto_ex = input("Auto-Execute aktivieren? (nur Simulate/Paper) [j/N]: ").strip().lower() == "j"

        result = run_scanner_mode(
            watchlist=watchlist,
            account_info=account_info,
            timeframe=timeframe,
            asset_type="stock",
            market_hint="US",
            auto_execute=auto_ex,
        )
        format_scanner_results(result)
        _print_monitor_stats()

    # ---------------------------------------------------------
    # 3) OFFENE POSITIONEN
    # ---------------------------------------------------------
    elif choice == "3":
        if _pm_module.monitor is None:
            print("Position-Monitor nicht initialisiert.")
            return
        positions = _pm_module.monitor.get_open_positions()
        if not positions:
            print("\nKeine offenen Positionen.")
        else:
            print(f"\n=== Offene Positionen ({len(positions)}) ===")
            for p in positions:
                print(
                    f"  #{p['id']} {p['direction'].upper():5} {p['symbol']:8} "
                    f"x{p['quantity']:.2f}  Entry={p['entry_price']}  "
                    f"SL={p['stop_loss']}  TP={p['take_profit']}  "
                    f"seit {p['opened_at'][:19]}"
                )

    # ---------------------------------------------------------
    # 4) TRADE-HISTORIE
    # ---------------------------------------------------------
    elif choice == "4":
        if _pm_module.monitor is None:
            print("Position-Monitor nicht initialisiert.")
            return
        history = _pm_module.monitor.get_history(limit=20)
        if not history:
            print("\nNoch keine Trades in der Datenbank.")
        else:
            print(f"\n=== Letzte {len(history)} Trades ===")
            for p in history:
                pnl = f"{p['pnl']:+.2f}" if p["pnl"] is not None else "offen"
                print(
                    f"  #{p['id']} {p['direction'].upper():5} {p['symbol']:8} "
                    f"Status={p['status']:25} P&L={pnl}"
                )
        _print_monitor_stats()

    # ---------------------------------------------------------
    # 5) SCHEDULER (Daemon)
    # ---------------------------------------------------------
    elif choice == "5":
        from scheduler import TradingScheduler
        import signal as _signal

        print("\n[Scheduler] Starte automatischen Trading-Daemon.")
        print("  Konfiguration: SCHEDULER_MARKETS, SCHEDULER_UNIVERSE, SCHEDULER_AUTO_EXECUTE")
        print("  Beenden mit Ctrl+C\n")

        sched = TradingScheduler()

        def _stop(sig, _):
            sched.stop()
            sys.exit(0)

        import sys
        _signal.signal(_signal.SIGINT, _stop)
        _signal.signal(_signal.SIGTERM, _stop)
        sched.start()  # blockiert

    # ---------------------------------------------------------
    # 6) BACKTEST
    # ---------------------------------------------------------
    elif choice == "6":
        from BACKTEST import fetch_candles_yfinance, run_backtest, print_report, plot_equity_curve

        symbol   = input("Symbol (z.B. AAPL, SAP) [AAPL]: ").strip().upper() or "AAPL"
        period   = input("Zeitraum (1y/2y/5y) [2y]: ").strip() or "2y"
        acc_raw  = input("Startkapital [100000]: ").strip()
        acct     = float(acc_raw) if acc_raw else account_info["account_size"]
        risk_raw = input("Max Risiko/Trade (z.B. 0.01) [0.01]: ").strip()
        risk     = float(risk_raw) if risk_raw else account_info["max_risk_per_trade"]

        print(f"\nLade {symbol} ({period}) via yfinance...")
        try:
            candles = fetch_candles_yfinance(symbol, period=period)
        except Exception as exc:
            print(f"Fehler: {exc}")
            return

        print(f"{len(candles)} Candles geladen. Simuliere...")
        result = run_backtest(candles, account_size=acct, max_risk_per_trade=risk)
        print_report(result, symbol)

        if input("Equity-Kurve anzeigen? [j/N]: ").strip().lower() == "j":
            plot_equity_curve(result, symbol)

    # ---------------------------------------------------------
    # 7) ML-MODELL TRAINIEREN
    # ---------------------------------------------------------
    elif choice == "7":
        import subprocess, sys
        print("\n[ML] Starte TRAIN_MODEL.py …")
        subprocess.run([sys.executable, "TRAIN_MODEL.py"], check=False)

    else:
        print("Ungültige Wahl.")



# =================================================================
# MAIN ENTRYPOINT
# =================================================================

if __name__ == "__main__":
    start()
