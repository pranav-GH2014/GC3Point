import time
import logging
from typing import Optional, Dict, Any, Tuple
from ..config.config_loader import AppConfig
from ..database.db import DatabaseManager

logger = logging.getLogger("nifty_algo.position_tracker")

class PositionTracker:
    """
    Coordinates single-position execution lifecycle and enforces the 3-minute re-entry cooldown.
    """

    def __init__(self, config: AppConfig, db: DatabaseManager):
        self.config = config
        self.db = db
        self.current_position: Optional[Dict[str, Any]] = None
        self.cooldown_until: float = 0.0
        self.state: str = "IDLE"  # 'IDLE', 'PENDING_BUY', 'OPEN', 'PENDING_EXIT', 'COOLDOWN'

    @property
    def has_open_position(self) -> bool:
        return self.current_position is not None and self.state in ("PENDING_BUY", "OPEN", "PENDING_EXIT")

    @property
    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def get_remaining_cooldown_seconds(self) -> int:
        remaining = int(self.cooldown_until - time.time())
        return max(0, remaining)

    def start_cooldown(self, reason: str = "Trade completed"):
        self.cooldown_until = time.time() + self.config.re_entry_cooldown_seconds
        self.state = "COOLDOWN"
        logger.info("[COOLDOWN ACTIVATED] %d seconds cooldown started. Reason: %s", self.config.re_entry_cooldown_seconds, reason)

    def set_active_position(self, pos: Dict[str, Any]):
        self.current_position = pos
        self.state = pos.get("status", "OPEN")

    def clear_position(self):
        self.current_position = None
        self.start_cooldown("Position closed")

    def check_can_enter(self) -> Tuple[bool, str]:
        if self.has_open_position:
            return False, f"Existing open strategy position active ({self.current_position.get('tradingsymbol')})"

        if self.is_in_cooldown:
            return False, f"Re-entry cooldown active ({self.get_remaining_cooldown_seconds()}s remaining)"

        return True, "Ready for entry"
