import os
from pprint import pprint

os.environ.setdefault("EXECUTION_MODE", "simulate")
os.environ.setdefault("PAPER_EXECUTE", "0")
os.environ.setdefault("MAX_QTY_CAP", "100")

from trading_agents_with_gpt import ExecutionAgent


def run_case(title: str, plan: dict, broker: str | None = None):
    print(f"\n=== {title} ===")
    agent = ExecutionAgent()
    result = agent.execute_trade_plan(plan, broker_preference=broker)
    pprint(result)
    assert result["status"] in {"simulated", "blocked", "sent", "no_trade"}
    return result


base_plan = {
    "action": "open_position",
    "symbol": "AAPL",
    "direction": "long",
    "instrument_type": "stock",
    "order_type": "MKT",
    "position_sizing": {"contracts_or_shares": 5},
}

# 1) Default simulate (no broker preference)
run_case("Default simulate", base_plan)

# 2) Quantity cap demo
big_plan = {**base_plan, "position_sizing": {"contracts_or_shares": 9999}}
res = run_case("Capped quantity", big_plan)
assert res.get("status") == "simulated"

# 3) Force simulate via broker preference flag
run_case("Explicit simulate preference", base_plan, broker="simulate")

print("\nAll simulate smoke tests passed.")
