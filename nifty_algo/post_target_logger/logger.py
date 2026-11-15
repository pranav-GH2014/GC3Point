import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from ..database.db import DatabaseManager

logger = logging.getLogger("nifty_algo.post_target")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

class PostTargetMovementLogger:
    """
    Mandatory analytics engine tracking post-+3 exit premium progression.
    Stores milestones (+5, +7, +10, +15) and timed snapshots (1, 3, 5, 10, 15, 30 min).
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        # Active monitoring tasks: { trade_id: { observation_data } }
        self.active_monitors: Dict[str, Dict[str, Any]] = {}

    def start_monitoring(
        self,
        trade_id: str,
        position_id: str,
        tradingsymbol: str,
        buy_avg: float,
        actual_exit_price: float,
        exit_quantity: int,
        gross_pnl: float,
        net_pnl: float,
        nifty_underlying_exit: float
    ):
        exit_time = time.time()
        obs_id = f"OBS_{trade_id}"
        self.active_monitors[trade_id] = {
            "observation_id": obs_id,
            "trade_id": trade_id,
            "position_id": position_id,
            "tradingsymbol": tradingsymbol,
            "buy_avg_price": buy_avg,
            "actual_exit_price": actual_exit_price,
            "exit_time_sec": exit_time,
            "target_exit_time_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
            "exit_quantity": exit_quantity,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "nifty_underlying_at_exit": nifty_underlying_exit,
            "post_exit_high_premium": actual_exit_price,
            "time_to_post_exit_high_sec": 0.0,
            "additional_premium_pts": 0.0,
            "reached_plus_5": 0,
            "reached_plus_7": 0,
            "reached_plus_10": 0,
            "reached_plus_15": 0,
            "reversed_below_plus_3": 0,
            "max_adverse_move_after_high": 0.0,
            "premium_1m": None,
            "premium_3m": None,
            "premium_5m": None,
            "premium_10m": None,
            "premium_15m": None,
            "premium_30m": None,
            "nifty_underlying_after_30m": None,
            "nifty_direction_post_exit": "UNKNOWN",
            "monitoring_stopped_reason": None,
        }
        logger.info(
            "[POST-TARGET MONITOR STARTED] Tracking %s post-exit (Buy: ₹%.2f, Exit: ₹%.2f, Trade: %s)",
            tradingsymbol, buy_avg, actual_exit_price, trade_id
        )

    def on_tick(self, tradingsymbol: str, current_ltp: float, nifty_spot: float):
        """Processes live option tick and updates excursion metrics."""
        for trade_id, obs in list(self.active_monitors.items()):
            if obs["tradingsymbol"] != tradingsymbol:
                continue

            elapsed_sec = time.time() - obs["exit_time_sec"]
            buy_avg = obs["buy_avg_price"]
            exit_price = obs["actual_exit_price"]

            # 1. Update High and Additional Premium
            if current_ltp > obs["post_exit_high_premium"]:
                obs["post_exit_high_premium"] = current_ltp
                obs["time_to_post_exit_high_sec"] = elapsed_sec
                obs["additional_premium_pts"] = round(current_ltp - exit_price, 2)

            # 2. Check Reversal below original +3 target
            if current_ltp < exit_price:
                obs["reversed_below_plus_3"] = 1

            # 3. Adverse move after high
            adverse_move = obs["post_exit_high_premium"] - current_ltp
            if adverse_move > obs["max_adverse_move_after_high"]:
                obs["max_adverse_move_after_high"] = round(adverse_move, 2)

            # 4. Check milestones relative to original entry
            move_from_entry = current_ltp - buy_avg
            if move_from_entry >= 5.0:
                obs["reached_plus_5"] = 1
            if move_from_entry >= 7.0:
                obs["reached_plus_7"] = 1
            if move_from_entry >= 10.0:
                obs["reached_plus_10"] = 1
            if move_from_entry >= 15.0:
                obs["reached_plus_15"] = 1

            # 5. Record timed snapshots (1, 3, 5, 10, 15, 30 min)
            if elapsed_sec >= 60 and obs["premium_1m"] is None:
                obs["premium_1m"] = current_ltp
            if elapsed_sec >= 180 and obs["premium_3m"] is None:
                obs["premium_3m"] = current_ltp
            if elapsed_sec >= 300 and obs["premium_5m"] is None:
                obs["premium_5m"] = current_ltp
            if elapsed_sec >= 600 and obs["premium_10m"] is None:
                obs["premium_10m"] = current_ltp
            if elapsed_sec >= 900 and obs["premium_15m"] is None:
                obs["premium_15m"] = current_ltp
            if elapsed_sec >= 1800 and obs["premium_30m"] is None:
                obs["premium_30m"] = current_ltp
                obs["nifty_underlying_after_30m"] = nifty_spot
                n_diff = nifty_spot - obs["nifty_underlying_at_exit"]
                obs["nifty_direction_post_exit"] = "UP" if n_diff > 0 else "DOWN"
                obs["monitoring_stopped_reason"] = "Completed 30-minute observation window"
                self._save_and_retire(trade_id)

    def _save_and_retire(self, trade_id: str):
        obs = self.active_monitors.pop(trade_id, None)
        if not obs:
            return

        ist_now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.db._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO post_target_observations (
                        observation_id, trade_id, position_id, tradingsymbol, buy_avg_price,
                        actual_exit_price, target_exit_time_ist, exit_quantity, gross_pnl, net_pnl,
                        post_exit_high_premium, time_to_post_exit_high_sec, additional_premium_pts,
                        reached_plus_5, reached_plus_7, reached_plus_10, reached_plus_15,
                        reversed_below_plus_3, max_adverse_move_after_high,
                        premium_1m, premium_3m, premium_5m, premium_10m, premium_15m, premium_30m,
                        nifty_underlying_at_exit, nifty_underlying_after_30m, nifty_direction_post_exit,
                        monitoring_stopped_reason, updated_at_ist
                    ) VALUES (
                        :observation_id, :trade_id, :position_id, :tradingsymbol, :buy_avg_price,
                        :actual_exit_price, :target_exit_time_ist, :exit_quantity, :gross_pnl, :net_pnl,
                        :post_exit_high_premium, :time_to_post_exit_high_sec, :additional_premium_pts,
                        :reached_plus_5, :reached_plus_7, :reached_plus_10, :reached_plus_15,
                        :reversed_below_plus_3, :max_adverse_move_after_high,
                        :premium_1m, :premium_3m, :premium_5m, :premium_10m, :premium_15m, :premium_30m,
                        :nifty_underlying_at_exit, :nifty_underlying_after_30m, :nifty_direction_post_exit,
                        :monitoring_stopped_reason, :updated_at_ist
                    )
                    """,
                    {**obs, "updated_at_ist": ist_now}
                )
            logger.info("[POST-TARGET RECORD SAVED] Trade %s persisted to analytics database.", trade_id)
        except Exception as e:
            logger.error("Failed to save post-target observation for trade %s: %s", trade_id, e)
