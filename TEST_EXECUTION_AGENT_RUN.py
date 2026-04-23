import os

# Env-Defaults VOR dem Import setzen (robuster, falls das Modul beim Import env liest)
os.environ.setdefault("EXECUTION_MODE", "simulate")
os.environ.setdefault("PAPER_EXECUTE", "0")
os.environ.setdefault("MAX_QTY_CAP", "100")
# Optional: ALLOW_REAL_EXECUTION nur setzen, wenn du Live testen willst
# os.environ.setdefault("ALLOW_REAL_EXECUTION", "1")

from trading_agents_with_gpt import ExecutionAgent
import pprint

pp = pprint.PrettyPrinter(indent=2)

# 1) Simulate (default)
os.environ.setdefault("EXECUTION_MODE", "simulate")
agent = ExecutionAgent()
plan = {
  "action": "open_position",
  "symbol": "AAPL",
  "direction": "long",
  "instrument_type": "stock",
  "order_type": "MKT",
  "position_sizing": {"contracts_or_shares": 5},
}
print("=== SIMULATE ===")
pp.pprint(agent.execute_trade_plan(plan))

# 2) Blocked live (guard)
os.environ["EXECUTION_MODE"] = "live"
os.environ["PAPER_EXECUTE"] = "0"
agent_live_blocked = ExecutionAgent()
print("\n=== LIVE BLOCKED (PAPER_EXECUTE=0) ===")
pp.pprint(agent_live_blocked.execute_trade_plan(plan))

# 3) Live attempt (will try IBKR HTTP path — likely error if no session)
os.environ["EXECUTION_MODE"] = "live"
os.environ["PAPER_EXECUTE"] = "1"
os.environ["ALLOW_REAL_EXECUTION"] = "1"
agent_live = ExecutionAgent()
print("\n=== LIVE ATTEMPT (may error if IBKR HTTP session not configured) ===")
pp.pprint(agent_live.execute_trade_plan(plan))