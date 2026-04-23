from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order as IBOrder
from ibapi.common import *
from ibapi.ticktype import *

import threading
import time
from typing import List, Dict, Any, Optional


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
        # Order tracking
        self.next_order_id: Optional[int] = None
        self.order_done: bool = False
        self.order_status_data: Dict[str, Any] = {}

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

    # -------- Order Callbacks ----------
    def nextValidId(self, orderId: int):
        self.next_order_id = orderId

    def openOrder(self, orderId, contract, order, orderState):
        self.order_status_data.update({
            "orderId": orderId,
            "status": orderState.status,
        })

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        self.order_status_data.update({
            "orderId": orderId,
            "status": status,
            "filled": float(filled),
            "remaining": float(remaining),
            "avgFillPrice": float(avgFillPrice),
        })
        if status in {"Filled", "Submitted", "PreSubmitted"}:
            self.order_done = True


# ============================================================
# High-Level API Wrapper
# ============================================================

class IBKRApi:
    _next_client_id = 7
    _client_id_lock = threading.Lock()

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = None):
        """
        host/port: TWS oder IBKR Gateway
        client_id: eine beliebige Zahl, die noch nicht verwendet wird
        """
        self.host = host
        self.port = port
        if client_id is None:
            with IBKRApi._client_id_lock:
                self.client_id = IBKRApi._next_client_id
                IBKRApi._next_client_id += 1
        else:
            self.client_id = client_id
        self._conid_cache: Dict[str, int] = {}  # symbol → conid

    def _run_loop(self, app: IBKRClient):
        app.run()

    def _start_app(self) -> IBKRClient:
        app = IBKRClient()
        with IBKRApi._client_id_lock:
            cid = IBKRApi._next_client_id
            IBKRApi._next_client_id += 1
        print(f"[IBKRApi] Verbinde zu TWS: host={self.host}, port={self.port}, client_id={cid}")
        app.connect(self.host, self.port, cid)

        thread = threading.Thread(target=self._run_loop, args=(app,), daemon=True)
        thread.start()
        # kleine Pause, damit die Verbindung steht
        time.sleep(1.0)
        return app

    # -------------------------------------------------------
    # 1) conid besorgen (mit Cache)
    # -------------------------------------------------------
    def get_conid(self, symbol: str) -> int:
        if symbol in self._conid_cache:
            print(f"[IBKRApi] get_conid() – Cache hit für {symbol}: {self._conid_cache[symbol]}")
            return self._conid_cache[symbol]

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
        self._conid_cache[symbol] = conid
        app.disconnect()
        print(f"[IBKRApi] get_conid() fertig – conid = {conid} (cached)")
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

    # -------------------------------------------------------
    # 3) Order platzieren via TWS Socket
    # -------------------------------------------------------
    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Platziert eine Order via TWS Socket (Paper/Live)."""
        conid = self.get_conid(symbol)
        app = self._start_app()

        app.next_order_id = None
        app.order_done = False
        app.order_status_data = {}

        app.reqIds(-1)
        deadline = time.time() + 10.0
        while app.next_order_id is None and time.time() < deadline:
            time.sleep(0.1)

        if app.next_order_id is None:
            app.disconnect()
            raise RuntimeError(f"[IBKRApi] nextValidId Timeout für {symbol}")

        contract = Contract()
        contract.conId = conid
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = currency

        order = IBOrder()
        order.action = side.upper()
        order.totalQuantity = qty
        order.orderType = order_type
        order.tif = "DAY"
        if order_type in {"LMT", "LIMIT"} and limit_price is not None:
            order.lmtPrice = round(float(limit_price), 2)

        order_id = app.next_order_id
        print(f"[IBKRApi] placeOrder: {side} {qty}x {symbol} "
              f"(conid={conid}, orderId={order_id}, type={order_type})")
        app.placeOrder(order_id, contract, order)

        deadline = time.time() + 15.0
        while not app.order_done and time.time() < deadline:
            time.sleep(0.2)

        result = dict(app.order_status_data)
        result.setdefault("orderId", order_id)
        app.disconnect()
        print(f"[IBKRApi] place_order Ergebnis: {result}")
        return result


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

    def _map_timeframe_to_yfinance(self, timeframe: str) -> (str, str):
        """
        Mappt timeframe (z.B. "1D", "1H", "15m") auf yfinance period + interval.
        """
        tf = timeframe.lower()
        if tf in ("1d", "d", "1day"):
            return "1y", "1d"
        if tf in ("1h", "60m", "60min"):
            return "60d", "1h"
        if tf in ("15m", "15min"):
            return "60d", "15m"
        if tf in ("5m", "5min"):
            return "30d", "5m"
        return "1y", "1d"

    def _fetch_yfinance_history(self, symbol: str, period: str, interval: str) -> List[Dict[str, Any]]:
        """
        Lädt historische Daten via yfinance (kostenlos, kein TWS nötig).
        """
        try:
            import yfinance as yf
        except ImportError:
            raise RuntimeError("yfinance fehlt. Installiere: pip install yfinance")

        print(f"[DataAgent] Lade {symbol} von yfinance (period={period}, interval={interval})")
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)

        if df.empty:
            raise RuntimeError(f"[DataAgent] Keine Daten für {symbol} von yfinance erhalten.")

        df = df.reset_index()
        date_col = "Datetime" if "Datetime" in df.columns else "Date"

        candles = []
        for _, row in df.iterrows():
            candles.append({
                "timestamp": str(row[date_col]),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })
        print(f"[DataAgent] {symbol}: {len(candles)} Kerzen geladen")
        return candles

    def fetch(self,
              symbol: str,
              asset_type: str = "stock",
              market_hint: str = "US",
              timeframe: str = "1D") -> Dict[str, Any]:

        if asset_type == "fx":
            raise NotImplementedError("FX ist noch nicht implementiert.")

        period, interval = self._map_timeframe_to_yfinance(timeframe)
        raw_bars = self._fetch_yfinance_history(symbol, period=period, interval=interval)

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
                "source_api": "yfinance",
                "market": market_hint,
                "period": period,
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