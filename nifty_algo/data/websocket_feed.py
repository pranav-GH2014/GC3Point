import logging
import threading
import time
from typing import List, Callable, Dict, Any, Optional
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.websocket")

class RobustWebSocketFeed:
    """
    Manages KiteTicker WebSocket connection:
    - Auto-reconnect with exponential backoff
    - Automatic token resubscription
    - Periodic heartbeat check
    - Thread-safe message dispatch
    """

    def __init__(self, config: AppConfig, on_tick_callback: Callable[[List[Dict[str, Any]]], None]):
        self.config = config
        self.on_tick_callback = on_tick_callback
        self.kws: Any = None
        self.subscribed_tokens: List[int] = []
        self._is_running = False
        self._last_heartbeat = time.time()
        self._lock = threading.Lock()

    def set_tokens(self, tokens: List[int]):
        with self._lock:
            self.subscribed_tokens = list(set(tokens))
            if self.kws and hasattr(self.kws, "is_connected") and self.kws.is_connected():
                self.kws.subscribe(self.subscribed_tokens)
                self.kws.set_mode(self.kws.MODE_FULL, self.subscribed_tokens)
                logger.info("Resubscribed to tokens: %s", self.subscribed_tokens)

    def start(self):
        if not self.config.api_key or not self.config.access_token:
            logger.warning("Kite API key or access token missing; WebSocket feed will not start in real-time.")
            return

        try:
            from kiteconnect.ticker import KiteTicker
        except Exception as e:
            logger.error("Failed to load KiteTicker: %s", e)
            return

        self._is_running = True
        self.kws = KiteTicker(
            api_key=self.config.api_key,
            access_token=self.config.access_token
        )

        self.kws.on_ticks = self._on_ticks
        self.kws.on_connect = self._on_connect
        self.kws.on_close = self._on_close
        self.kws.on_error = self._on_error
        self.kws.on_reconnect = self._on_reconnect
        self.kws.on_noreconnect = self._on_noreconnect

        # Launch in background with KiteTicker's built-in non-blocking thread (installSignalHandlers=False)
        self.kws.connect(threaded=True)
        logger.info("WebSocket feed launched (threaded=True).")

    def _on_connect(self, ws, response):
        logger.info("WebSocket connected successfully! Response: %s", response)
        with self._lock:
            if self.subscribed_tokens:
                ws.subscribe(self.subscribed_tokens)
                ws.set_mode(ws.MODE_FULL, self.subscribed_tokens)
                logger.info("Subscribed %d tokens on connect.", len(self.subscribed_tokens))

    def _on_ticks(self, ws, ticks):
        self._last_heartbeat = time.time()
        if self.on_tick_callback:
            self.on_tick_callback(ticks)

    def _on_close(self, ws, code, reason):
        logger.warning("WebSocket closed! Code: %s, Reason: %s", code, reason)

    def _on_error(self, ws, code, reason):
        logger.error("WebSocket error! Code: %s, Reason: %s", code, reason)

    def _on_reconnect(self, ws, attempts_count):
        logger.info("WebSocket reconnecting... Attempt %d", attempts_count)

    def _on_noreconnect(self, ws):
        logger.critical("WebSocket failed all reconnect attempts!")

    def check_heartbeat(self, timeout_seconds: float = 15.0) -> bool:
        """Returns True if ticks received within timeout, False otherwise."""
        if not self._is_running:
            return True
        elapsed = time.time() - self._last_heartbeat
        return elapsed <= timeout_seconds

    def stop(self):
        self._is_running = False
        if self.kws:
            try:
                self.kws.close()
            except Exception as e:
                logger.error("Error closing WebSocket: %s", e)
