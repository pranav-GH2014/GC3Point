"""
Database schema definition and SQL migrations for SQLite persistence.
Enforces foreign keys, indexes, and uniqueness constraints.
"""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- Daily Trading Sessions
CREATE TABLE IF NOT EXISTS trading_sessions (
    session_id TEXT PRIMARY KEY,
    date_ist TEXT NOT NULL UNIQUE,
    opened_at_utc TEXT NOT NULL,
    opened_at_ist TEXT NOT NULL,
    closed_at_utc TEXT,
    closed_at_ist TEXT,
    initial_capital REAL NOT NULL,
    current_capital REAL NOT NULL,
    gross_pnl REAL DEFAULT 0.0,
    net_pnl REAL DEFAULT 0.0,
    total_trades INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    is_trading_frozen INTEGER DEFAULT 0,
    freeze_reason TEXT
);

-- Market Signals & Evaluations
CREATE TABLE IF NOT EXISTS market_signals (
    signal_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    timestamp_ist TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL, -- 'BULLISH' (CE) or 'BEARISH' (PE)
    underlying_price REAL NOT NULL,
    confidence_score REAL NOT NULL,
    is_eligible INTEGER NOT NULL, -- 1 if score >= 80, 0 otherwise
    primary_setup_id TEXT NOT NULL,
    contributing_setups_json TEXT,
    indicators_json TEXT,
    market_structure_json TEXT,
    veto_reason TEXT
);

-- Strategy Positions (Strictly ONE open position at a time)
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    instrument_token INTEGER NOT NULL,
    tradingsymbol TEXT NOT NULL,
    option_type TEXT NOT NULL, -- 'CE' or 'PE'
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    product TEXT NOT NULL DEFAULT 'NRML',
    status TEXT NOT NULL, -- 'PENDING_BUY', 'OPEN', 'PENDING_EXIT', 'CLOSED', 'CANCELLED', 'RECON_FREEZE'
    desired_quantity INTEGER NOT NULL,
    filled_quantity INTEGER DEFAULT 0,
    remaining_quantity INTEGER DEFAULT 0,
    buy_avg_price REAL DEFAULT 0.0,
    sell_avg_price REAL DEFAULT 0.0,
    target_price REAL DEFAULT 0.0,
    stop_loss_price REAL,
    opened_at_ist TEXT NOT NULL,
    closed_at_ist TEXT,
    gross_pnl REAL DEFAULT 0.0,
    net_pnl REAL DEFAULT 0.0,
    charges REAL DEFAULT 0.0,
    exit_reason TEXT,
    is_overnight INTEGER DEFAULT 0
);

-- Orders Table (Traceable to position and trade)
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    broker_order_id TEXT UNIQUE,
    position_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    tradingsymbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'NFO',
    transaction_type TEXT NOT NULL, -- 'BUY' or 'SELL'
    order_type TEXT NOT NULL DEFAULT 'LIMIT',
    product TEXT NOT NULL DEFAULT 'NRML',
    requested_price REAL NOT NULL,
    requested_quantity INTEGER NOT NULL,
    filled_quantity INTEGER DEFAULT 0,
    average_price REAL DEFAULT 0.0,
    status TEXT NOT NULL, -- 'PLACED', 'COMPLETE', 'CANCELLED', 'REJECTED'
    status_message TEXT,
    placed_at_ist TEXT NOT NULL,
    updated_at_ist TEXT NOT NULL,
    FOREIGN KEY(position_id) REFERENCES positions(position_id)
);

-- Trades / Execution Fills (Individual executions from Zerodha)
CREATE TABLE IF NOT EXISTS order_fills (
    fill_id TEXT PRIMARY KEY,
    broker_trade_id TEXT UNIQUE,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    fill_time_ist TEXT NOT NULL,
    FOREIGN KEY(client_order_id) REFERENCES orders(client_order_id),
    FOREIGN KEY(position_id) REFERENCES positions(position_id)
);

-- Cooldown Tracking Periods
CREATE TABLE IF NOT EXISTS cooldown_periods (
    cooldown_id TEXT PRIMARY KEY,
    started_at_ist TEXT NOT NULL,
    expires_at_ist TEXT NOT NULL,
    reason TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

-- Post-Target Market Movement Observations (Mandatory Analytics for +3 Exit)
CREATE TABLE IF NOT EXISTS post_target_observations (
    observation_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    position_id TEXT NOT NULL,
    tradingsymbol TEXT NOT NULL,
    buy_avg_price REAL NOT NULL,
    actual_exit_price REAL NOT NULL,
    target_exit_time_ist TEXT NOT NULL,
    exit_quantity INTEGER NOT NULL,
    gross_pnl REAL NOT NULL,
    net_pnl REAL NOT NULL,
    post_exit_high_premium REAL,
    time_to_post_exit_high_sec REAL,
    additional_premium_pts REAL,
    reached_plus_5 INTEGER DEFAULT 0,
    reached_plus_7 INTEGER DEFAULT 0,
    reached_plus_10 INTEGER DEFAULT 0,
    reached_plus_15 INTEGER DEFAULT 0,
    reversed_below_plus_3 INTEGER DEFAULT 0,
    max_adverse_move_after_high REAL DEFAULT 0.0,
    premium_1m REAL,
    premium_3m REAL,
    premium_5m REAL,
    premium_10m REAL,
    premium_15m REAL,
    premium_30m REAL,
    nifty_underlying_at_exit REAL,
    nifty_underlying_after_30m REAL,
    nifty_direction_post_exit TEXT,
    monitoring_stopped_reason TEXT,
    updated_at_ist TEXT NOT NULL,
    FOREIGN KEY(position_id) REFERENCES positions(position_id)
);

-- Broker Reconciliation Audit Logs
CREATE TABLE IF NOT EXISTS broker_reconciliations (
    recon_id TEXT PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    broker_net_quantity INTEGER NOT NULL,
    sqlite_net_quantity INTEGER NOT NULL,
    discrepancy_detected INTEGER NOT NULL,
    resolution_action TEXT NOT NULL,
    details_json TEXT
);

-- System Audit and Recovery Events
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    timestamp_ist TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL, -- 'INFO', 'WARN', 'ERROR', 'CRITICAL'
    message TEXT NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_orders_broker_id ON orders(broker_order_id);
CREATE INDEX IF NOT EXISTS idx_signals_time ON market_signals(timestamp_ist);
CREATE INDEX IF NOT EXISTS idx_post_target_trade ON post_target_observations(trade_id);
"""
