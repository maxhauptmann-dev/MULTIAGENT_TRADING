import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

print("Lade .env in TEST_FINNHUB.py ...")
load_dotenv()

# Debug-Ausgabe, um sicherzugehen, dass der Key da ist
finnhub_key = os.getenv("FINNHUB_API_KEY")
print("FINNHUB_API_KEY (erste 6 Zeichen):", (finnhub_key or "")[:6])

if not finnhub_key:
    print("FEHLER: FINNHUB_API_KEY ist nicht gesetzt!")
    raise SystemExit(1)

symbol = "AAPL"
days_back = 3

end = datetime.utcnow().date()
start = end - timedelta(days=days_back)

url = "https://finnhub.io/api/v1/company-news"
params = {
    "symbol": symbol,
    "from": start.isoformat(),
    "to": end.isoformat(),
    "token": finnhub_key,
}

print(f"\n⏳ Teste Finnhub…")
print(f"→ Anfrage: {url}")
print(f"→ Parameter: {params}\n")

resp = requests.get(url, params=params, timeout=10)

print("Status Code:", resp.status_code)

try:
    data = resp.json()
    print("Erhaltene Artikel:", len(data))
    for i, item in enumerate(data[:5]):
        print(f"{i+1}. {item.get('headline')}")
except Exception as e:
    print("Fehler beim JSON-Parsing:", e)
