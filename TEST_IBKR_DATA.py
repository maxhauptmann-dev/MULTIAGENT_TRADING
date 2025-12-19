#✅

from DEF_DATA_AGENT import DataAgent

agent = DataAgent()

print("Starte Download von AAPL...")

data = agent.fetch("AAPL")

print("\n--- Ergebnis ---")
print("Symbol:", data["symbol"])
print("Anzahl Candles:", len(data["candles"]))
print("Erste Candle:", data["candles"][0] if data["candles"] else "Keine Daten")
print("Meta:", data["meta"])

print("\nTest fertig.")