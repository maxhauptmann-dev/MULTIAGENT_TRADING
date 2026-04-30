-- Database Schema for Hourly Options Trading System
-- SQLite compatible

-- Signals table: Generated signals from StrategyEngine
CREATE TABLE IF NOT EXISTS hourly_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,  -- bull_call_spread, bear_put_spread, etc.
    direction TEXT NOT NULL,  -- bullish, bearish, neutral, income
    confidence REAL NOT NULL,
    signal_strength REAL NOT NULL,
    entry_reason TEXT,
    iv_percentile REAL,
    volatility_regime TEXT,
    recommended_contracts INTEGER,
    recommended_dte INTEGER,
    max_risk REAL,
    target_profit REAL,
    status TEXT DEFAULT 'generated',  -- generated, validated, executed, rejected
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP,
    UNIQUE(cycle_id, symbol, strategy)
);

-- Strategy executions: Actual trade orders placed
CREATE TABLE IF NOT EXISTS executed_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    contracts INTEGER,
    entry_price REAL,
    entry_timestamp TIMESTAMP,
    exit_price REAL,
    exit_timestamp TIMESTAMP,
    pnl REAL,
    pnl_percent REAL,
    status TEXT DEFAULT 'open',  -- open, closed, cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (signal_id) REFERENCES hourly_signals(id)
);

-- Strategy legs: Individual option legs for multi-leg strategies
CREATE TABLE IF NOT EXISTS strategy_legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER NOT NULL,
    option_type TEXT NOT NULL,  -- call, put
    strike REAL NOT NULL,
    dte INTEGER,
    side TEXT NOT NULL,  -- long, short
    quantity INTEGER NOT NULL,
    delta_target REAL,
    premium REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES executed_strategies(id)
);

-- Portfolio history: Track daily P&L and Greeks
CREATE TABLE IF NOT EXISTS portfolio_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_delta REAL,
    total_gamma REAL,
    total_theta REAL,
    total_vega REAL,
    open_positions INTEGER,
    daily_pnl REAL,
    cumulative_pnl REAL,
    margin_used_pct REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cycle history: Track each hourly cycle execution
CREATE TABLE IF NOT EXISTS cycle_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL UNIQUE,
    symbols_analyzed INTEGER,
    signals_generated INTEGER,
    signals_executed INTEGER,
    signals_rejected INTEGER,
    portfolio_delta REAL,
    portfolio_theta REAL,
    cycle_duration_seconds REAL,
    errors TEXT,  -- JSON array of error messages
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON hourly_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_status ON hourly_signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_created ON hourly_signals(created_at);
CREATE INDEX IF NOT EXISTS idx_executions_symbol ON executed_strategies(symbol);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executed_strategies(status);
CREATE INDEX IF NOT EXISTS idx_portfolio_date ON portfolio_history(date);
CREATE INDEX IF NOT EXISTS idx_cycles_created ON cycle_history(created_at);
