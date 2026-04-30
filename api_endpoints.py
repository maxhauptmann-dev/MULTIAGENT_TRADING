"""
API Endpoints for Dashboard Integration
Flask endpoints for orchestrator status, signals, and portfolio Greeks
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

try:
    from flask import Flask, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class OrchestratorAPI:
    """REST API for TradingOrchestrator status and signals"""

    def __init__(self, orchestrator, db_path: str = "trading.db"):
        self.orchestrator = orchestrator
        self.db_path = db_path
        self.app = None

        if FLASK_AVAILABLE:
            self._init_flask()

    def _init_flask(self):
        """Initialize Flask application with routes"""
        self.app = Flask(__name__)

        # Orchestrator status endpoint
        @self.app.route("/orchestrator/status", methods=["GET"])
        def orchestrator_status():
            """Get last cycle status and portfolio state"""
            cycle = self.orchestrator.get_last_cycle_result()
            portfolio = self.orchestrator.get_portfolio_status()

            return jsonify({
                "status": "running",
                "last_cycle": cycle,
                "portfolio": portfolio,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Signals endpoints
        @self.app.route("/signals/last_hour", methods=["GET"])
        def signals_last_hour():
            """Get signals from last hour"""
            return jsonify(self._get_signals_last_hour())

        @self.app.route("/signals/by_strategy/<strategy>", methods=["GET"])
        def signals_by_strategy(strategy):
            """Get signals filtered by strategy"""
            return jsonify(self._get_signals_by_strategy(strategy))

        # Portfolio endpoints
        @self.app.route("/portfolio/greeks", methods=["GET"])
        def portfolio_greeks():
            """Get current portfolio Greeks"""
            portfolio = self.orchestrator.get_portfolio_status()
            return jsonify({
                "delta": portfolio.get("delta", 0),
                "gamma": portfolio.get("gamma", 0),
                "theta_per_day": portfolio.get("theta_per_day", 0),
                "vega": portfolio.get("vega", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        @self.app.route("/portfolio/limit_status", methods=["GET"])
        def portfolio_limit_status():
            """Get portfolio limit utilization"""
            portfolio = self.orchestrator.get_portfolio_status()

            limits = {
                "max_delta": 0.30,
                "current_delta": portfolio.get("delta", 0),
                "delta_utilization": abs(portfolio.get("delta", 0)) / 0.30,

                "max_theta_day": 500.0,
                "current_theta": portfolio.get("theta_per_day", 0),
                "theta_utilization": abs(portfolio.get("theta_per_day", 0)) / 500.0,

                "max_positions": 5,
                "current_positions": portfolio.get("positions", 0),
                "position_utilization": portfolio.get("positions", 0) / 5,

                "margin_used": portfolio.get("margin_used", "0%"),
            }

            return jsonify(limits)

        # Paper Trading endpoints
        @self.app.route("/paper_trading/stats", methods=["GET"])
        def paper_trading_stats():
            """Get paper trading performance statistics"""
            stats = self.orchestrator.get_paper_trading_stats()
            return jsonify(stats)

    def _get_signals_last_hour(self) -> Dict[str, Any]:
        """Query signals from last hour"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

            cursor.execute(
                """
                SELECT symbol, strategy, direction, confidence, signal_strength,
                       status, created_at
                FROM hourly_signals
                WHERE created_at > ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (one_hour_ago,),
            )

            signals = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return {
                "signals": signals,
                "count": len(signals),
                "period": "last_hour",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e), "signals": []}

    def _get_signals_by_strategy(self, strategy: str) -> Dict[str, Any]:
        """Query signals by strategy type"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT symbol, strategy, direction, confidence, signal_strength,
                       status, created_at
                FROM hourly_signals
                WHERE strategy = ?
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (strategy,),
            )

            signals = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return {
                "strategy": strategy,
                "signals": signals,
                "count": len(signals),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e), "signals": []}

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
        """Run Flask API server"""
        if not self.app:
            raise RuntimeError("Flask not available")

        self.app.run(host=host, port=port, debug=debug)


# ============================================================
# Database Helper Functions
# ============================================================

def init_database(db_path: str = "trading.db"):
    """Initialize database with schema"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Read and execute schema
        with open("database_schema.sql", "r") as f:
            schema = f.read()

        cursor.executescript(schema)
        conn.commit()
        conn.close()

        print(f"Database initialized: {db_path}")
    except Exception as e:
        print(f"Database initialization error: {e}")


def save_signal(
    db_path: str,
    cycle_id: str,
    signal: "Signal",  # From strategy_engine
) -> int:
    """Save signal to database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO hourly_signals
            (cycle_id, symbol, strategy, direction, confidence, signal_strength,
             entry_reason, iv_percentile, volatility_regime, recommended_contracts,
             recommended_dte, max_risk, target_profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle_id,
                signal.symbol,
                signal.strategy.value,
                signal.direction,
                signal.confidence,
                signal.signal_strength,
                signal.entry_reason,
                signal.iv_percentile,
                signal.volatility_regime,
                signal.recommended_contracts,
                signal.recommended_dte,
                signal.max_risk,
                signal.target_profit,
            ),
        )

        conn.commit()
        signal_id = cursor.lastrowid
        conn.close()

        return signal_id
    except Exception as e:
        print(f"Error saving signal: {e}")
        return 0


def save_cycle_result(
    db_path: str,
    cycle_result,  # From orchestrator CycleResult
) -> bool:
    """Save cycle result to database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO cycle_history
            (cycle_id, symbols_analyzed, signals_generated, signals_executed,
             signals_rejected, portfolio_delta, portfolio_theta, cycle_duration_seconds,
             errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle_result.cycle_id,
                cycle_result.symbols_analyzed,
                cycle_result.signals_generated,
                cycle_result.signals_executed,
                cycle_result.signals_rejected,
                cycle_result.portfolio_delta,
                cycle_result.portfolio_theta,
                cycle_result.duration_seconds,
                json.dumps(cycle_result.errors),
            ),
        )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving cycle result: {e}")
        return False


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    print("OrchestratorAPI initialized (Flask-aware)")

    if FLASK_AVAILABLE:
        print("Flask is available - API endpoints would be registered")
    else:
        print("Flask not installed - API endpoints disabled")
        print("Install: pip install flask")
