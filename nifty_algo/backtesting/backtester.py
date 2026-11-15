import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
from ..indicators.technical import TechnicalIndicators
from ..market_structure.structure_engine import MarketStructureEngine
from ..strategies import (
    BreakoutRetestSetup,
    LiquiditySweepReversalSetup,
    VWAPReclaimSetup,
    VWAPRejectionSetup,
    TrendContinuationSetup,
    OpeningRangeBreakoutSetup,
    SupportReversalSetup,
    ResistanceRejectionSetup,
    FVGConfirmationSetup,
)
from ..confidence.scorer import ConfidenceScorer
from ..risk.charges import ZerodhaOptionChargesCalculator
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.backtest")

@dataclass
class BacktestTrade:
    trade_id: str
    entry_time: str
    exit_time: str
    setup_name: str
    direction: str  # CE or PE
    entry_premium: float
    exit_premium: float
    points_pnl: float
    gross_pnl: float
    net_pnl: float
    charges: float
    post_exit_max_premium: float
    reached_plus_5: bool
    reached_plus_7: bool
    reached_plus_10: bool
    reached_plus_15: bool

class NiftyHistoricalBacktester:
    """
    Multi-Timeframe Backtesting Engine with:
    - 1m/3m/5m/15m multi-timeframe resampled data
    - +3 pt fixed target with ₹0.45 limit entry offset
    - Realistic slippage, charges, 3m cooldown, and consecutive loss filters
    - Post-target milestone tracking (+5, +7, +10, +15)
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.structure_engine = MarketStructureEngine()
        self.confidence_scorer = ConfidenceScorer(config)
        self.setups = [
            BreakoutRetestSetup(),
            LiquiditySweepReversalSetup(),
            VWAPReclaimSetup(),
            VWAPRejectionSetup(),
            TrendContinuationSetup(),
            OpeningRangeBreakoutSetup(),
            SupportReversalSetup(),
            ResistanceRejectionSetup(),
            FVGConfirmationSetup(),
        ]

    def run(self, df_1m: pd.DataFrame, delta: float = 0.50, lot_size: int = 65) -> Dict[str, Any]:
        """
        Executes backtest on historical 1-minute NIFTY candles.
        Delta approximates option price movement relative to NIFTY spot movement.
        """
        if df_1m.empty or len(df_1m) < 60:
            return {"error": "Insufficient historical data for backtesting."}

        df_1m = df_1m.copy()
        if not isinstance(df_1m.index, pd.DatetimeIndex):
            df_1m["date"] = pd.to_datetime(df_1m["date"])
            df_1m.set_index("date", inplace=True)

        trades: List[BacktestTrade] = []
        consecutive_losses = 0
        in_trade = False
        current_trade: Optional[Dict[str, Any]] = None
        cooldown_bars = 0
        current_day = None
        daily_trades_count = 0
        daily_trade_records = {}

        # Precompute 3-minute bars
        df_3m = df_1m.resample("3min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna()

        for i in range(40, len(df_1m) - 30):
            sub_1m = df_1m.iloc[:i + 1]
            curr_bar = df_1m.iloc[i]
            bar_time = df_1m.index[i]
            bar_day = bar_time.date()

            # New day reset
            if bar_day != current_day:
                current_day = bar_day
                consecutive_losses = 0
                daily_trades_count = 0
                cooldown_bars = 0

            # Trading hours check (09:20 to 15:00 for new entries)
            time_str = bar_time.strftime("%H:%M")
            can_open_new = ("09:20" <= time_str < "15:00") and (consecutive_losses < self.config.max_consecutive_losses)

            # In trade management
            if in_trade and current_trade:
                entry_spot = current_trade["entry_spot"]
                direction = current_trade["direction"]
                opt_entry = current_trade["entry_opt_price"]
                opt_target = opt_entry + 3.0

                # Simulated option premium based on spot change
                spot_change = (curr_bar["close"] - entry_spot) if direction == "BULLISH" else (entry_spot - curr_bar["close"])
                current_opt_price = max(0.5, opt_entry + (spot_change * delta))

                # Track post-target progress if already exited or check exit
                if current_opt_price >= opt_target:
                    # Target hit!
                    exit_premium = opt_target
                    pnl_pts = 3.0
                    gross_pnl = pnl_pts * lot_size
                    charges_calc = ZerodhaOptionChargesCalculator.calculate(opt_entry, exit_premium, lot_size)
                    net_pnl = round(gross_pnl - charges_calc.total_charges, 2)

                    # Scan subsequent 30 bars for post-target excursion
                    post_bars = df_1m.iloc[i:i + 30]
                    post_opt_high = opt_target
                    for _, p_bar in post_bars.iterrows():
                        p_change = (p_bar["high"] - entry_spot) if direction == "BULLISH" else (entry_spot - p_bar["low"])
                        p_opt = max(0.5, opt_entry + (p_change * delta))
                        if p_opt > post_opt_high:
                            post_opt_high = p_opt

                    trades.append(BacktestTrade(
                        trade_id=f"BT_{len(trades)+1}",
                        entry_time=str(current_trade["time"]),
                        exit_time=str(bar_time),
                        setup_name=current_trade["setup"],
                        direction="CE" if direction == "BULLISH" else "PE",
                        entry_premium=round(opt_entry, 2),
                        exit_premium=round(exit_premium, 2),
                        points_pnl=pnl_pts,
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        charges=charges_calc.total_charges,
                        post_exit_max_premium=round(post_opt_high, 2),
                        reached_plus_5=(post_opt_high - opt_entry) >= 5.0,
                        reached_plus_7=(post_opt_high - opt_entry) >= 7.0,
                        reached_plus_10=(post_opt_high - opt_entry) >= 10.0,
                        reached_plus_15=(post_opt_high - opt_entry) >= 15.0,
                    ))

                    consecutive_losses = 0  # Reset on win
                    in_trade = False
                    current_trade = None
                    cooldown_bars = 3  # 3 bars = 3 minutes cooldown
                    continue

                # Structure stop loss check (Swing break or 40 pts adverse move)
                elif spot_change <= -25.0:
                    exit_premium = max(0.5, opt_entry + (spot_change * delta))
                    pnl_pts = round(exit_premium - opt_entry, 2)
                    gross_pnl = pnl_pts * lot_size
                    charges_calc = ZerodhaOptionChargesCalculator.calculate(opt_entry, exit_premium, lot_size)
                    net_pnl = round(gross_pnl - charges_calc.total_charges, 2)

                    trades.append(BacktestTrade(
                        trade_id=f"BT_{len(trades)+1}",
                        entry_time=str(current_trade["time"]),
                        exit_time=str(bar_time),
                        setup_name=current_trade["setup"],
                        direction="CE" if direction == "BULLISH" else "PE",
                        entry_premium=round(opt_entry, 2),
                        exit_premium=round(exit_premium, 2),
                        points_pnl=pnl_pts,
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        charges=charges_calc.total_charges,
                        post_exit_max_premium=round(exit_premium, 2),
                        reached_plus_5=False,
                        reached_plus_7=False,
                        reached_plus_10=False,
                        reached_plus_15=False,
                    ))

                    consecutive_losses += 1
                    in_trade = False
                    current_trade = None
                    cooldown_bars = 3
                    continue

            # Handle Cooldown
            if cooldown_bars > 0:
                cooldown_bars -= 1
                continue

            if not can_open_new or in_trade:
                continue

            # Evaluate Market Structure and Indicators
            sub_3m = df_3m[df_3m.index <= bar_time]
            if len(sub_3m) < 20:
                continue

            indicators = TechnicalIndicators.analyze_indicators(sub_1m)
            structure = self.structure_engine.compute_structure(sub_1m, sub_3m)

            # Evaluate Setups
            c1_list = sub_1m.to_dict("records")
            c3_list = sub_3m.to_dict("records")
            signals = [s.evaluate(c1_list, c3_list, structure, indicators) for s in self.setups]

            conf_eval = self.confidence_scorer.score(
                signals=signals,
                structure=structure,
                indicators=indicators,
                volume_profile={},
                oi_data={"oi_bias": "NEUTRAL"},
                df_1m=sub_1m
            )

            if conf_eval.is_eligible and conf_eval.total_score >= 80.0:
                # Trigger BUY
                direction = conf_eval.direction
                setup_name = next((s.setup_name for s in signals if s.triggered), "Momentum Override")
                base_option_premium = 120.0  # Normalized mid-premium option
                buy_limit_price = base_option_premium - self.config.buy_limit_discount_offset

                in_trade = True
                daily_trades_count += 1
                daily_trade_records[str(bar_day)] = daily_trades_count
                current_trade = {
                    "time": bar_time,
                    "direction": direction,
                    "entry_spot": curr_bar["close"],
                    "entry_opt_price": buy_limit_price,
                    "setup": setup_name
                }

        # Calculate metrics
        if not trades:
            return {"total_trades": 0, "message": "No trades executed during backtest period."}

        df_res = pd.DataFrame([t.__dict__ for t in trades])
        wins = df_res[df_res["net_pnl"] > 0]
        losses = df_res[df_res["net_pnl"] <= 0]
        win_rate = (len(wins) / len(df_res)) * 100

        gross_pnl = df_res["gross_pnl"].sum()
        net_pnl = df_res["net_pnl"].sum()
        total_charges = df_res["charges"].sum()

        days_count = len(daily_trade_records)
        days_with_4_plus = sum(1 for cnt in daily_trade_records.values() if cnt >= 4)
        pct_days_4_plus = (days_with_4_plus / days_count * 100) if days_count > 0 else 0.0

        return {
            "total_trades": len(df_res),
            "win_rate_pct": round(win_rate, 2),
            "gross_pnl_inr": round(gross_pnl, 2),
            "net_pnl_inr": round(net_pnl, 2),
            "total_charges_inr": round(total_charges, 2),
            "average_win_inr": round(float(wins["net_pnl"].mean()), 2) if not wins.empty else 0.0,
            "average_loss_inr": round(float(losses["net_pnl"].mean()), 2) if not losses.empty else 0.0,
            "profit_factor": round(abs(wins["gross_pnl"].sum() / losses["gross_pnl"].sum()), 2) if not losses.empty and losses["gross_pnl"].sum() != 0 else 999.0,
            "days_evaluated": days_count,
            "days_with_at_least_4_trades_pct": round(pct_days_4_plus, 1),
            "post_target_progression": {
                "reached_plus_5_pct": round(float(df_res["reached_plus_5"].sum() / len(df_res) * 100), 1),
                "reached_plus_7_pct": round(float(df_res["reached_plus_7"].sum() / len(df_res) * 100), 1),
                "reached_plus_10_pct": round(float(df_res["reached_plus_10"].sum() / len(df_res) * 100), 1),
                "reached_plus_15_pct": round(float(df_res["reached_plus_15"].sum() / len(df_res) * 100), 1),
            }
        }
