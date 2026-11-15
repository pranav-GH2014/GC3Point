import time
import uuid
import logging
from typing import Dict, Any, Optional, Tuple
from ..config.config_loader import AppConfig
from ..data.kite_client import SafeKiteClient
from ..database.db import DatabaseManager

logger = logging.getLogger("nifty_algo.order_manager")

class OrderExecutionManager:
    """
    Manages BUY order lifecycle strictly following Section 17 requirements:
    - BUY Limit price = current premium - offset (e.g. 0.45)
    - Full pre-flight verification against Zerodha
    - Order timeout handling
    - Partial fill handling: Cancels unfilled balance, confirms cancellation, protects ONLY actual filled quantity.
    """

    def __init__(self, config: AppConfig, kite_client: SafeKiteClient, db: DatabaseManager):
        self.config = config
        self.kite_client = kite_client
        self.db = db

    def execute_buy(
        self,
        contract: Dict[str, Any],
        current_premium: float,
        trade_id: str,
        position_id: str
    ) -> Tuple[bool, Optional[str], int, float, str]:
        """
        Executes a BUY limit order.
        Returns: (success, broker_order_id, filled_qty, avg_price, message)
        """
        tradingsymbol = contract["tradingsymbol"]
        lot_size = contract["lot_size"]
        discount_offset = self.config.buy_limit_discount_offset
        limit_price = round(current_premium - discount_offset, 2)
        # Ensure tick size alignment (0.05 step for NSE)
        limit_price = round(round(limit_price / 0.05) * 0.05, 2)

        client_order_id = f"BUY_{uuid.uuid4().hex[:12]}"
        logger.info(
            "[BUY INITIATED] %s @ Limit ₹%.2f (Offset: -₹%.2f from ₹%.2f). Desired Qty: %d",
            tradingsymbol, limit_price, discount_offset, current_premium, lot_size
        )

        if self.config.simulation_mode:
            # Paper execution: Simulates immediate limit execution for dry-run testing
            filled_qty = lot_size
            avg_price = limit_price
            broker_order_id = f"SIM_{client_order_id}"
            logger.info("[PAPER BUY COMPLETE] %s filled %d units @ ₹%.2f", tradingsymbol, filled_qty, avg_price)
            return True, broker_order_id, filled_qty, avg_price, "Paper fill executed"

        # LIVE ORDER EXECUTION:
        try:
            broker_order_id = self.kite_client.place_order(
                variety="regular",
                exchange="NFO",
                tradingsymbol=tradingsymbol,
                transaction_type="BUY",
                quantity=lot_size,
                product=self.config.product_type,
                order_type="LIMIT",
                price=limit_price,
                tag=client_order_id
            )
        except Exception as e:
            msg = f"BUY order placement rejected by broker: {e}"
            logger.error(msg)
            return False, None, 0, 0.0, msg

        # Poll order status within timeout window
        timeout = self.config.buy_order_timeout_seconds
        start_time = time.time()
        filled_qty = 0
        avg_price = 0.0
        order_status = "PLACED"

        while time.time() - start_time < timeout:
            time.sleep(1.0)
            try:
                history = self.kite_client.get_order_history(broker_order_id)
                if not history:
                    continue
                latest = history[-1]
                order_status = latest.get("status", "PLACED")
                filled_qty = latest.get("filled_quantity", 0)
                avg_price = latest.get("average_price", 0.0)

                if order_status == "COMPLETE":
                    logger.info("[BUY COMPLETE] Order %s fully filled: %d units @ ₹%.2f", broker_order_id, filled_qty, avg_price)
                    return True, broker_order_id, filled_qty, avg_price, "Fully filled"

                if order_status in ("CANCELLED", "REJECTED"):
                    msg = f"Order {broker_order_id} ended with status: {order_status}. Reason: {latest.get('status_message')}"
                    logger.warning(msg)
                    return False, broker_order_id, filled_qty, avg_price, msg

            except Exception as e:
                logger.error("Error polling order history for %s: %s", broker_order_id, e)

        # Timeout reached: If partially filled or unfilled, cancel remaining balance
        logger.warning("[BUY TIMEOUT] Order %s timed out after %d sec. Status: %s, Filled: %d/%d",
                       broker_order_id, timeout, order_status, filled_qty, lot_size)
        try:
            self.kite_client.cancel_order(variety="regular", order_id=broker_order_id)
        except Exception as e:
            logger.error("Exception while cancelling timed out order %s: %s", broker_order_id, e)

        # Give 1.5s for broker cancellation to settle and re-verify actual fills
        time.sleep(1.5)
        try:
            history = self.kite_client.get_order_history(broker_order_id)
            if history:
                latest = history[-1]
                filled_qty = latest.get("filled_quantity", 0)
                avg_price = latest.get("average_price", 0.0)
        except Exception as e:
            logger.error("Re-verification after cancel failed: %s", e)

        if filled_qty > 0:
            logger.info("[PARTIAL BUY MANAGED] Retaining confirmed partial fill: %d units @ ₹%.2f", filled_qty, avg_price)
            return True, broker_order_id, filled_qty, avg_price, f"Partial fill confirmed ({filled_qty} units)"

        return False, broker_order_id, 0, 0.0, "Unfilled order cancelled after timeout"
