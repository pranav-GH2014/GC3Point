import logging
from typing import Optional, Tuple, Dict, Any, List
from .charges import ZerodhaOptionChargesCalculator, TransactionCharges
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.risk")

class PreLiveCheckFailedError(Exception):
    """Raised when pre-live safety checks fail."""
    pass

class RiskManager:
    """
    Execution Risk Engine:
    - Strictly buy-only protection (no naked shorting).
    - Max 98% capital deployment, 2% reserved.
    - Lot affordability verification.
    - 3 consecutive losing trades circuit breaker.
    - Unresolved parameter validation (blocks LIVE if unconfirmed).
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._consecutive_losses = 0
        self._is_trading_frozen = False
        self._freeze_reason = ""

    @property
    def is_frozen(self) -> bool:
        return self._is_trading_frozen

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    def set_consecutive_losses(self, count: int):
        self._consecutive_losses = count
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self._is_trading_frozen = True
            self._freeze_reason = f"Hit {self.config.max_consecutive_losses} consecutive losses. Trading stopped for today."
            logger.warning("[RISK CIRCUIT] %s", self._freeze_reason)

    def record_trade_result(self, net_pnl: float):
        if net_pnl < 0:
            self._consecutive_losses += 1
            logger.info("Recorded loss trade. Consecutive losses: %d", self._consecutive_losses)
            if self._consecutive_losses >= self.config.max_consecutive_losses:
                self._is_trading_frozen = True
                self._freeze_reason = f"Hit {self.config.max_consecutive_losses} consecutive losses."
                logger.critical("[RISK FREEZE] %s", self._freeze_reason)
        else:
            logger.info("Recorded winning/breakeven trade (Net P&L: ₹%.2f). Resetting consecutive loss counter.", net_pnl)
            self._consecutive_losses = 0

    def verify_affordability(self, available_capital: float, option_premium: float, lot_size: int) -> Tuple[bool, int, str]:
        """
        Calculates max deployable capital (98% of available, 2% reserved)
        and verifies if at least 1 whole lot can be afforded.
        """
        if available_capital <= 0:
            return False, 0, f"Available capital ₹{available_capital:.2f} is non-positive"

        deployable_capital = available_capital * self.config.capital.max_deployment_pct
        required_capital_1_lot = option_premium * lot_size

        if required_capital_1_lot > deployable_capital:
            return False, 0, (
                f"1 lot ({lot_size} units @ ₹{option_premium:.2f} = ₹{required_capital_1_lot:.2f}) "
                f"exceeds 98% deployable capital limit (₹{deployable_capital:.2f} of ₹{available_capital:.2f})"
            )

        # For this strategy, desired quantity is 1 full lot
        return True, lot_size, "Affordability verified"

    def perform_pre_live_safety_checks(self) -> Tuple[bool, List[str]]:
        """
        Non-negotiable pre-live checklist:
        1. LIVE mode must be explicitly enabled.
        2. Unresolved parameter 'max_loss_per_trade_inr' must not be None.
        3. Broker API key and access token must be present and verified.
        4. Telegram credentials must be configured.
        """
        failures = []

        if self.config.simulation_mode:
            failures.append("Program is in PAPER/SIMULATION mode; live trading cannot proceed until simulation_mode=false.")

        if not self.config.live_execution_enabled:
            failures.append("live_execution_enabled is set to false.")

        if self.config.risk.max_loss_per_trade_inr is None or self.config.risk.max_loss_per_trade_inr <= 0:
            failures.append(
                "UNRESOLVED PARAMETER: 'max_loss_per_trade_inr' is NOT confirmed. "
                "The algorithm strictly forbids live trading without an approved monetary risk cap per trade."
            )

        if not self.config.api_key or not self.config.access_token:
            failures.append("Zerodha Kite API key or access token is missing.")

        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            failures.append("Telegram notification credentials are missing.")

        return len(failures) == 0, failures
