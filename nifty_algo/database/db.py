import sqlite3
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from .models import SCHEMA_SQL

logger = logging.getLogger("nifty_algo.db")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

def now_timestamps() -> Tuple[str, str]:
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    return now_utc.isoformat(), now_ist.strftime("%Y-%m-%d %H:%M:%S")

class DatabaseManager:
    """Production SQLite database manager with ACID transactions and crash recovery hooks."""

    def __init__(self, db_path: str = "nifty_algo_production.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")  # Write-Ahead Logging for high concurrency
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("SQLite database initialized at: %s (WAL mode active)", self.db_path)

    def log_audit(self, event_type: str, severity: str, message: str, metadata: Optional[Dict[str, Any]] = None):
        utc_ts, ist_ts = now_timestamps()
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_logs (timestamp_utc, timestamp_ist, event_type, severity, message, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (utc_ts, ist_ts, event_type, severity, message, json.dumps(metadata or {}))
                )
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)

    # ----------------- SESSION MANAGEMENT -----------------
    def get_or_create_daily_session(self, initial_capital: float) -> Dict[str, Any]:
        utc_ts, ist_ts = now_timestamps()
        today_date = ist_ts.split(" ")[0]
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trading_sessions WHERE date_ist = ?", (today_date,))
            row = cur.fetchone()
            if row:
                return dict(row)
            session_id = f"SES_{today_date}"
            cur.execute(
                """
                INSERT INTO trading_sessions 
                (session_id, date_ist, opened_at_utc, opened_at_ist, initial_capital, current_capital)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, today_date, utc_ts, ist_ts, initial_capital, initial_capital)
            )
            return {
                "session_id": session_id,
                "date_ist": today_date,
                "initial_capital": initial_capital,
                "current_capital": initial_capital,
                "consecutive_losses": 0,
                "is_trading_frozen": 0,
            }

    def update_session_pnl(self, date_ist: str, gross_pnl: float, net_pnl: float, is_loss: bool):
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT consecutive_losses, current_capital, total_trades FROM trading_sessions WHERE date_ist = ?", (date_ist,))
            row = cur.fetchone()
            if not row:
                return
            losses = row["consecutive_losses"]
            if is_loss:
                losses += 1
            else:
                losses = 0  # Profitable trade resets consecutive-loss counter per prompt rules
            new_capital = row["current_capital"] + net_pnl
            new_total = row["total_trades"] + 1
            is_frozen = 1 if losses >= 3 else 0
            freeze_reason = "3 consecutive losing completed trades reached" if is_frozen else None

            cur.execute(
                """
                UPDATE trading_sessions
                SET gross_pnl = gross_pnl + ?,
                    net_pnl = net_pnl + ?,
                    current_capital = ?,
                    total_trades = ?,
                    consecutive_losses = ?,
                    is_trading_frozen = CASE WHEN is_trading_frozen = 1 THEN 1 ELSE ? END,
                    freeze_reason = COALESCE(freeze_reason, ?)
                WHERE date_ist = ?
                """,
                (gross_pnl, net_pnl, new_capital, new_total, losses, is_frozen, freeze_reason, date_ist)
            )

    # ----------------- POSITION & ORDER RECOVERY -----------------
    def get_open_strategy_position(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM positions WHERE status IN ('PENDING_BUY', 'OPEN', 'PENDING_EXIT') LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None

    def create_position(self, pos: Dict[str, Any]):
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO positions (
                    position_id, trade_id, instrument_token, tradingsymbol, option_type,
                    strike, expiry, product, status, desired_quantity, filled_quantity,
                    remaining_quantity, buy_avg_price, target_price, opened_at_ist
                ) VALUES (
                    :position_id, :trade_id, :instrument_token, :tradingsymbol, :option_type,
                    :strike, :expiry, :product, :status, :desired_quantity, :filled_quantity,
                    :remaining_quantity, :buy_avg_price, :target_price, :opened_at_ist
                )
                """,
                pos
            )

    def update_position_fill(self, position_id: str, filled_qty: int, buy_avg: float, target_price: float):
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE positions
                SET filled_quantity = ?,
                    remaining_quantity = ?,
                    buy_avg_price = ?,
                    target_price = ?,
                    status = 'OPEN'
                WHERE position_id = ?
                """,
                (filled_qty, filled_qty, buy_avg, target_price, position_id)
            )

    def update_position_target(self, position_id: str, new_target_price: float):
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE positions
                SET target_price = ?
                WHERE position_id = ?
                """,
                (new_target_price, position_id)
            )

    def close_position(self, position_id: str, sell_avg: float, gross_pnl: float, net_pnl: float, charges: float, exit_reason: str):
        _, ist_ts = now_timestamps()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE positions
                SET status = 'CLOSED',
                    remaining_quantity = 0,
                    sell_avg_price = ?,
                    gross_pnl = ?,
                    net_pnl = ?,
                    charges = ?,
                    exit_reason = ?,
                    closed_at_ist = ?
                WHERE position_id = ?
                """,
                (sell_avg, gross_pnl, net_pnl, charges, exit_reason, ist_ts, position_id)
            )

    # ----------------- RECONCILIATION AUDIT -----------------
    def record_reconciliation(self, broker_qty: int, sqlite_qty: int, discrepancy: bool, action: str, details: Dict[str, Any]):
        _, ist_ts = now_timestamps()
        recon_id = f"REC_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO broker_reconciliations (recon_id, timestamp_ist, broker_net_quantity, sqlite_net_quantity, discrepancy_detected, resolution_action, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (recon_id, ist_ts, broker_qty, sqlite_qty, 1 if discrepancy else 0, action, json.dumps(details))
            )

    def get_recent_positions(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT position_id, trade_id, tradingsymbol, option_type, strike,
                       buy_avg_price, sell_avg_price, filled_quantity, gross_pnl, net_pnl,
                       charges, exit_reason, opened_at_ist, closed_at_ist, status
                FROM positions
                WHERE status = 'CLOSED'
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
