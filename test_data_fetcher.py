"""
Unit Tests for DataFetcher Module
Tests caching, error handling, and data format compatibility with DEF_INDICATORS
"""

import unittest
import os
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import json

from data_fetcher import (
    DataFetcher,
    Candle,
    MarketData,
    IVData,
    CacheManager,
)

# Configure logging for tests
logging.basicConfig(level=logging.WARNING)


class TestCacheManager(unittest.TestCase):
    """Test TTL-based cache"""

    def setUp(self):
        self.cache = CacheManager()

    def test_set_and_get(self):
        """Test basic set/get operations"""
        self.cache.set("key1", {"value": 42})
        result = self.cache.get("key1", ttl_seconds=3600)
        self.assertEqual(result, {"value": 42})

    def test_cache_expiration(self):
        """Test TTL expiration"""
        import time

        self.cache.set("key1", {"value": 42})
        # Retrieve with very short TTL
        result = self.cache.get("key1", ttl_seconds=0)
        self.assertIsNone(result)

    def test_cache_miss(self):
        """Test missing key returns None"""
        result = self.cache.get("nonexistent", ttl_seconds=3600)
        self.assertIsNone(result)

    def test_clear(self):
        """Test cache clearing"""
        self.cache.set("key1", {"value": 42})
        self.cache.clear()
        result = self.cache.get("key1", ttl_seconds=3600)
        self.assertIsNone(result)


class TestCandle(unittest.TestCase):
    """Test Candle data class"""

    def test_candle_creation(self):
        """Test Candle object creation"""
        ts = datetime.now(timezone.utc)
        candle = Candle(timestamp=ts, open=100.0, high=105.0, low=99.0, close=103.0, volume=1000000)

        self.assertEqual(candle.open, 100.0)
        self.assertEqual(candle.close, 103.0)
        self.assertEqual(candle.volume, 1000000)

    def test_candle_to_dict(self):
        """Test Candle serialization"""
        ts = datetime.now(timezone.utc)
        candle = Candle(timestamp=ts, open=100.0, high=105.0, low=99.0, close=103.0, volume=1000000)

        result = candle.to_dict()
        self.assertIn("timestamp", result)
        self.assertEqual(result["open"], 100.0)
        self.assertEqual(result["close"], 103.0)


class TestDataFetcher(unittest.TestCase):
    """Test DataFetcher module"""

    def setUp(self):
        # Mock environment variables
        with patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"}):
            self.fetcher = DataFetcher()

    def test_initialization(self):
        """Test DataFetcher initialization"""
        self.assertIsNotNone(self.fetcher.api_key)
        self.assertIsNotNone(self.fetcher.secret_key)
        self.assertIsNotNone(self.fetcher.headers)

    def test_missing_credentials(self):
        """Test error on missing credentials"""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                DataFetcher()

    @patch("data_fetcher.requests.get")
    def test_fetch_hourly_candles_success(self, mock_get):
        """Test successful hourly candle fetch"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "bars": {
                "AAPL": [
                    {
                        "t": "2026-04-30T14:00:00Z",
                        "o": 150.0,
                        "h": 151.0,
                        "l": 149.0,
                        "c": 150.5,
                        "v": 1000000,
                    }
                ]
            }
        }
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_hourly_candles("AAPL", limit=1)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].close, 150.5)
        self.assertEqual(result[0].volume, 1000000)

    @patch("data_fetcher.requests.get")
    def test_fetch_hourly_candles_empty(self, mock_get):
        """Test fetch with no bars returned"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"bars": {"AAPL": []}}
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_hourly_candles("AAPL")

        self.assertEqual(result, [])

    @patch("data_fetcher.requests.get")
    def test_fetch_hourly_candles_network_error(self, mock_get):
        """Test network error handling"""
        import requests

        mock_get.side_effect = requests.ConnectionError("Connection failed")

        result = self.fetcher.fetch_hourly_candles("AAPL", retry_count=2)

        self.assertIsNone(result)

    def test_cache_hourly_candles(self):
        """Test hourly candle caching"""
        with patch("data_fetcher.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2026-04-30T14:00:00Z",
                            "o": 150.0,
                            "h": 151.0,
                            "l": 149.0,
                            "c": 150.5,
                            "v": 1000000,
                        }
                    ]
                }
            }
            mock_get.return_value = mock_response

            # First fetch
            result1 = self.fetcher.fetch_hourly_candles("AAPL", limit=1)
            # Second fetch (should be cached)
            result2 = self.fetcher.fetch_hourly_candles("AAPL", limit=1)

            self.assertEqual(result1, result2)
            # Should only call API once (second is from cache)
            mock_get.assert_called_once()

    @patch("data_fetcher.requests.get")
    def test_fetch_current_price(self, mock_get):
        """Test current price fetch"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "quote": {
                "bp": 150.0,
                "ap": 150.5,
                "bs": 1000,
                "as": 1000,
            }
        }
        mock_get.return_value = mock_response

        result = self.fetcher.fetch_current_price("AAPL")

        self.assertIsNotNone(result)
        self.assertEqual(result.bid, 150.0)
        self.assertEqual(result.ask, 150.5)
        self.assertEqual(result.bid_size, 1000)
        self.assertEqual(result.ask_size, 1000)

    def test_candles_to_indicators_format(self):
        """Test format conversion for DEF_INDICATORS compatibility"""
        ts = datetime.now(timezone.utc)
        candles = [
            Candle(timestamp=ts, open=100.0, high=105.0, low=99.0, close=103.0, volume=1000000),
            Candle(timestamp=ts + timedelta(hours=1), open=103.0, high=108.0, low=102.0, close=106.0, volume=1200000),
        ]

        result = DataFetcher.candles_to_indicators_format(candles)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["open"], 100.0)
        self.assertEqual(result[0]["close"], 103.0)
        self.assertEqual(result[0]["volume"], 1000000)
        self.assertEqual(result[1]["open"], 103.0)
        self.assertEqual(result[1]["close"], 106.0)

    def test_get_cache_status(self):
        """Test cache status reporting"""
        self.fetcher.cache.set("test_key", {"value": 42})
        status = self.fetcher.get_cache_status()

        self.assertIn("size", status)
        self.assertIn("entries", status)
        self.assertEqual(status["size"], 1)
        self.assertIn("test_key", status["entries"])


class TestMarketDataAndIVData(unittest.TestCase):
    """Test data classes"""

    def test_market_data_creation(self):
        """Test MarketData creation"""
        ts = datetime.now(timezone.utc)
        md = MarketData(
            symbol="AAPL",
            price=150.25,
            bid=150.0,
            ask=150.5,
            bid_size=1000,
            ask_size=1000,
            timestamp=ts,
        )

        self.assertEqual(md.symbol, "AAPL")
        self.assertEqual(md.price, 150.25)

    def test_iv_data_creation(self):
        """Test IVData creation"""
        ts = datetime.now(timezone.utc)
        iv = IVData(symbol="AAPL", iv=0.25, timestamp=ts)

        self.assertEqual(iv.symbol, "AAPL")
        self.assertEqual(iv.iv, 0.25)
        self.assertEqual(iv.source, "alpaca")


if __name__ == "__main__":
    unittest.main()
