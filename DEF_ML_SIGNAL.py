"""
DEF_ML_SIGNAL.py

XGBoost-basiertes ML-Signal — ersetzt signal_scanner_agent.

Workflow:
  1. TRAIN_MODEL.py  →  trainiert Modell auf historischen Daten
  2. DEF_ML_SIGNAL.py →  lädt Modell, liefert Signal für aktuelle Candles

Features: RSI, MACD, ATR%, EMA-Ratio, BB, Volume, ADX, Stochastic
         + vergangene Returns + Lags + Markt-Kontext (VIX, SPY, Sektor)
Target:   Steigt der Kurs in forward_days Tagen um mehr als min_return?

Installation: pip install xgboost scikit-learn yfinance
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("MLSignalEngine")

MODEL_DIR = os.getenv("ML_MODEL_DIR", "models")

# ── Sektor-Mapping ────────────────────────────────────────────────────────────

_SECTOR_MAP: Dict[str, str] = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AMD": "XLK",
    "INTC": "XLK", "ORCL": "XLK", "CRM": "XLK", "ADBE": "XLK",
    "AVGO": "XLK", "QCOM": "XLK",
    "GOOGL": "XLC", "META": "XLC", "NFLX": "XLC", "DIS": "XLC", "CMCSA": "XLC",
    "TSLA": "XLY", "AMZN": "XLY", "HD": "XLY", "MCD": "XLY", "NKE": "XLY",
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "V": "XLF", "MA": "XLF",
    "MS": "XLF", "BLK": "XLF", "AXP": "XLF",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE",
    "JNJ": "XLV", "UNH": "XLV", "PFE": "XLV", "ABBV": "XLV", "TMO": "XLV",
    "MRK": "XLV", "LLY": "XLV",
    "WMT": "XLP", "KO": "XLP", "PEP": "XLP", "COST": "XLP", "PG": "XLP",
    "CAT": "XLI", "BA": "XLI", "HON": "XLI", "UPS": "XLI",
}


def _get_sector_etf(symbol: str) -> str:
    return _SECTOR_MAP.get(symbol.upper(), "SPY")


# ── Markt-Kontext ─────────────────────────────────────────────────────────────

def _build_market_ctx(
    vix_candles: List[Dict],
    spy_candles: List[Dict],
    sector_candles: Optional[List[Dict]] = None,
) -> pd.DataFrame:
    """
    Baut Markt-Kontext DataFrame (Index = normalisiertes Datum).
    Spalten: vix_level, vix_change_5d, spy_ema_ratio, spy_vs_ema200_pct, sector_rel_5d
    """
    try:
        import pandas_ta as ta
    except ImportError:
        return pd.DataFrame()

    if not vix_candles or not spy_candles:
        return pd.DataFrame()

    def _to_series(candles: List[Dict], col: str = "close") -> pd.Series:
        df = pd.DataFrame(candles)[["timestamp", col]].copy()
        df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.normalize().dt.tz_localize(None)
        df = df.drop_duplicates("date").set_index("date").sort_index()
        return df[col].astype(float)

    vix_c = _to_series(vix_candles)
    spy_c = _to_series(spy_candles)

    ctx = pd.DataFrame(index=spy_c.index)
    # Forward-fill VIX so holidays don't create NaN gaps
    vix_aligned = vix_c.reindex(ctx.index).ffill()
    ctx["vix_level"]     = vix_aligned
    ctx["vix_change_5d"] = vix_aligned.pct_change(5) * 100

    ema20  = ta.ema(spy_c, length=20)
    ema50  = ta.ema(spy_c, length=50)
    ema200 = ta.ema(spy_c, length=200)

    # Guard against None (pandas-ta returns None when series too short)
    if ema20 is not None and ema50 is not None:
        ema50_safe = ema50.replace(0, float("nan"))
        ctx["spy_ema_ratio"] = (ema20 / ema50_safe).values
    else:
        ctx["spy_ema_ratio"] = float("nan")

    if ema200 is not None:
        ema200_safe = ema200.replace(0, float("nan"))
        ctx["spy_vs_ema200_pct"] = ((spy_c - ema200_safe) / ema200_safe * 100).values
    else:
        ctx["spy_vs_ema200_pct"] = float("nan")

    spy_ret5 = spy_c.pct_change(5)

    if sector_candles:
        sec_c    = _to_series(sector_candles)
        sec_ret5 = sec_c.pct_change(5).reindex(ctx.index)
        ctx["sector_rel_5d"] = (sec_ret5 - spy_ret5).values * 100
    else:
        ctx["sector_rel_5d"] = 0.0

    return ctx


# ── Live-Marktkontext-Cache (für predict()) ───────────────────────────────────

_CTX_CACHE: Dict[str, Any] = {}
_CTX_TTL = 900  # 15 Minuten


def _fetch_live_market_ctx(sector_etf: str = "SPY") -> Optional[pd.DataFrame]:
    """Lädt VIX + SPY + Sektor-ETF für letzte 3 Monate via yfinance, gecacht."""
    cache_key = sector_etf
    cached = _CTX_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CTX_TTL:
        return cached["df"]

    try:
        import yfinance as yf

        def _yf_candles(ticker: str) -> List[Dict]:
            df = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
            if df is None or df.empty:
                return []
            df = df.reset_index()
            ts_col = "Datetime" if "Datetime" in df.columns else "Date"
            return [
                {
                    "timestamp": str(row[ts_col]),
                    "close": float(row["Close"]),
                }
                for _, row in df.iterrows()
            ]

        vix_c = _yf_candles("^VIX")
        spy_c = _yf_candles("SPY")
        sec_c = _yf_candles(sector_etf) if sector_etf != "SPY" else None

        ctx = _build_market_ctx(vix_c, spy_c, sec_c)
        _CTX_CACHE[cache_key] = {"df": ctx, "ts": time.time()}
        return ctx

    except Exception as exc:
        logger.warning("[ML] Live-Marktkontext Fehler: %s", exc)
        return None


# ── Feature-Engineering ───────────────────────────────────────────────────────

def _build_feature_df(
    candles: List[Dict[str, Any]],
    market_ctx: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Baut stationäre Feature-Matrix aus OHLCV-Candles + optionalem Markt-Kontext.
    Keine Rohpreise oder absolute EMA-Werte — nur Ratios und %.
    """
    try:
        import pandas_ta as ta
    except ImportError:
        raise RuntimeError("pandas-ta fehlt: pip install pandas-ta")

    df = pd.DataFrame(candles).copy()
    df[["open", "high", "low", "close", "volume"]] = \
        df[["open", "high", "low", "close", "volume"]].astype(float)

    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]

    # ── Indikatoren ───────────────────────────────────────────────────────────
    df["rsi"] = ta.rsi(c, length=14)

    macd_df = ta.macd(c, fast=12, slow=26, signal=9)
    if macd_df is not None and not macd_df.empty:
        cols = macd_df.columns.tolist()
        df["macd"]      = macd_df[cols[0]]
        df["macd_sig"]  = macd_df[cols[2]]
        df["macd_hist"] = macd_df[cols[1]]

    atr = ta.atr(h, l, c, length=14)
    df["atr_pct"] = atr / c * 100

    ema20  = ta.ema(c, length=20)
    ema50  = ta.ema(c, length=50)
    df["ema_ratio"]       = ema20 / ema50
    df["price_ema20_pct"] = (c - ema20) / ema20 * 100

    bb = ta.bbands(c, length=20, std=2)
    if bb is not None and not bb.empty:
        cols = bb.columns.tolist()
        df["bb_pct"] = bb[cols[4]]
        df["bb_bw"]  = bb[cols[3]]

    vol_ma = ta.sma(v, length=20)
    df["vol_ratio"] = v / vol_ma

    adx_df = ta.adx(h, l, c, length=14)
    if adx_df is not None and not adx_df.empty:
        df["adx"] = adx_df[adx_df.columns[0]]

    stoch = ta.stoch(h, l, c, k=14, d=3, smooth_k=3)
    if stoch is not None and not stoch.empty:
        cols = stoch.columns.tolist()
        df["stoch_k"] = stoch[cols[0]]
        df["stoch_d"] = stoch[cols[1]]

    # ── Vergangene Returns ────────────────────────────────────────────────────
    for n in [1, 3, 5, 10, 20]:
        df[f"ret_{n}d"] = c.pct_change(n) * 100

    # ── Lags (erweitert) ──────────────────────────────────────────────────────
    for col in ["rsi", "macd_hist", "vol_ratio", "bb_pct"]:
        if col in df.columns:
            for lag in [1, 3, 5, 10, 20]:
                df[f"{col}_lag{lag}"] = df[col].shift(lag)

    # ── Kalender-Effekte ──────────────────────────────────────────────────────
    try:
        df["day_of_week"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
    except Exception:
        df["day_of_week"] = 0

    # ── Markt-Kontext einmergen ───────────────────────────────────────────────
    if market_ctx is not None and not market_ctx.empty:
        try:
            df["_date"] = pd.to_datetime(df["timestamp"], utc=True).dt.normalize().dt.tz_localize(None)
            df = df.merge(market_ctx, left_on="_date", right_index=True, how="left")
            df = df.drop(columns=["_date"])
        except Exception as exc:
            logger.warning("[ML] market_ctx merge fehlgeschlagen: %s", exc)

    return df


def _feature_columns(df: pd.DataFrame) -> List[str]:
    """Alle Feature-Spalten (keine Rohpreise, kein Ziel, kein Timestamp)."""
    exclude = {"timestamp", "open", "high", "low", "close", "volume", "target", "symbol"}
    return [c for c in df.columns if c not in exclude]


# ── MLSignalEngine ────────────────────────────────────────────────────────────

class MLSignalEngine:
    """
    Öffentliche API:
      train(symbols_candles, market_ctx_by_sector) → trainiert und speichert Modell
      predict(candles, symbol)                      → liefert Signal-Dict
      save(name) / load(name)                       → Modell-Persistenz
    """

    def __init__(self, model_dir: str = MODEL_DIR) -> None:
        self.model_dir = model_dir
        self.model = None
        self.feature_cols: List[str] = []

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        symbols_candles: Dict[str, List[Dict]],
        market_ctx_by_sector: Optional[Dict[str, pd.DataFrame]] = None,
        forward_days: int = 5,
        min_return: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Trainiert XGBoost auf mehreren Symbolen gleichzeitig.

        Args:
            symbols_candles:      {symbol: candles_list}
            market_ctx_by_sector: {sector_etf: ctx_df} — optional, aus TRAIN_MODEL.py
            forward_days:         Vorhersage-Horizont (Tage)
            min_return:           Mindest-Return für positives Label
        """
        try:
            import xgboost as xgb
            from sklearn.metrics import roc_auc_score
            from sklearn.model_selection import TimeSeriesSplit
        except ImportError:
            raise RuntimeError("xgboost / scikit-learn fehlt: pip install xgboost scikit-learn")

        frames: List[pd.DataFrame] = []
        for sym, candles in symbols_candles.items():
            if len(candles) < 60:
                logger.warning("[ML] %s: zu wenige Candles (%d) – überspringe.", sym, len(candles))
                continue

            ctx: Optional[pd.DataFrame] = None
            if market_ctx_by_sector:
                sector = _get_sector_etf(sym)
                ctx = market_ctx_by_sector.get(sector)
                if ctx is None:
                    ctx = market_ctx_by_sector.get("SPY")

            df = _build_feature_df(candles, market_ctx=ctx)
            df["target"] = (
                df["close"].shift(-forward_days) > df["close"] * (1 + min_return)
            ).astype(int)
            df["symbol"] = sym
            frames.append(df)

        if not frames:
            raise ValueError("Keine verwendbaren Symbol-Daten.")

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        feat_cols = _feature_columns(combined)
        combined  = combined.dropna(subset=feat_cols + ["target"])

        X = combined[feat_cols].astype(float)
        y = combined["target"]

        if len(X) < 200:
            raise ValueError(f"Zu wenige Samples ({len(X)}). Mehr Symbole oder längeren Zeitraum.")

        self.feature_cols = feat_cols

        split_idx = int(len(X) * 0.80)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        pos_count = int(y_train.sum())
        neg_count = len(y_train) - pos_count
        scale_pw  = neg_count / max(pos_count, 1)

        model = xgb.XGBClassifier(
            n_estimators=500,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.7,
            min_child_weight=3,
            reg_alpha=0.05,
            reg_lambda=1.0,
            scale_pos_weight=scale_pw,
            random_state=42,
            eval_metric="auc",
            early_stopping_rounds=50,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        acc    = float((y_pred == y_test).mean())
        try:
            auc = float(roc_auc_score(y_test, y_prob))
        except Exception:
            auc = 0.0

        tscv    = TimeSeriesSplit(n_splits=5)
        cv_accs = []
        for tr_idx, va_idx in tscv.split(X):
            m = xgb.XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.03,
                scale_pos_weight=scale_pw, random_state=42, eval_metric="auc",
            )
            m.fit(X.iloc[tr_idx], y.iloc[tr_idx], verbose=False)
            cv_accs.append(float((m.predict(X.iloc[va_idx]) == y.iloc[va_idx]).mean()))

        final_model = xgb.XGBClassifier(
            n_estimators=max(100, int(model.best_iteration * 1.1) + 1),
            max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.7,
            min_child_weight=3, reg_alpha=0.05, reg_lambda=1.0,
            scale_pos_weight=scale_pw, random_state=42, eval_metric="auc",
        )
        final_model.fit(X, y, verbose=False)
        self.model = final_model

        imp          = final_model.feature_importances_
        top_features = sorted(zip(feat_cols, imp.tolist()), key=lambda x: x[1], reverse=True)[:15]

        return {
            "n_samples":        len(X),
            "n_features":       len(feat_cols),
            "n_symbols":        len(frames),
            "test_accuracy":    round(acc, 4),
            "auc_roc":          round(auc, 4),
            "cv_accuracy_mean": round(float(pd.Series(cv_accs).mean()), 4),
            "cv_accuracy_std":  round(float(pd.Series(cv_accs).std()), 4),
            "top_features":     top_features,
            "forward_days":     forward_days,
            "min_return":       min_return,
            "best_iteration":   model.best_iteration,
        }

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(self, candles: List[Dict[str, Any]], symbol: str = "") -> Dict[str, Any]:
        """Liefert Signal-Dict — Drop-in-Ersatz für signal_scanner_agent."""
        if self.model is None:
            return {
                "short_term_signal": "none", "confidence": 0.0,
                "buy_probability": 0.5, "entry_style": "none",
                "reasons": ["ML-Modell nicht geladen – run TRAIN_MODEL.py"],
                "invalidating_conditions": [], "source": "ml_not_loaded",
            }

        if len(candles) < 60:
            return {
                "short_term_signal": "none", "confidence": 0.0,
                "buy_probability": 0.5, "entry_style": "none",
                "reasons": [f"Zu wenige Candles ({len(candles)})"],
                "invalidating_conditions": [], "source": "ml_insufficient_data",
            }

        try:
            sector_etf = _get_sector_etf(symbol) if symbol else "SPY"
            market_ctx = _fetch_live_market_ctx(sector_etf)

            df  = _build_feature_df(candles, market_ctx=market_ctx)
            # Nur Spalten verwenden die das Modell kennt
            available = [c for c in self.feature_cols if c in df.columns]
            missing   = [c for c in self.feature_cols if c not in df.columns]
            if missing:
                for col in missing:
                    df[col] = 0.0

            df = df.dropna(subset=available)
            if df.empty:
                raise ValueError("Alle Rows nach dropna leer.")

            X        = df[self.feature_cols].astype(float).iloc[[-1]]
            buy_prob = float(self.model.predict_proba(X)[0][1])

        except Exception as exc:
            logger.warning("[ML] predict Fehler: %s", exc)
            return {
                "short_term_signal": "none", "confidence": 0.0,
                "buy_probability": 0.5, "entry_style": "none",
                "reasons": [f"Fehler: {exc}"],
                "invalidating_conditions": [], "source": "ml_error",
            }

        if buy_prob >= 0.60:
            signal, confidence, style = "bullish", round(buy_prob, 3), "breakout"
        elif buy_prob <= 0.38:
            signal, confidence, style = "bearish", round(1.0 - buy_prob, 3), "breakdown"
        else:
            signal, confidence, style = "none", round(abs(buy_prob - 0.5) * 2, 3), "none"

        last_row = df.iloc[-1]
        top3 = []
        imp_pairs = sorted(
            zip(self.feature_cols, self.model.feature_importances_),
            key=lambda x: x[1], reverse=True,
        )[:3]
        for feat, _ in imp_pairs:
            val = last_row.get(feat, "n/a")
            top3.append(f"{feat}={round(float(val), 3) if isinstance(val, (int, float)) else val}")

        return {
            "symbol":            symbol,
            "short_term_signal": signal,
            "confidence":        confidence,
            "buy_probability":   round(buy_prob, 3),
            "entry_style":       style,
            "reasons":           [f"XGBoost buy_prob={buy_prob:.3f}"] + top3,
            "invalidating_conditions": [],
            "source":            "xgboost_ml_v2",
        }

    # ── Persistenz ────────────────────────────────────────────────────────────

    def save(self, name: str = "universal") -> None:
        try:
            import joblib
        except ImportError:
            raise RuntimeError("joblib fehlt: pip install scikit-learn")
        os.makedirs(self.model_dir, exist_ok=True)
        joblib.dump(self.model, f"{self.model_dir}/{name}_model.joblib")
        with open(f"{self.model_dir}/{name}_features.json", "w") as f:
            json.dump(self.feature_cols, f, indent=2)
        logger.info("[ML] Modell gespeichert: %s/%s_model.joblib", self.model_dir, name)

    def load(self, name: str = "universal") -> bool:
        try:
            import joblib
        except ImportError:
            logger.warning("[ML] joblib fehlt – Modell nicht geladen.")
            return False

        model_path   = f"{self.model_dir}/{name}_model.joblib"
        feature_path = f"{self.model_dir}/{name}_features.json"

        if not os.path.exists(model_path):
            logger.info("[ML] Kein Modell unter %s – bitte TRAIN_MODEL.py ausführen.", model_path)
            return False

        try:
            self.model = joblib.load(model_path)
            with open(feature_path) as f:
                self.feature_cols = json.load(f)
            logger.info("[ML] Modell geladen: %s (%d Features)", model_path, len(self.feature_cols))
            return True
        except Exception as exc:
            logger.error("[ML] Laden fehlgeschlagen: %s", exc)
            return False

    @property
    def is_loaded(self) -> bool:
        return self.model is not None and len(self.feature_cols) > 0


# ── Modul-Singleton ───────────────────────────────────────────────────────────

_engine = MLSignalEngine()
_engine.load("universal")
