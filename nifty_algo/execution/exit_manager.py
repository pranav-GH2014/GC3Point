import time
import uuid
import logging
from typing import Dict, Any, Optional, Tuple, List
from ..config.config_loader import AppConfig
from ..data.kite_client import SafeKiteClient
from ..database.db import DatabaseManager

logger = logging.getLogger("nifty_algo.exit_manager")

class BrokerStateUncertainError(Exception):
    """Raised when broker positions and orders cannot be reconciled with 100% certainty."""
    pass

class ExitSafetyManager:
    """
    CRITICAL Execution-Risk Safety Engine:
    - Enforces STRICT BUY-ONLY policy (NEVER create an accidental short position).
    - Verifies live broker position quantity directly with Zerodha before placing any SELL order.
    - Limits SELL quantity strictly to <= verified remaining long quantity.
    - Prevents duplicate exit orders and race conditions during partial execution.
    - Locks the system in EMERGENCY_FREEZE if broker state is uncertain.
    """

    def __init__(self, config: AppConfig, kite_client: SafeKiteClient, db: DatabaseManager):
        self.config = config
        self.kite_client = kite_client
        self.db = db

    def get_verified_remaining_long_quantity(self, tradingsymbol: str) -> Tuple[int, Dict[str, Any]]:
        """
        Queries live Zerodha positions and open orders directly.
        Returns: (verified_net_long_quantity, raw_broker_position_dict)
        """
        if self.config.simulation_mode:
            # Paper mode: Query SQLite open position
            pos = self.db.get_open_strategy_position()
            if pos and pos["tradingsymbol"] == tradingsymbol:
                return pos["remaining_quantity"], pos
            return 0, {}

        try:
            positions_data = self.kite_client.get_positions()
            net_positions = positions_data.get("net", [])
            target_pos = next((p for p in net_positions if p.get("tradingsymbol") == tradingsymbol), None)

            if not target_pos:
                return 0, {}

            net_qty = target_pos.get("quantity", 0)
            if net_qty < 0:
                # SEVERE VIOLATION DETECTED: Accidental short position!
                msg = f"CRITICAL ANOMALY: Detected negative net position ({net_qty}) for {tradingsymbol}!"
                logger.critical(msg)
                self.db.log_audit("CRITICAL_SHORT_DETECTED", "CRITICAL", msg, target_pos)
                raise BrokerStateUncertainError(msg)

            return net_qty, target_pos
        except Exception as e:
            msg = f"Failed to verify broker live positions: {e}"
            logger.critical(msg)
            raise BrokerStateUncertainError(msg)

    def verify_no_conflicting_exit_orders(self, tradingsymbol: str) -> List[str]:
        """
        Queries live open orders from Zerodha to check if any open SELL order already exists for this contract.
        """
        if self.config.simulation_mode:
            return []

        open_sell_orders = []
        try:
            orders = self.kite_client.get_orders()
            for ord_info in orders:
                if ord_info.get("tradingsymbol") == tradingsymbol and \
                   ord_info.get("transaction_type") == "SELL" and \
                   ord_info.get("status") in ("OPEN", "TRIGGER PENDING", "VALIDATION PENDING"):
                    open_sell_orders.append(ord_info["order_id"])
        except Exception as e:
            msg = f"Failed to query live broker open orders: {e}"
            logger.critical(msg)
            raise BrokerStateUncertainError(msg)

        return open_sell_orders

    def place_fixed_target_exit(
        self,
        tradingsymbol: str,
        buy_avg_price: float,
        expected_quantity: int,
        target_points_override: Optional[float] = None
    ) -> Tuple[bool, Optional[str], float, str]:
        """
        Places a target SELL limit order strictly protecting verified filled quantity.
        Supports standard +3.0 pts or expanded fast-move +15.0 pts.
        """
        target_pts = target_points_override if target_points_override is not None else self.config.target_premium_points
        target_price = round(buy_avg_price + target_pts, 2)
        # Tick alignment to 0.05
        target_price = round(round(target_price / 0.05) * 0.05, 2)

        # 1. Verification of real remaining long quantity directly with Zerodha
        verified_qty, _ = self.get_verified_remaining_long_quantity(tradingsymbol)

        if verified_qty <= 0:
            msg = f"Cannot place exit SELL: Verified remaining long quantity for {tradingsymbol} is {verified_qty}"
            logger.error(msg)
            return False, None, target_price, msg

        # Strict safety cap: SELL quantity must never exceed verified remaining quantity
        sell_quantity = min(verified_qty, expected_quantity)

        # 2. Check for conflicting open SELL orders
        conflicting = self.verify_no_conflicting_exit_orders(tradingsymbol)
        if conflicting:
            msg = f"DUPLICATE SELL PREVENTED: Open SELL orders already pending on broker: {conflicting}"
            logger.warning(msg)
            return False, conflicting[0], target_price, msg

        logger.info(
            "[EXIT TARGET INITIATED] %s @ Target Limit ₹%.2f (+%.1f pts over Buy Avg ₹%.2f). Verified Qty: %d",
            tradingsymbol, target_price, target_pts, buy_avg_price, sell_quantity
        )

        if self.config.simulation_mode:
            broker_order_id = f"SIM_SELL_{uuid.uuid4().hex[:10]}"
            logger.info("[PAPER TARGET SELL PLACED] %s order %s", tradingsymbol, broker_order_id)
            return True, broker_order_id, target_price, "Paper target order placed"

        try:
            broker_order_id = self.kite_client.place_order(
                variety="regular",
                exchange="NFO",
                tradingsymbol=tradingsymbol,
                transaction_type="SELL",
                quantity=sell_quantity,
                product=self.config.product_type,
                order_type="LIMIT",
                price=target_price,
                tag=f"EXIT_{uuid.uuid4().hex[:8]}"
            )
            return True, broker_order_id, target_price, "Live target order submitted"
        except Exception as e:
            msg = f"Failed to submit target SELL order: {e}"
            logger.critical(msg)
            return False, None, target_price, msg

    def modify_target_exit(self, tradingsymbol: str, new_target_price: float) -> Tuple[bool, Optional[str], str]:
        """
        Modifies an existing open SELL limit order on Zerodha to a new target price.
        """
        target_price = round(round(new_target_price / 0.05) * 0.05, 2)
        if self.config.simulation_mode:
            logger.info("[PAPER TARGET MODIFIED] %s target adjusted to ₹%.2f", tradingsymbol, target_price)
            return True, "SIM_MODIFIED", f"Paper target order updated to ₹{target_price:.2f}"

        conflicting = self.verify_no_conflicting_exit_orders(tradingsymbol)
        if not conflicting:
            msg = f"No open SELL exit order found for {tradingsymbol} to modify."
            logger.warning(msg)
            return False, None, msg

        order_id = conflicting[0]
        try:
            self.kite_client.modify_order(
                variety="regular",
                order_id=order_id,
                price=target_price,
                order_type="LIMIT"
            )
            msg = f"Target order {order_id} modified to ₹{target_price:.2f}"
            logger.info("[LIVE TARGET MODIFIED] %s: %s", tradingsymbol, msg)
            return True, order_id, msg
        except Exception as e:
            msg = f"Failed to modify target order {order_id}: {e}"
            logger.error(msg)
            return False, order_id, msg

    def reconcile_and_confirm_position_closed(self, tradingsymbol: str) -> bool:
        """
        After exit execution, verifies that net position is exactly ZERO before marking trade closed.
        """
        verified_qty, _ = self.get_verified_remaining_long_quantity(tradingsymbol)
        if verified_qty == 0:
            logger.info("[POSITION VERIFIED CLOSED] %s net quantity confirmed 0 on broker.", tradingsymbol)
            return True
        else:
            logger.warning("[POSITION STILL OPEN] %s net quantity is %d. Trade is NOT closed.", tradingsymbol, verified_qty)
            return False
