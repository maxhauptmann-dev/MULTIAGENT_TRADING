"""
DataFetcher Module — Reliable hourly/daily data pipeline from Alpaca
Handles OHLCV candles, implied volatility, and current prices with caching.
"""

import os
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
from functools import lru_cache
import time

# ============================================================
# Data Classes
# ============================================================


@dataclass
class Candle:
    """Single OHLCV bar"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class MarketData:
    """Complete market snapshot for a symbol"""
    symbol: str
    price: float
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class IVData:
    """Implied Volatility snapshot"""
    symbol: str
    iv: float
    timestamp: datetime
    source: str = "alpaca"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "iv": self.iv,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }


# ============================================================
# Caching Layer
# ============================================================

class CacheManager:
    """Simple TTL-based cache for market data"""

    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str, ttl_seconds: int = 3600) -> Optional[Any]:
        """Retrieve cached value if not expired"""
        if key not in self.cache:
            return None

        entry = self.cache[key]
        age = time.time() - entry["timestamp"]

        if age > ttl_seconds:
            del self.cache[key]
            return None

        return entry["value"]

    def set(self, key: str, value: Any) -> None:
        """Store value with current timestamp"""
        self.cache[key] = {
            "value": value,
            "timestamp": time.time(),
        }

    def clear(self) -> None:
        """Clear all cache"""
        self.cache.clear()


# ============================================================
# DataFetcher
# ============================================================

class DataFetcher:
    """Fetches OHLCV, IV, and market data from Alpaca"""

    BASE_URL = "https://api.alpaca.markets"
    DATA_BASE_URL = "https://data.alpaca.markets"

    def __init__(self):
        self.api_key = os.getenv("APCA_API_KEY_ID")
        self.secret_key = os.getenv("APCA_API_SECRET_KEY")

        if not self.api_key or not self.secret_key:
            raise ValueError(
                "Missing Alpaca credentials: APCA_API_KEY_ID or APCA_API_SECRET_KEY"
            )

        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

        self.cache = CacheManager()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # -------- Hourly Candles (last 72 hours) --------
    def fetch_hourly_candles(
        self,
        symbol: str,
        limit: int = 72,
        retry_count: int = 3,
    ) -> Optional[List[Candle]]:
        """Fetch last 72 hours of hourly candles from Alpaca"""
        cache_key = f"hourly_candles:{symbol}"
        cached = self.cache.get(cache_key, ttl_seconds=300)  # 5-min cache
        if cached is not None:
            return cached

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=limit)

        # Use v2/stocks endpoint for stock bars
        url = f"{self.DATA_BASE_URL}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": "1h",
            "start": start_time.isoformat().replace("+00:00", "Z"),
            "end": end_time.isoformat().replace("+00:00", "Z"),
            "limit": limit,
            "adjustment": "all",
        }

        for attempt in range(retry_count):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                bars = data.get("bars", {}).get(symbol, [])
                if not bars:
                    self.logger.info(f"No hourly candles returned for {symbol}")
                    return []

                candles = []
                for bar in bars:
                    # Handle both ISO and numeric timestamp formats
                    if isinstance(bar.get("t"), str):
                        ts = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                    else:
                        ts = datetime.fromtimestamp(bar["t"], tz=timezone.utc)

                    candle = Candle(
                        timestamp=ts,
                        open=float(bar["o"]),
                        high=float(bar["h"]),
                        low=float(bar["l"]),
                        close=float(bar["c"]),
                        volume=int(bar.get("v", 0)),
                    )
                    candles.append(candle)

                self.cache.set(cache_key, candles)
                self.logger.info(
                    f"Fetched {len(candles)} hourly candles for {symbol}"
                )
                return candles

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{retry_count}: Failed to fetch hourly candles "
                    f"for {symbol}: {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(1 + attempt)
                continue

        self.logger.error(f"Failed to fetch hourly candles for {symbol} after {retry_count} retries")
        return None

    # -------- Daily Candles (last 365 days, cached) --------
    def fetch_daily_candles(
        self,
        symbol: str,
        limit: int = 365,
        retry_count: int = 3,
    ) -> Optional[List[Candle]]:
        """Fetch last 365 days of daily candles from Alpaca (cached for 1 hour)"""
        cache_key = f"daily_candles:{symbol}"
        cached = self.cache.get(cache_key, ttl_seconds=3600)  # 1-hour cache
        if cached is not None:
            return cached

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=limit)

        # Use v2/stocks endpoint for stock bars
        url = f"{self.DATA_BASE_URL}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": "1d",
            "start": start_time.isoformat().replace("+00:00", "Z"),
            "end": end_time.isoformat().replace("+00:00", "Z"),
            "limit": limit,
            "adjustment": "all",
        }

        for attempt in range(retry_count):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                bars = data.get("bars", {}).get(symbol, [])
                if not bars:
                    self.logger.info(f"No daily candles returned for {symbol}")
                    return []

                candles = []
                for bar in bars:
                    # Handle both ISO and numeric timestamp formats
                    if isinstance(bar.get("t"), str):
                        ts = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                    else:
                        ts = datetime.fromtimestamp(bar["t"], tz=timezone.utc)

                    candle = Candle(
                        timestamp=ts,
                        open=float(bar["o"]),
                        high=float(bar["h"]),
                        low=float(bar["l"]),
                        close=float(bar["c"]),
                        volume=int(bar.get("v", 0)),
                    )
                    candles.append(candle)

                self.cache.set(cache_key, candles)
                self.logger.info(
                    f"Fetched {len(candles)} daily candles for {symbol}"
                )
                return candles

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{retry_count}: Failed to fetch daily candles "
                    f"for {symbol}: {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(1 + attempt)
                continue

        self.logger.error(f"Failed to fetch daily candles for {symbol} after {retry_count} retries")
        return None

    # -------- Implied Volatility (1-hour cache) --------
    def fetch_iv(
        self,
        symbol: str,
        retry_count: int = 3,
    ) -> Optional[float]:
        """Fetch implied volatility for symbol (cached 1 hour)"""
        cache_key = f"iv:{symbol}"
        cached = self.cache.get(cache_key, ttl_seconds=3600)  # 1-hour cache
        if cached is not None:
            return cached

        url = f"{self.BASE_URL}/v1/marketdata/etfs/{symbol}/snapshot"

        for attempt in range(retry_count):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                # Extract IV from option chain if available
                if "option_chain" in data:
                    iv = data["option_chain"].get("iv", 0.25)
                else:
                    # Fallback: use previous or default
                    iv = 0.25

                self.cache.set(cache_key, iv)
                self.logger.info(f"Fetched IV for {symbol}: {iv:.4f}")
                return iv

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{retry_count}: Failed to fetch IV "
                    f"for {symbol}: {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(1 + attempt)
                continue

        self.logger.warning(f"Failed to fetch IV for {symbol}, using default 0.25")
        return 0.25

    # -------- Current Market Price --------
    def fetch_current_price(
        self,
        symbol: str,
        retry_count: int = 3,
    ) -> Optional[MarketData]:
        """Fetch current bid/ask/price for symbol"""
        url = f"{self.BASE_URL}/v1/marketdata/stocks/{symbol}/latest/quote"

        for attempt in range(retry_count):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json().get("quote", {})

                market_data = MarketData(
                    symbol=symbol,
                    price=float(data.get("ap", data.get("bp", 0))),  # ask price or bid price
                    bid=float(data.get("bp", 0)),
                    ask=float(data.get("ap", 0)),
                    bid_size=int(data.get("bs", 0)),
                    ask_size=int(data.get("as", 0)),
                    timestamp=datetime.now(timezone.utc),
                )

                self.logger.info(
                    f"Fetched price for {symbol}: ${market_data.price:.2f} "
                    f"(bid: ${market_data.bid:.2f}, ask: ${market_data.ask:.2f})"
                )
                return market_data

            except requests.exceptions.RequestException as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{retry_count}: Failed to fetch current price "
                    f"for {symbol}: {e}"
                )
                if attempt < retry_count - 1:
                    time.sleep(1 + attempt)
                continue

        self.logger.error(f"Failed to fetch current price for {symbol}")
        return None

    # -------- Batch Operations --------
    def fetch_all_symbols(
        self,
        symbols: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch hourly + daily candles + IV for all symbols"""
        results = {}

        for symbol in symbols:
            hourly = self.fetch_hourly_candles(symbol)
            daily = self.fetch_daily_candles(symbol)
            iv = self.fetch_iv(symbol)
            price = self.fetch_current_price(symbol)

            results[symbol] = {
                "symbol": symbol,
                "hourly_candles": hourly or [],
                "daily_candles": daily or [],
                "iv": iv,
                "price": price.to_dict() if price else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        return results

    def fetch_symbol(self, symbol: str) -> Dict[str, Any]:
        """Fetch all data for single symbol"""
        hourly = self.fetch_hourly_candles(symbol)
        daily = self.fetch_daily_candles(symbol)
        iv = self.fetch_iv(symbol)
        price = self.fetch_current_price(symbol)

        return {
            "symbol": symbol,
            "hourly_candles": [c.to_dict() for c in hourly] if hourly else [],
            "daily_candles": [c.to_dict() for c in daily] if daily else [],
            "iv": iv,
            "price": price.to_dict() if price else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # -------- Cache Management --------
    def clear_cache(self) -> None:
        """Clear all cached data"""
        self.cache.clear()
        self.logger.info("Cache cleared")

    def get_cache_status(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": len(self.cache.cache),
            "entries": list(self.cache.cache.keys()),
        }

    # -------- Format Conversion --------
    @staticmethod
    def candles_to_indicators_format(candles: List[Candle]) -> List[Dict[str, float]]:
        """Convert Candle objects to format expected by DEF_INDICATORS.compute_indicators

        Expected format: List of dicts with keys: open, high, low, close, volume
        """
        return [
            {
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = DataFetcher()

    # Test single symbol
    print("\n=== Testing Single Symbol ===")
    result = fetcher.fetch_symbol("AAPL")
    print(json.dumps(result, indent=2, default=str))

    # Test multiple symbols
    print("\n=== Testing Multiple Symbols ===")
    symbols = ["AAPL", "MSFT", "GOOGL"]
    results = fetcher.fetch_all_symbols(symbols)
    for symbol, data in results.items():
        print(f"\n{symbol}:")
        print(f"  Hourly candles: {len(data['hourly_candles'])}")
        print(f"  Daily candles: {len(data['daily_candles'])}")
        print(f"  IV: {data['iv']}")
        print(f"  Price: ${data['price']['price']:.2f}" if data['price'] else "  Price: N/A")

    # Cache status
    print("\n=== Cache Status ===")
    print(json.dumps(fetcher.get_cache_status(), indent=2))
