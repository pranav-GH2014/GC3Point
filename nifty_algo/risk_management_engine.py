import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from nifty_algo.risk.charges import ZerodhaOptionChargesCalculator, TransactionCharges

logger = logging.getLogger("nifty_algo.risk_engine")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class RiskEngineConfig:
    max_active_positions: int = 1
    max_daily_loss_inr: float = 500.0
    max_consecutive_losses: int = 2
    loss_cooldown_minutes: int = 15
    max_daily_trades: int = 5
    min_risk_reward_ratio: float = 1.0
    max_slippage_points: float = 1.0
    max_capital_exposure_pct: float = 0.98
    reserved_capital_pct: float = 0.02
    stale_data_timeout_seconds: float = 20.0
    
    # Dynamic Stop Loss parameters
    default_stop_loss_pts: float = 4.0
    min_stop_loss_pts: float = 2.5
    max_stop_loss_pts: float = 6.0
    atr_sl_multiplier: float = 0.40  # Option ATR ~ 40% of spot ATR
    
    # Two-stage exit parameters
    stage1_breakeven_trigger_pts: float = 1.8  # When in +1.8 pts profit, move SL to breakeven + charges
    stage1_lock_profit_pts: float = 0.5        # Locks entry + charges offset (+0.5 pts)
    stage2_trailing_activation_pts: float = 2.5
    stage2_trail_step_pts: float = 0.5


@dataclass
class CircuitBreakerStatus:
    is_tripped: bool
    reason: str
    trip_time: Optional[datetime] = None
    resets_at: Optional[datetime] = None


