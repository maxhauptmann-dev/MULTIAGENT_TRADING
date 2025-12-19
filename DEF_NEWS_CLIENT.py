import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

# .env laden, damit FINNHUB_API_KEY / SERPAPI_API_KEY verfügbar sind
load_dotenv()


class NewsClient:
    """
    Kombinierter News-Client:
    - Finnhub für strukturierte Finanz-News
    - SerpAPI für allgemeine Web-News

    Erwartet ENV-Variablen:
    - FINNHUB_API_KEY
    - SERPAPI_API_KEY
    """

    def __init__(
        self,
        finnhub_api_key: Optional[str] = None,
        serpapi_api_key: Optional[str] = None,
    ):
        self.finnhub_api_key = finnhub_api_key or os.getenv("FINNHUB_API_KEY")
        self.serpapi_api_key = serpapi_api_key or os.getenv("SERPAPI_API_KEY")

        if not self.finnhub_api_key:
            print("[NewsClient] WARNUNG: FINNHUB_API_KEY nicht gesetzt – Finnhub-News deaktiviert.")
        if not self.serpapi_api_key:
            print("[NewsClient] WARNUNG: SERPAPI_API_KEY nicht gesetzt – SerpAPI-News deaktiviert.")

    # ---------- Public API ----------

    def get_combined_news(
        self,
        symbol: str,
        days_back: int = 3,
        limit_per_source: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Holt News aus beiden Quellen und gibt eine kombinierte Liste zurück.
        Normalisiertes Format:
        {
            "symbol": str,
            "headline": str,
            "source": str,
            "published_at": str (ISO oder frei, GPT kommt klar),
            "url": str | None,
            "summary": str | None,
            "provider": "finnhub" | "serpapi"
        }
        """
        news: List[Dict[str, Any]] = []

        # Finnhub
        if self.finnhub_api_key:
            try:
                finnhub_news = self._get_finnhub_news(symbol, days_back, limit_per_source)
                news.extend(finnhub_news)
            except Exception as e:
                print(f"[NewsClient] Fehler bei Finnhub-News für {symbol}: {e}")

        # SerpAPI
        if self.serpapi_api_key:
            try:
                serp_news = self._get_serpapi_news(symbol, days_back, limit_per_source)
                news.extend(serp_news)
            except Exception as e:
                print(f"[NewsClient] Fehler bei SerpAPI-News für {symbol}: {e}")

        # Nach Datum sortieren (neueste zuerst, soweit parsebar)
        from datetime import timezone

        def _parse_dt(x: Dict[str, Any]) -> datetime:
            ts = x.get("published_at")
            if not ts:
                # immer naive datetime zurückgeben
                return datetime.min

            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                # timezone-aware → auf UTC normalisieren und tzinfo entfernen
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except Exception:
                # bei Parsing-Problemen: minimaler Wert, ebenfalls naive
                return datetime.min

        news_sorted = sorted(news, key=_parse_dt, reverse=True)
        print(f"[NewsClient] Combined-News für {symbol}: {len(news_sorted)}")
        return news_sorted

    # ---------- Finnhub ----------

    def _get_finnhub_news(
        self,
        symbol: str,
        days_back: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Nutzt Finnhub company-news Endpoint.
        https://finnhub.io/docs/api/company-news
        """
        end = datetime.utcnow().date()
        start = end - timedelta(days=days_back)

        url = "https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": symbol,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "token": self.finnhub_api_key,
        }

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results: List[Dict[str, Any]] = []
        for item in data[:limit]:
            ts = item.get("datetime")
            if ts is not None:
                dt = datetime.utcfromtimestamp(ts).isoformat() + "Z"
            else:
                dt = None

            results.append(
                {
                    "symbol": symbol,
                    "headline": item.get("headline"),
                    "source": item.get("source"),
                    "published_at": dt,
                    "url": item.get("url"),
                    "summary": item.get("summary"),
                    "provider": "finnhub",
                }
            )

        print(f"[NewsClient] Finnhub-News für {symbol}: {len(results)}")
        return results

    # ---------- SerpAPI ----------

    def _get_serpapi_news(
        self,
        symbol: str,
        days_back: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Nutzt SerpAPI Google-News-Suche.
        https://serpapi.com/google-news-api
        """
        query = f"{symbol} stock"

        url = "https://serpapi.com/search"
        params = {
            "engine": "google_news",
            "q": query,
            "api_key": self.serpapi_api_key,
            "hl": "en",
            "num": limit,
        }

        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        articles = data.get("news_results", []) or data.get("articles", []) or []

        results: List[Dict[str, Any]] = []
        for item in articles[:limit]:
            dt_raw = item.get("date") or item.get("published_date")
            dt_iso = dt_raw  # wir lassen es so, GPT kann Strings interpretieren

            source = item.get("source")
            if isinstance(source, dict):
                source_name = source.get("name")
            else:
                source_name = source

            results.append(
                {
                    "symbol": symbol,
                    "headline": item.get("title") or item.get("headline"),
                    "source": source_name,
                    "published_at": dt_iso,
                    "url": item.get("link") or item.get("url"),
                    "summary": item.get("snippet") or item.get("summary"),
                    "provider": "serpapi",
                }
            )

        print(f"[NewsClient] SerpAPI-News für {symbol}: {len(results)}")
        return results
