import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from ..config.config_loader import ConfigLoader, AppConfig
from ..indicators.technical import TechnicalIndicators
from ..indicators.volume_profile import VolumeProfileAnalyzer
from ..market_structure.structure_engine import MarketStructureEngine
from ..strategies.opportunity_engine import OpportunityEngine, OpportunityDecision
from ..strategies.support_resistance_engine import SupportResistanceEngine
from ..strategies.day_high_low_engine import DayHighLowEngine
from ..strategies.bos_engine import BOSEngine
from ..strategies.fvg_engine import FVGEngine
from ..strategies.candle_pattern_engine import CandlePatternEngine
from ..strategies.oi_analysis_engine import OIAnalysisEngine
from ..execution.trade_execution_engine import TradeExecutionEngine, TradeRecord
from .performance_report import PerformanceReporter, PerformanceMetrics

logger = logging.getLogger("nifty_algo.backtest_comparison")

class BacktestComparisonRunner:
    """
    Comprehensive Comparative Backtester (Section 10 & 11)
    Compares 8 Modes/Setups:
    1. Support/Resistance Setup
    2. Day High/Low Setup
    3. BOS Setup
    4. FVG Setup
    5. Candle Pattern Setup
    6. OI-Assisted Setup
    7. Opportunity Mode (Primary)
    8. High-Conviction Mode
    Tests ATM and one-step ITM options separately.
    Splits: Development, Validation, and Out-of-Sample.
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        data_path: str = "historical_data/nifty_nov05_nov13_1min.csv"
    ):
        self.config = config or ConfigLoader.load("config.json")
        self.data_path = data_path
        self.structure_engine = MarketStructureEngine(min_room_pts=6.0)

    def load_data(self) -> pd.DataFrame:
        df = pd.read_csv(self.data_path)
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def run_simulation(
        self,
        df: pd.DataFrame,
        mode: str = "OPPORTUNITY",
        specific_setup: Optional[str] = None,
        strike_selection: str = "ATM",
        split_name: str = "Full Dataset"
    ) -> Tuple[List[TradeRecord], PerformanceMetrics]:
        lot_size = 65
        exec_engine = TradeExecutionEngine(
            lot_size=lot_size,
            target_pts=self.config.target_premium_points,
            break_even_activation_pts=2.0,
            max_premium_loss_cap=5.0,
            strike_selection=strike_selection
        )

        opp_engine = OpportunityEngine(
            mode=mode,
            opportunity_min_score=self.config.confidence.min_entry_score,
            high_conviction_min_score=85.0
        )

        # Pre-build 3-minute and 15-minute bars
        df_indexed = df.set_index("date")
        df_3m_all = df_indexed.resample("3min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna().reset_index()
        df_15m_all = df_indexed.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna().reset_index()

        trades: List[TradeRecord] = []
        active_trade: Optional[Dict[str, Any]] = None
        current_day = None
        consecutive_losses = 0
        cooldown_until_idx = -1
        missed_opportunities = 0

        for i in range(30, len(df)):
            curr_bar = df.iloc[i].to_dict()
            bar_time = curr_bar["date"]
            bar_day = bar_time.date()
            time_str = bar_time.strftime("%H:%M")

            # Day Reset
            if bar_day != current_day:
                current_day = bar_day
                consecutive_losses = 0
                cooldown_until_idx = -1

            # 1. Manage Open Position (if any)
            if active_trade:
                trade_record = exec_engine.process_exit_conditions(
                    active_trade=active_trade,
                    curr_bar=curr_bar,
                    bar_idx=i,
                    entry_bar_idx=active_trade["entry_bar_idx"]
                )
                if trade_record:
                    trades.append(trade_record)
                    if trade_record.exit_reason == "INITIAL_SL":
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0  # Win or BE resets loss count
                    active_trade = None
                    cooldown_until_idx = i + 1  # 60s cooldown
                    continue

            # 2. Check Trading Window & Circuit Breakers
            is_trading_hours = ("09:20" <= time_str < "15:00")
            # Lunch Chop filter (11:30 - 13:00)
            if self.config.trading_hours.pause_lunch_chop:
                if self.config.trading_hours.lunch_chop_start <= time_str < self.config.trading_hours.lunch_chop_end:
                    is_trading_hours = False

            can_open_new = is_trading_hours and (consecutive_losses < self.config.max_consecutive_losses) and (i >= cooldown_until_idx)

            # Slicing current day bars
            today_1m = df[(df["date"].dt.date == bar_day) & (df["date"] <= bar_time)]
            today_3m = df_3m_all[(df_3m_all["date"].dt.date == bar_day) & (df_3m_all["date"] <= bar_time)]
            if len(today_1m) < 15:
                continue

            sub_1m = df.iloc[max(0, i - 120):i + 1]
            sub_15m = df_15m_all[df_15m_all["date"] <= bar_time]

            # Prior day levels
            prev_dates = [d for d in df["date"].dt.date.unique() if d < bar_day]
            prev_day = prev_dates[-1] if prev_dates else None
            pdh, pdl = None, None
            if prev_day:
                prev_df = df[df["date"].dt.date == prev_day]
                pdh = float(prev_df["high"].max())
                pdl = float(prev_df["low"].min())

            indicators = TechnicalIndicators.analyze_indicators(sub_1m)
            structure = self.structure_engine.compute_structure(today_1m, today_3m, pdh=pdh, pdl=pdl)
            c1_list = today_1m.to_dict("records")
            c3_list = today_3m.to_dict("records")

            # 3. Evaluate Setup Signal
            if specific_setup:
                # Evaluating a single standalone setup engine
                if specific_setup == "SETUP_SUPPORT_RESISTANCE":
                    sig = opp_engine.sr_engine.evaluate(c1_list, c3_list, structure, indicators)
                elif specific_setup == "SETUP_DAY_HIGH_LOW":
                    sig = opp_engine.dhl_engine.evaluate(c1_list, c3_list, structure, indicators)
                elif specific_setup == "SETUP_BOS":
                    sig = opp_engine.bos_engine.evaluate(c1_list, c3_list, structure, indicators)
                elif specific_setup == "SETUP_FVG":
                    sig = opp_engine.fvg_engine.evaluate(c1_list, c3_list, structure, indicators)
                elif specific_setup == "SETUP_CANDLE_PATTERN":
                    sig = opp_engine.candle_engine.evaluate(c1_list, c3_list, structure, indicators)
                elif specific_setup == "SETUP_OI_ASSISTED":
                    sig = opp_engine.oi_engine.evaluate(c1_list, c3_list, structure, indicators, oi_data={"oi_bias": "BULLISH_PE_WRITING", "pcr": 1.3})
                else:
                    continue

                if sig.triggered and sig.confidence >= self.config.confidence.min_entry_score:
                    decision = OpportunityDecision(
                        mode="STANDALONE", should_enter=True, direction=sig.direction,
                        primary_setup=sig.setup_name, confidence_score=sig.confidence,
                        entry_price=curr_bar["close"], invalidation_level=sig.invalidation_level,
                        reasons=[sig.reason], supporting_categories=[sig.supporting_factors.get("category", "")],
                        all_signals=[sig]
                    )
                else:
                    decision = OpportunityDecision("STANDALONE", False, None, "None", 0.0, 0.0, 0.0, [], [], [])
            else:
                # Opportunity Mode or High-Conviction Mode
                decision = opp_engine.evaluate_opportunity(
                    candles_1m=c1_list,
                    candles_3m=c3_list,
                    structure=structure,
                    indicators=indicators,
                    oi_data={"oi_bias": "NEUTRAL", "pcr": 1.0}
                )

            # Check missed opportunity if signal occurred while in active position
            if decision.should_enter and active_trade:
                missed_opportunities += 1
                continue

            if not decision.should_enter or not can_open_new:
                continue

            # 15m Trend Alignment Context (Section 6)
            if not sub_15m.empty and len(sub_15m) >= 5:
                ind_15m = TechnicalIndicators.analyze_indicators(sub_15m)
                if decision.direction == "BULLISH" and ind_15m.get("ema_bearish") and ind_15m.get("price_below_vwap"):
                    continue
                if decision.direction == "BEARISH" and ind_15m.get("ema_bullish") and ind_15m.get("price_above_vwap"):
                    continue

            # 4. Immediate Execution
            strike, delta, base_prem = exec_engine.select_strike(curr_bar["close"], decision.direction)
            entry_premium = base_prem - self.config.buy_limit_discount_offset + exec_engine.slippage_entry
            initial_stop = entry_premium - exec_engine.max_premium_loss_cap

            active_trade = {
                "trade_id": f"TRD_{len(trades)+1:02d}",
                "entry_time": time_str,
                "entry_bar_idx": i,
                "direction": decision.direction,
                "strike": strike,
                "delta": delta,
                "entry_spot": curr_bar["close"],
                "entry_premium": round(entry_premium, 2),
                "current_stop": round(initial_stop, 2),
                "be_activated": False,
                "mfe": 0.0,
                "mae": 0.0,
                "setup_name": decision.primary_setup,
                "confidence": decision.confidence_score,
                "contributing_factors": decision.supporting_categories
            }

        # Calculate metrics
        metrics = PerformanceReporter.calculate_metrics(
            trades=trades,
            mode_name=specific_setup or mode,
            strike_type=strike_selection,
            data_split=split_name,
            missed_opportunities=missed_opportunities
        )
        return trades, metrics
