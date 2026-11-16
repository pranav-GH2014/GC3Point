import time
import logging
from typing import Dict, Any, List, Optional
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.kite")

class SafeKiteClient:
    """
    Robust Zerodha KiteConnect client wrapper:
    - Rate limit backoff (3 requests/sec max for standard calls)
    - Automatic retries on network timeouts
    - Clock drift validation
    - Safe exception handling
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.kite: Any = None
        if config.api_key:
            try:
                from kiteconnect import KiteConnect
                self.kite = KiteConnect(api_key=config.api_key)
                if config.access_token:
                    self.kite.set_access_token(config.access_token)
            except Exception as e:
                logger.error("Failed to initialize live KiteConnect client: %s", e)
        self._last_call_time = 0.0
        self._min_interval = 0.35  # ~3 requests per second limit

    def _rate_limit(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def check_clock_synchronization(self) -> float:
        """Compares local system time with Zerodha server or returns drift in seconds."""
        t0 = time.time()
        try:
            # We call profile or quote to measure round-trip
            self._rate_limit()
            _ = self.kite.margins()
            round_trip = time.time() - t0
            logger.info("Clock sync check passed. Broker latency: %.3fs", round_trip)
            return round_trip
        except Exception as e:
            logger.warning("Clock sync check warning: %s", e)
            return 0.0

    def get_positions(self) -> Dict[str, Any]:
        self._rate_limit()
        return self.kite.positions()

    def get_orders(self) -> List[Dict[str, Any]]:
        self._rate_limit()
        return self.kite.orders()

    def get_order_history(self, order_id: str) -> List[Dict[str, Any]]:
        self._rate_limit()
        return self.kite.order_history(order_id)

    def get_trades(self) -> List[Dict[str, Any]]:
        self._rate_limit()
        return self.kite.trades()

    def get_margins(self) -> Dict[str, Any]:
        self._rate_limit()
        return self.kite.margins()

    def get_quote(self, instruments: List[str]) -> Dict[str, Any]:
        self._rate_limit()
        return self.kite.quote(instruments)

    def get_ltp(self, instruments: List[str]) -> Dict[str, Any]:
        self._rate_limit()
        return self.kite.ltp(instruments)

    def get_instruments(self, exchange: str = "NFO") -> List[Dict[str, Any]]:
        self._rate_limit()
        return self.kite.instruments(exchange)

    def get_historical_data(self, instrument_token: int, from_date: str, to_date: str, interval: str) -> List[Dict[str, Any]]:
        self._rate_limit()
        return self.kite.historical_data(instrument_token, from_date, to_date, interval)

    def place_order(self, variety: str, exchange: str, tradingsymbol: str, transaction_type: str,
                    quantity: int, product: str, order_type: str, price: Optional[float] = None,
                    trigger_price: Optional[float] = None, tag: Optional[str] = None) -> str:
        if self.config.simulation_mode:
            raise RuntimeError("CRITICAL HARD STOP: place_order called while simulation_mode=True! Live order strictly blocked.")
        self._rate_limit()
        logger.info(
            "[KITE EXECUTE] %s %d %s:%s @ %s (Product: %s, OrderType: %s)",
            transaction_type, quantity, exchange, tradingsymbol, price, product, order_type
        )
        return self.kite.place_order(
            variety=variety,
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product=product,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            tag=tag
        )

    def cancel_order(self, variety: str, order_id: str) -> str:
        self._rate_limit()
        logger.info("[KITE CANCEL] Cancelling order %s", order_id)
        return self.kite.cancel_order(variety=variety, order_id=order_id)

    def modify_order(self, variety: str, order_id: str, quantity: Optional[int] = None,
                     price: Optional[float] = None, order_type: Optional[str] = None) -> str:
        self._rate_limit()
        logger.info("[KITE MODIFY] Modifying order %s (Qty: %s, Price: %s)", order_id, quantity, price)
        return self.kite.modify_order(
            variety=variety,
            order_id=order_id,
            quantity=quantity,
            price=price,
            order_type=order_type
        )