class RiskManagementEngine:
    """
    Mandatory Comprehensive Risk Management Engine (Phase 6)
    Highest-priority safety authority:
    - Never operates without a protective exit.
    - Dynamic stop loss tailored to volatility, swing invalidation, and transaction costs.
    - Two-stage profit-locking exit (True Breakeven after Zerodha charges + Trailing stop).
    - Daily circuit breaker monitoring realized & unrealized losses, consecutive losses,
      daily trade counts, loss cooldowns, and stale market data.
    - Completely independent of strategy signal generation.
    """

    def __init__(self, config: Optional[RiskEngineConfig] = None):
        self.config = config or RiskEngineConfig()
        self.circuit_breaker = CircuitBreakerStatus(is_tripped=False, reason="")
        self.consecutive_losses: int = 0
        self.daily_trades_count: int = 0
        self.realized_daily_pnl: float = 0.0
        self.last_loss_timestamp: Optional[datetime] = None
        self.last_market_tick_time: Optional[float] = None
        self.daily_trade_history: List[Dict[str, Any]] = []

    def update_heartbeat(self, tick_time: Optional[float] = None):
        self.last_market_tick_time = tick_time or time.time()

    def is_market_data_stale(self) -> Tuple[bool, float]:
        if self.last_market_tick_time is None:
            return False, 0.0
        elapsed = time.time() - self.last_market_tick_time
        return elapsed > self.config.stale_data_timeout_seconds, elapsed

    def compute_dynamic_stop_loss(
        self,
        entry_premium: float,
        spot_atr: float = 12.0,
        structure_invalidation_spot_dist: Optional[float] = None,
        option_delta: float = 0.50,
        bid_ask_spread: float = 0.50
    ) -> float:
        """
        Calculates a dynamic stop loss in option premium points:
        1. Volatility component: spot_atr * delta * multiplier.
        2. Structural invalidation component: option delta * spot distance.
        3. Transaction cost buffer: round-trip spread & charges allowance.
        Enforces min_stop_loss_pts and max_stop_loss_pts bounds.
        """
        # Baseline from ATR
        vol_sl = spot_atr * option_delta * self.config.atr_sl_multiplier
        
        # Structure invalidation
        struct_sl = (structure_invalidation_spot_dist * option_delta) if structure_invalidation_spot_dist else vol_sl
        
        # Consider spread
        cost_buffer = max(0.3, bid_ask_spread * 0.75)
        
        combined_sl = max(vol_sl, struct_sl) + cost_buffer
        bounded_sl = max(self.config.min_stop_loss_pts, min(self.config.max_stop_loss_pts, combined_sl))
        
        # Stop loss price must always be positive and non-zero
        final_sl_pts = round(round(bounded_sl / 0.05) * 0.05, 2)
        logger.info(
            "[RISK ENGINE SL] Entry: ₹%.2f | Dynamic SL: %.2f pts (Vol SL: %.2f, Struct SL: %.2f, Spread Buffer: %.2f)",
            entry_premium, final_sl_pts, vol_sl, struct_sl, cost_buffer
        )
        return final_sl_pts

    def compute_two_stage_exit_price(
        self,
        buy_avg_price: float,
        current_ltp: float,
        current_stop_price: float,
        highest_ltp_seen: float,
        lot_size: int = 65
    ) -> Tuple[float, str]:
        """
        Calculates revised stop loss under the two-stage exit mandate:
        - Stage 1: If current_ltp >= buy_avg + trigger, lock entry + charges.
        - Stage 2: If highest_ltp >= buy_avg + stage 2, trail behind highest price.
        NEVER loosens stop loss in the losing direction!
        """
        points_gain = current_ltp - buy_avg_price
        max_gain = highest_ltp_seen - buy_avg_price

        # True Breakeven Calculation including brokerage & STT
        charges = ZerodhaOptionChargesCalculator.calculate(buy_avg_price, buy_avg_price + 0.5, lot_size)
        charges_pts = round(charges.total_charges / lot_size, 2)
        true_breakeven_price = round(round((buy_avg_price + charges_pts + self.config.stage1_lock_profit_pts) / 0.05) * 0.05, 2)

        # Stage 2 Trailing
        if max_gain >= self.config.stage2_trailing_activation_pts:
            trail_distance = 1.5  # Keep 1.5 pts breathing room
            suggested_stop = round(round((highest_ltp_seen - trail_distance) / 0.05) * 0.05, 2)
            if suggested_stop > current_stop_price:
                return suggested_stop, f"STAGE_2_TRAILING (Locked ₹{suggested_stop:.2f} behind high ₹{highest_ltp_seen:.2f})"

        # Stage 1 Breakeven Lock
        if points_gain >= self.config.stage1_breakeven_trigger_pts:
            if true_breakeven_price > current_stop_price:
                return true_breakeven_price, f"STAGE_1_BREAKEVEN_PROTECTED (Locked ₹{true_breakeven_price:.2f} covering charges ₹{charges.total_charges:.2f})"

        return current_stop_price, "MAINTAIN_CURRENT_STOP"

    def can_initiate_new_trade(
        self,
        has_active_position: bool,
        unrealized_pnl: float = 0.0,
        current_time_ist: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Master gatekeeper: strictly checks all circuit breakers before permitting a new trade entry.
        """
        now = current_time_ist or datetime.now(IST)

        # 1. Active Position Check
        if has_active_position:
            return False, "REJECTED_ACTIVE_POSITION_EXISTS"

        # 2. Circuit Breaker Already Tripped Check
        if self.circuit_breaker.is_tripped:
            return False, f"REJECTED_CIRCUIT_BREAKER_ACTIVE: {self.circuit_breaker.reason}"

        # 3. Stale Market Data Check
        stale, elapsed = self.is_market_data_stale()
        if stale:
            return False, f"REJECTED_STALE_MARKET_DATA: No ticks for {elapsed:.1f}s (Threshold: {self.config.stale_data_timeout_seconds}s)"

        # 4. Daily Realized + Unrealized Loss Limit (₹500 initially)
        total_daily_loss = self.realized_daily_pnl + min(0.0, unrealized_pnl)
        if total_daily_loss <= -self.config.max_daily_loss_inr:
            self._trip_circuit_breaker(f"Hit Daily Loss Limit of ₹{self.config.max_daily_loss_inr:.2f} (Current: ₹{total_daily_loss:.2f})")
            return False, f"REJECTED_DAILY_LOSS_LIMIT_REACHED (Loss: ₹{total_daily_loss:.2f})"

        # 5. Consecutive Losses Limit (2 losses)
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            self._trip_circuit_breaker(f"Hit Maximum Consecutive Losses ({self.consecutive_losses} >= {self.config.max_consecutive_losses})")
            return False, f"REJECTED_CONSECUTIVE_LOSS_LIMIT ({self.consecutive_losses} losses)"

        # 6. Cooldown After Loss (15 minutes)
        if self.last_loss_timestamp is not None:
            time_since_loss = (now - self.last_loss_timestamp).total_seconds() / 60.0
            if time_since_loss < self.config.loss_cooldown_minutes:
                remaining_cd = self.config.loss_cooldown_minutes - time_since_loss
                return False, f"REJECTED_LOSS_COOLDOWN_ACTIVE: {remaining_cd:.1f} minutes remaining"

        # 7. Maximum Daily Trades Limit
        if self.daily_trades_count >= self.config.max_daily_trades:
            self._trip_circuit_breaker(f"Hit Maximum Daily Trades ({self.daily_trades_count} >= {self.config.max_daily_trades})")
            return False, f"REJECTED_MAX_DAILY_TRADES_EXCEEDED ({self.daily_trades_count} trades taken)"

        return True, "QUALIFIED"

    def record_completed_trade(
        self,
        trade_id: str,
        gross_pnl: float,
        net_pnl: float,
        exit_reason: str,
        timestamp: Optional[datetime] = None
    ):
        """Updates internal risk state immediately upon trade completion."""
        now = timestamp or datetime.now(IST)
        self.daily_trades_count += 1
        self.realized_daily_pnl += net_pnl
        
        self.daily_trade_history.append({
            "trade_id": trade_id,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "exit_reason": exit_reason,
            "timestamp": now.isoformat()
        })

        if net_pnl < 0:
            self.consecutive_losses += 1
            self.last_loss_timestamp = now
            logger.warning(
                "[RISK ENGINE LOSS RECORDED] Trade %s Loss: ₹%.2f. Consecutive losses: %d. Daily Realized: ₹%.2f",
                trade_id, net_pnl, self.consecutive_losses, self.realized_daily_pnl
            )
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self._trip_circuit_breaker(f"Hit Maximum Consecutive Losses ({self.consecutive_losses})")
            if self.realized_daily_pnl <= -self.config.max_daily_loss_inr:
                self._trip_circuit_breaker(f"Hit Daily Loss Limit of ₹{self.config.max_daily_loss_inr:.2f}")
        else:
            # Winning or true breakeven trade resets consecutive loss counter
            logger.info(
                "[RISK ENGINE WIN RECORDED] Trade %s Profit: ₹%.2f. Resetting consecutive loss counter. Daily Realized: ₹%.2f",
                trade_id, net_pnl, self.realized_daily_pnl
            )
            self.consecutive_losses = 0

    def _trip_circuit_breaker(self, reason: str):
        self.circuit_breaker = CircuitBreakerStatus(
            is_tripped=True,
            reason=reason,
            trip_time=datetime.now(IST)
        )
        logger.critical("[CIRCUIT BREAKER TRIPPED] %s. All new entries locked for remainder of session.", reason)

    def manual_reset_circuit_breaker(self, reason: str = "Operator override"):
        logger.info("[CIRCUIT BREAKER RESET] %s", reason)
        self.circuit_breaker = CircuitBreakerStatus(is_tripped=False, reason="")
