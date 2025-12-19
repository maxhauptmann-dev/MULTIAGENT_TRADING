from pprint import pprint

from DEF_SCANNER_MODE import run_scanner_mode


# --- Konto-Infos ---
account_info = {
    "account_size": 100000,
    "max_risk_per_trade": 0.01,
    "time_horizon": "short",
    "broker_preference": "ibkr",
}

# --- Watchlist ---
watchlist = ["AAPL", "MSFT", "NVDA"]

print("Starte Scanner-Mode...")
print("Watchlist:", watchlist)

result = run_scanner_mode(
    watchlist=watchlist,
    account_info=account_info,
    timeframe="1D",     # gültig
    asset_type="stock",
    market_hint="US",
    auto_execute=False,
)

print("\n=== SCANNER RESULT ===")
pprint(result)

print("\nGefundene Setups:", len(result.get("setups", [])))

for s in result.get("setups", []):
    print("\n---", s["symbol"], "---")
    print("Signal:", s["signal_output"]["short_term_signal"])
    print("Bias:", s["synthese_output"]["overall_bias"])
    print("Reason:", s["trade_plan"]["reason"][:200], "...")