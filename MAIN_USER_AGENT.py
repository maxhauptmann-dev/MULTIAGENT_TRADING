# MAIN_USER_AGENT.py

from trading_agents_with_gpt import run_single_symbol_mode
from DEF_SCANNER_MODE import run_scanner_mode
from universe_manager import manager as universe_manager

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

def start():
    print("=== Trading Agent Orchestrator ===")
    print("1) Einzelmodus")
    print("2) Scannermodus (nach Universum)")
    choice = input("Modus wählen (1/2): ").strip()

    # hier kannst du später echte Account-Daten reinpacken / aus .env lesen
    account_info = {
        "account_size": 100000,
        "max_risk_per_trade": 0.01,
        "broker_preference": "IBKR",
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

        result = run_single_symbol_mode(
            symbol=symbol,
            account_info=account_info,
            timeframe=timeframe,
            asset_type="stock",
            market_hint="US",
            auto_execute=False,
        )
        format_single_result(result)

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

        result = run_scanner_mode(
            watchlist=watchlist,
            account_info=account_info,
            timeframe=timeframe,
            asset_type="stock",
            market_hint="US",
            auto_execute=False,
        )
        format_scanner_results(result)

    else:
        print("Ungültige Wahl.")



# =================================================================
# MAIN ENTRYPOINT
# =================================================================

if __name__ == "__main__":
    start()
