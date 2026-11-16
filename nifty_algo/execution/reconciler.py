import logging
from typing import Dict, Any, Optional, Tuple
from ..config.config_loader import AppConfig
from ..data.kite_client import SafeKiteClient
from ..database.db import DatabaseManager

logger = logging.getLogger("nifty_algo.reconciler")

class BrokerReconciler:
    """
    Broker-State Reconciliation & Crash Recovery Engine:
    - Runs on bot startup and after any network/process restart.
    - Ensures Zerodha's live server state is the single source of truth.
    - Freezes trading if an irreconcilable discrepancy is found.
    """

    def __init__(self, config: AppConfig, kite_client: SafeKiteClient, db: DatabaseManager):
        self.config = config
        self.kite_client = kite_client
        self.db = db

    def reconcile_on_startup(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Reconciles broker state on startup.
        Returns: (is_healthy, status_message, active_position_data)
        """
        logger.info("[STARTUP RECONCILIATION] Initiating broker-state audit against Zerodha...")

        if self.config.simulation_mode:
            logger.info("[RECONCILIATION] Running in PAPER mode. Loading persisted open positions from SQLite.")
            open_pos = self.db.get_open_strategy_position()
            if open_pos:
                logger.info("Recovered active paper position: %s (Trade ID: %s)", open_pos["tradingsymbol"], open_pos["trade_id"])
            return True, "Paper mode reconciled", open_pos

        # LIVE MODE RECONCILIATION:
        try:
            positions_res = self.kite_client.get_positions()
            net_positions = positions_res.get("net", [])
            open_orders = self.kite_client.get_orders()
            sqlite_pos = self.db.get_open_strategy_position()

            # Filter non-zero NIFTY option positions
            live_open_nifty = [
                p for p in net_positions 
                if p.get("quantity", 0) != 0 and "NIFTY" in p.get("tradingsymbol", "")
            ]

            # Case 1: Broker has NO open NIFTY positions
            if not live_open_nifty:
                if sqlite_pos and sqlite_pos.get("status") in ("OPEN", "PENDING_EXIT"):
                    logger.warning(
                        "[RECON DISCREPANCY] SQLite has active position %s but broker has 0 net quantity. "
                        "Marking database position CLOSED as broker is authoritative.",
                        sqlite_pos["tradingsymbol"]
                    )
                    self.db.close_position(
                        position_id=sqlite_pos["position_id"],
                        sell_avg=0.0,
                        gross_pnl=0.0,
                        net_pnl=0.0,
                        charges=0.0,
                        exit_reason="Startup reconciliation closed (0 broker quantity)"
                    )
                    self.db.record_reconciliation(
                        broker_qty=0,
                        sqlite_qty=sqlite_pos["remaining_quantity"],
                        discrepancy=True,
                        action="CLOSED_DB_POSITION",
                        details={"sqlite_pos": sqlite_pos}
                    )
                return True, "Broker has zero open positions. Reconciled clean.", None

            # Case 2: Broker has 1 open NIFTY position
            if len(live_open_nifty) == 1:
                broker_pos = live_open_nifty[0]
                broker_qty = broker_pos.get("quantity", 0)
                tradingsymbol = broker_pos.get("tradingsymbol")

                if broker_qty < 0:
                    msg = f"EMERGENCY FREEZE: Detected short position {tradingsymbol} ({broker_qty} units) on broker!"
                    logger.critical(msg)
                    self.db.record_reconciliation(broker_qty, 0, True, "EMERGENCY_FREEZE", broker_pos)
                    return False, msg, None

                logger.info("[RECON MATCH] Active long position on broker: %s (%d units)", tradingsymbol, broker_qty)
                self.db.record_reconciliation(broker_qty, broker_qty, False, "RECOVERED_ACTIVE_POSITION", broker_pos)
                
                # Merge broker position with persisted SQLite record for seamless management
                merged_pos = dict(sqlite_pos) if sqlite_pos else {}
                merged_pos.update(broker_pos)
                merged_pos["tradingsymbol"] = tradingsymbol
                merged_pos["buy_avg_price"] = float(broker_pos.get("average_price") or broker_pos.get("buy_price") or (sqlite_pos.get("buy_avg_price") if sqlite_pos else 0.0))
                merged_pos["filled_quantity"] = int(broker_qty)
                merged_pos["remaining_quantity"] = int(broker_qty)
                merged_pos["status"] = "OPEN"
                merged_pos["target_price"] = float((sqlite_pos.get("target_price") if sqlite_pos else None) or round(merged_pos["buy_avg_price"] + 3.0, 2))
                return True, f"Recovered active position {tradingsymbol}", merged_pos

            # Case 3: More than 1 open position detected (Strategy violation!)
            msg = f"STRATEGY VIOLATION: Multiple open option positions ({len(live_open_nifty)}) detected on broker!"
            logger.critical(msg)
            self.db.record_reconciliation(len(live_open_nifty), 0, True, "MULTIPLE_POSITIONS_FREEZE", {"positions": live_open_nifty})
            return False, msg, None

        except Exception as e:
            msg = f"Reconciliation failed due to broker API error: {e}"
            logger.critical(msg)
            return False, msg, None
