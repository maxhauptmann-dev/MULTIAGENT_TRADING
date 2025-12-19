# alt:
# from trading_agents_with_gpt import run_single_symbol_mode

# neu:

# TEST.py

from trading_agents_with_gpt import run_single_symbol_mode
import pprint

# 1) Account-Infos, die an den Handels-Agent gehen
account_info = {
    "account_size": 10000,          # dein Konto in $
    "max_risk_per_trade": 0.001,     # 1% Risiko pro Trade
    "time_horizon": "short",        # "short" / "medium" / "long"
    "broker_preference": "ibkr",    # für ExecutionAgent (jetzt noch optional)
}

# 2) Orchestrator aufrufen (Modus A – Einzelaktie)
print("Starte Orchestrator für NVDA...\n")

result = run_single_symbol_mode(
    symbol="NVDA",
    account_info=account_info,
    timeframe="1D",        # passt zu deinem DataAgent (Tageskerzen)
    asset_type="stock",
    market_hint="US",
    auto_execute=False,    # KEINE echten Orders senden
)

print("\n=== ORCHESTRATOR ERGEBNIS ===")
pprint.pp(result)
print("\nFertig.")