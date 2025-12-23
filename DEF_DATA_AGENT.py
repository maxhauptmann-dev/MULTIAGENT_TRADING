import os
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import *
from ibapi.ticktype import *

import threading
import time
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# Low-Level IBKR Client (Wrapper + Client)
# ============================================================

class IBKRClient(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.data: List[Dict[str, Any]] = []
        self.contract_details_received: bool = False
        self.historical_data_finished: bool = False
        self.conid: Optional[int] = None

    # -------- ERROR LOGGING ----------
    def error(self, reqId, errorCode, errorString):
        print(f"[IBKRClient][ERROR] reqId={reqId}, code={errorCode}, msg={errorString}")

    # -------- Contract Details (für conid) ----------
    def contractDetails(self, reqId, contractDetails):
        self.conid = contractDetails.contract.conId
        print(f"[IBKRClient] contractDetails erhalten: conid={self.conid}")
        self.contract_details_received = True

    def contractDetailsEnd(self, reqId):
        print(f"[IBKRClient] contractDetailsEnd für reqId={reqId}")
        self.contract_details_received = True

    # -------- Historical Data ----------
    def historicalData(self, reqId, bar):
        # bar: BarData
        self.data.append({
            "timestamp": bar.date,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        })
        # Erste Bar zu Debug-Zwecken
        if len(self.data) == 1:
            print(f"[IBKRClient] erste Historical-Bar: {bar.date}, "
                  f"O={bar.open}, H={bar.high}, L={bar.low}, C={bar.close}, V={bar.volume}")

    def historicalDataEnd(self, reqId, start, end):
        print(f"[IBKRClient] historicalDataEnd: reqId={reqId}, start={start}, end={end}, bars={len(self.data)}")
        self.historical_data_finished = True


# ============================================================
# High-Level API Wrapper
# ============================================================

class IBKRApi:
    def __init__(self, host: str = None, port: int = None, client_id: int = 7):
        """
        host/port: TWS oder IBKR Gateway
        client_id: eine beliebige Zahl, die noch nicht verwendet wird
        """
        self.host = host or os.getenv("IBKR_SOCKET_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("IBKR_SOCKET_PORT", 7497))
        self.client_id = client_id

    def _run_loop(self, app: IBKRClient):
        app.run()

    def _start_app(self) -> IBKRClient:
        app = IBKRClient()
        print(f"[IBKRApi] Verbinde zu TWS: host={self.host}, port={self.port}, client_id={self.client_id}")
        app.connect(self.host, self.port, self.client_id)

        thread = threading.Thread(target=self._run_loop, args=(app,), daemon=True)
        thread.start()
        # kleine Pause, damit die Verbindung steht
        time.sleep(1.0)
        return app

    # -------------------------------------------------------
    # 1) conid besorgen
    # -------------------------------------------------------
    def get_conid(self, symbol: str) -> int:
        print(f"[IBKRApi] get_conid() für Symbol: {symbol}")
        app = self._start_app()

        sym = symbol.upper()

        # --- Markt-Logik ----------------------------------------------------
        # US-Aktien
        US_STOCKS = {
            "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "AMD", "GOOGL", "META", "NFLX",
            "SPY", "QQQ", "IWM"
        }

        # DAX / XETRA Aktien (EUR + IBIS)
        EU_XETRA = {
            "RHM", "SAP", "DTE", "SIE", "BAS", "BAYN", "BMW", "MBG", "VOW3", "VNA",
            "ALV", "DBK", "IFX", "MRK", "HEN3"
        }

        contract = Contract()
        contract.symbol = sym
        contract.secType = "STK"
        contract.exchange = "SMART"

        # --- 💡 Automatische Markterkennung -------------------------------
        if sym in US_STOCKS:
            contract.currency = "USD"
        elif sym in EU_XETRA:
            contract.currency = "EUR"
            contract.primaryExchange = "IBIS"  # Xetra
        else:
            # Fallback: erstmal USD probieren
            contract.currency = "USD"

        # Zustand zurücksetzen
        app.contract_details_received = False
        app.conid = None

        # Anfrage starten
        app.reqContractDetails(1, contract)

        # warten, bis contractDetails / contractDetailsEnd aufgerufen
        timeout = 10.0
        start = time.time()
        while not app.contract_details_received and (time.time() - start) < timeout:
            time.sleep(0.1)

        if app.conid is None:
            app.disconnect()
            raise RuntimeError(f"[IBKRApi] Keine conid für Symbol {symbol} erhalten.")

        conid = app.conid
        app.disconnect()
        print(f"[IBKRApi] get_conid() fertig – conid = {conid}")
        return conid

    # -------------------------------------------------------
    # 2) Historische Daten abrufen
    # -------------------------------------------------------
    def get_history(self, symbol: str, days: int = 90, bar_size: str = "1 day") -> List[Dict[str, Any]]:
        """
        Hol historische Daten über die Socket-API (nicht Client Portal HTTP).
        bar_size z.B.: "1 day", "1 hour", "15 mins"
        """
        print(f"[IBKRApi] get_history() startet für {symbol}, days={days}, bar_size={bar_size}")
        conid = self.get_conid(symbol)
        print(f"[IBKRApi] get_history() – benutze conid={conid}")

        app = self._start_app()

        app.data = []
        app.historical_data_finished = False

        contract = Contract()
        contract.conId = conid
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"

        app.reqHistoricalData(
            reqId=1,
            contract=contract,
            endDateTime="",
            durationStr=f"{days} D",
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=1,
            formatDate=1,
            keepUpToDate=False,
            chartOptions=[],
        )

        timeout = 60.0
        start = time.time()
        while not app.historical_data_finished and (time.time() - start) < timeout:
            time.sleep(0.2)

        data = app.data
        app.disconnect()
        print(f"[IBKRApi] get_history() – Anzahl empfangener Bars: {len(data)}")
        return data


# ============================================================
# DataAgent – Wrapper, den dein Orchestrator nutzt
# ============================================================

class DataAgent:
    """
    Höhere Abstraktion: liefert Marktdaten im einheitlichen Format:
    {
      "symbol": "...",
      "timeframe": "...",
      "candles": [ {timestamp, open, high, low, close, volume}, ... ],
      "orderbook": None,
      "meta": {...}
    }
    """

    def __init__(self, ibkr_api: Optional[IBKRApi] = None):
        self.api = ibkr_api or IBKRApi()

    def _map_timeframe_to_bar_size(self, timeframe: str) -> Tuple[str, int]:
        """
        Mappt dein timeframe (z.B. "1D", "1H", "15m") auf IBKR bar_size + geeignete Dauer in Tagen.
        """
        tf = timeframe.lower()
        if tf in ("1d", "d", "1day"):
            return "1 day", 180
        if tf in ("1h", "60m", "60min"):
            return "1 hour", 30
        if tf in ("15m", "15min"):
            return "15 mins", 10
        if tf in ("5m", "5min"):
            return "5 mins", 5
        # Fallback
        return "1 day", 180

    def fetch(self,
              symbol: str,
              asset_type: str = "stock",
              market_hint: str = "US",
              timeframe: str = "1D") -> Dict[str, Any]:

        if asset_type == "fx":
            # Für FX haben wir hier noch nichts angebunden
            raise NotImplementedError("FX über IBKRApi ist hier noch nicht implementiert.")

        bar_size, days = self._map_timeframe_to_bar_size(timeframe)
        raw_bars = self.api.get_history(symbol, days=days, bar_size=bar_size)

        candles = []
        for b in raw_bars:
            candles.append(
                {
                    "timestamp": b["timestamp"],
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b["volume"]),
                }
            )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "orderbook": None,
            "meta": {
                "source_api": "ibkr_socket",
                "market": market_hint,
                "days": days,
            },
        }


# ============================================================
# Kleiner Selbsttest (optional)
# ============================================================
if __name__ == "__main__":
    agent = DataAgent()
    print("Starte Test-Download von AAPL...")
    md = agent.fetch("AAPL", timeframe="1D")
    print("Symbol:", md["symbol"])
    print("Candles:", len(md["candles"]))
    if md["candles"]:
        print("Erste Candle:", md["candles"][0])