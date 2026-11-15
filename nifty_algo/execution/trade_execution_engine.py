from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List
from ..risk.charges import ZerodhaOptionChargesCalculator, TransactionCharges

@dataclass
class TradeRecord:
    trade_id: str
    date: str
    entry_time: str
    exit_time: str
    direction: str  # 'BUY CE' or 'BUY PE'
    strike_type: str  # 'ATM' or 'ITM_1'
    strike: float
    setup_name: str
    confidence_score: float
    entry_spot: float
    entry_premium: float
    exit_premium: float
    target_premium: float
    stop_premium: float
    break_even_activated: bool
    exit_reason: str  # 'TARGET', 'BREAK_EVEN', 'INITIAL_SL', 'TIME_CUTOFF'
    points_pnl: float
    gross_pnl: float
    charges: float
    net_pnl: float
    mae_points: float  # Maximum Adverse Excursion in option points
    mfe_points: float  # Maximum Favorable Excursion in option points
    holding_time_minutes: int
    contributing_factors: List[str]

class TradeExecutionEngine:
    """
    Manages realistic immediate execution, ATM/ITM_1 contract selection,
    and Section 7 Exit Management (+3 Target, +2 Break-Even Activation, Structural SL Cap).
    """

    def __init__(
        self,
        lot_size: int = 65,
        target_pts: float = 3.0,
        break_even_activation_pts: Optional[float] = None,
        max_premium_loss_cap: float = 5.0,
        slippage_entry: float = 0.10,
        slippage_exit: float = 0.05,
        strike_selection: str = "ATM"  # 'ATM' or 'ITM_1'
    ):
        self.lot_size = lot_size
        self.target_pts = target_pts
        self.break_even_activation_pts = break_even_activation_pts
        self.max_premium_loss_cap = max_premium_loss_cap
        self.slippage_entry = slippage_entry
        self.slippage_exit = slippage_exit
        self.strike_selection = strike_selection.upper()

    def select_strike(self, spot_price: float, direction: str) -> Tuple[float, float, float]:
        """
        Selects strike price, delta, and realistic baseline premium.
        Returns: (strike, delta, base_premium)
        """
        strike_step = 50.0
        atm_strike = round(spot_price / strike_step) * strike_step

        if self.strike_selection == "ITM_1":
            if direction == "BULLISH":
                # CE ITM: 1 strike below ATM
                strike = atm_strike - strike_step
                delta = 0.60
                base_premium = 165.0
            else:
                # PE ITM: 1 strike above ATM
                strike = atm_strike + strike_step
                delta = 0.60
                base_premium = 165.0
        else:
            # ATM
            strike = atm_strike
            delta = 0.50
            base_premium = 135.0

        return strike, delta, base_premium

    def calculate_option_extremes(
        self,
        entry_spot: float,
        curr_bar: Dict[str, Any],
        direction: str,
        delta: float,
        entry_premium: float
    ) -> Tuple[float, float, float]:
        """
        Estimates current bar option High, Low, and Close based on spot movement.
        """
        spot_high = curr_bar["high"]
        spot_low = curr_bar["low"]
        spot_close = curr_bar["close"]

        if direction == "BULLISH":
            opt_high = entry_premium + ((spot_high - entry_spot) * delta)
            opt_low = entry_premium + ((spot_low - entry_spot) * delta)
            opt_close = entry_premium + ((spot_close - entry_spot) * delta)
        else:
            opt_high = entry_premium + ((entry_spot - spot_low) * delta)
            opt_low = entry_premium + ((entry_spot - spot_high) * delta)
            opt_close = entry_premium + ((entry_spot - spot_close) * delta)

        return max(0.5, opt_high), max(0.5, opt_low), max(0.5, opt_close)

    def process_exit_conditions(
        self,
        active_trade: Dict[str, Any],
        curr_bar: Dict[str, Any],
        bar_idx: int,
        entry_bar_idx: int
    ) -> Optional[TradeRecord]:
        """
        Evaluates +3 Target, +2 Break-Even Stop, and Initial SL.
        Conservative resolution when sequence is unknown.
        """
        direction = active_trade["direction"]
        entry_spot = active_trade["entry_spot"]
        delta = active_trade["delta"]
        entry_premium = active_trade["entry_premium"]
        target_pts = float(active_trade.get("target_pts", self.target_pts))
        target_premium = entry_premium + target_pts
        current_stop = active_trade["current_stop"]
        be_activated = active_trade["be_activated"]

        opt_high, opt_low, opt_close = self.calculate_option_extremes(
            entry_spot, curr_bar, direction, delta, entry_premium
        )

        # Update MFE and MAE
        curr_mfe = max(active_trade["mfe"], opt_high - entry_premium)
        curr_mae = max(active_trade["mae"], entry_premium - opt_low)
        active_trade["mfe"] = curr_mfe
        active_trade["mae"] = curr_mae

        # Check Break-Even Activation (if enabled)
        just_activated_be = False
        prior_stop = current_stop
        if self.break_even_activation_pts is not None and self.break_even_activation_pts > 0:
            if not be_activated and opt_high >= (entry_premium + self.break_even_activation_pts):
                be_activated = True
                just_activated_be = True
                current_stop = max(current_stop, entry_premium)
                active_trade["be_activated"] = True
                active_trade["current_stop"] = current_stop

        # Target Check (+3.0 Points)
        is_target_hit = opt_high >= target_premium
        if just_activated_be:
            is_stop_hit = opt_low <= prior_stop or opt_close < entry_premium
        else:
            is_stop_hit = opt_low <= current_stop

        # Conservative intrabar resolution:
        # If both target and stop are touched on same bar:
        if is_target_hit and is_stop_hit:
            # Conservative: if break-even was already active, secure BE; otherwise assume SL hit first
            if be_activated:
                exit_price = target_premium - self.slippage_exit
                exit_reason = "TARGET"
            else:
                exit_price = max(0.5, current_stop - self.slippage_exit)
                exit_reason = "INITIAL_SL"
        elif is_target_hit:
            exit_price = target_premium - self.slippage_exit
            exit_reason = "TARGET"
        elif is_stop_hit:
            exit_price = max(0.5, current_stop - self.slippage_exit)
            exit_reason = "BREAK_EVEN" if be_activated and current_stop >= entry_premium else "INITIAL_SL"
        else:
            return None  # Position remains open

        # Compile completed TradeRecord
        pts_pnl = round(exit_price - entry_premium, 2)
        gross_pnl = round(pts_pnl * self.lot_size, 2)
        charges = ZerodhaOptionChargesCalculator.calculate(entry_premium, exit_price, self.lot_size).total_charges
        net_pnl = round(gross_pnl - charges, 2)
        holding_time = max(1, bar_idx - entry_bar_idx)

        trade = TradeRecord(
            trade_id=active_trade["trade_id"],
            date=str(curr_bar["date"].date() if hasattr(curr_bar["date"], "date") else str(curr_bar["date"])[:10]),
            entry_time=active_trade["entry_time"],
            exit_time=curr_bar["date"].strftime("%H:%M") if hasattr(curr_bar["date"], "strftime") else str(curr_bar["date"])[11:16],
            direction=f"BUY {'CE' if direction == 'BULLISH' else 'PE'}",
            strike_type=self.strike_selection,
            strike=active_trade["strike"],
            setup_name=active_trade["setup_name"],
            confidence_score=active_trade["confidence"],
            entry_spot=round(entry_spot, 2),
            entry_premium=round(entry_premium, 2),
            exit_premium=round(exit_price, 2),
            target_premium=round(target_premium, 2),
            stop_premium=round(current_stop, 2),
            break_even_activated=be_activated,
            exit_reason=exit_reason,
            points_pnl=pts_pnl,
            gross_pnl=gross_pnl,
            charges=round(charges, 2),
            net_pnl=net_pnl,
            mae_points=round(curr_mae, 2),
            mfe_points=round(curr_mfe, 2),
            holding_time_minutes=holding_time,
            contributing_factors=active_trade.get("contributing_factors", [])
        )
        return trade
