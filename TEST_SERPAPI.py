import os
import requests
from dotenv import load_dotenv

print("Lade .env in TEST_SERPAPI.py ...")
load_dotenv()

serp_key = os.getenv("SERPAPI_API_KEY")
print("SERPAPI_API_KEY (erste 6 Zeichen):", (serp_key or "")[:6])

if not serp_key:
    print("FEHLER: SERPAPI_API_KEY ist nicht gesetzt!")
    raise SystemExit(1)

params = {
    "engine": "google_news",
    "q": "AAPL stock",
    "api_key": serp_key,
    "hl": "en",
    "num": 10,
}

print(f"\n⏳ Teste SerpAPI Google News…")
resp = requests.get("https://serpapi.com/search", params=params, timeout=10)

print("Status Code:", resp.status_code)

try:
    data = resp.json()
    articles = data.get("news_results", []) or data.get("articles", [])
    print("Erhaltene Artikel:", len(articles))
    for i, item in enumerate(articles[:5]):
        print(f"{i+1}. {item.get('title')}")
except Exception as e:
    print("Fehler beim JSON-Parsing:", e)

