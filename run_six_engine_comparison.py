import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from nifty_algo.config.config_loader import ConfigLoader, AppConfig
from nifty_algo.indicators.technical import TechnicalIndicators
from nifty_algo.market_structure.structure_engine import MarketStructureEngine
from nifty_algo.execution.trade_execution_engine import TradeExecutionEngine, TradeRecord
from nifty_algo.strategies.multi_opportunity_coordinator import MultiOpportunityCoordinator
from nifty_algo.strategies.base_setup import OpportunitySignal

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("nifty_algo.backtest_six_engines")

class SixEngineBacktestRunner:
    def __init__(self, data_path: str = "historical_data/nifty_nov05_nov13_1min.csv"):
        self.config = ConfigLoader.load("config.json")
        self.data_path = data_path
        self.structure_engine = MarketStructureEngine(min_room_pts=6.0)
        self.coordinator = MultiOpportunityCoordinator(min_confidence=78.0)

    def load_data(self) -> pd.DataFrame:
        df = pd.read_csv(self.data_path)
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def run_simulation(
        self,
        df: pd.DataFrame,
        active_engine_mask: Optional[List[str]] = None,
        strike_selection: str = "ATM",
        label: str = "ALL_SIX"
    ) -> Dict[str, Any]:
        """
        Runs backtest with optimized row slicing and fast dictionary lookups.
        """
        lot_size = 65
        exec_engine = TradeExecutionEngine(
            lot_size=lot_size,
            target_pts=3.0,
            break_even_activation_pts=2.0,
            max_premium_loss_cap=5.0,
            strike_selection=strike_selection
        )

        df = df.copy()
        df["day"] = df["date"].dt.date
        df["time_str"] = df["date"].dt.strftime("%H:%M")

        # Pre-build 3m resampled data
        df_indexed = df.set_index("date")
        df_3m_all = df_indexed.resample("3min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna().reset_index()
        df_3m_all["day"] = df_3m_all["date"].dt.date

        # Group pre-calculations
        days_in_order = sorted(df["day"].unique())
        df_records = df.to_dict("records")
        df_3m_records = df_3m_all.to_dict("records")

        # Map day start indices
        day_indices: Dict[Any, List[int]] = {}
        for idx, r in enumerate(df_records):
            d = r["day"]
            if d not in day_indices:
                day_indices[d] = []
            day_indices[d].append(idx)

        day_3m_indices: Dict[Any, List[int]] = {}
        for idx, r in enumerate(df_3m_records):
            d = r["day"]
            if d not in day_3m_indices:
                day_3m_indices[d] = []
            day_3m_indices[d].append(idx)

        # Prior day levels
        pdl_map = {}
        pdh_map = {}
        for i, d in enumerate(days_in_order):
            if i > 0:
                prev_d = days_in_order[i - 1]
                prev_idxs = day_indices[prev_d]
                prev_highs = [df_records[k]["high"] for k in prev_idxs]
                prev_lows = [df_records[k]["low"] for k in prev_idxs]
                pdh_map[d] = max(prev_highs)
                pdl_map[d] = min(prev_lows)
            else:
                pdh_map[d] = None
                pdl_map[d] = None

        trades: List[TradeRecord] = []
        active_trade: Optional[Dict[str, Any]] = None
        current_day = None
        consecutive_losses = 0
        cooldown_until_idx = -1

        total_signals = 0
        duplicate_signals_count = 0
        rejected_signals_count = 0
        rejection_reasons_counter = {}
        missed_opportunities = 0

        # Run simulation bar-by-bar
        for i in range(25, len(df_records)):
            curr_bar = df_records[i]
            bar_day = curr_bar["day"]
            time_str = curr_bar["time_str"]

            if bar_day != current_day:
                current_day = bar_day
                consecutive_losses = 0
                cooldown_until_idx = -1

            # 1. Manage Active Trade
            if active_trade:
                tr = exec_engine.process_exit_conditions(
                    active_trade=active_trade,
                    curr_bar=curr_bar,
                    bar_idx=i,
                    entry_bar_idx=active_trade["entry_bar_idx"]
                )
                if tr:
                    trades.append(tr)
                    if tr.exit_reason == "INITIAL_SL":
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                    active_trade = None
                    cooldown_until_idx = i + 1
                    continue

            # 2. Check Trading Hours & Loss Limit
            is_trading_hours = ("09:20" <= time_str < "15:00")
            # Lunch Chop Filter (11:30 - 13:00)
            if self.config.trading_hours.pause_lunch_chop:
                if self.config.trading_hours.lunch_chop_start <= time_str < self.config.trading_hours.lunch_chop_end:
                    is_trading_hours = False

            can_open = is_trading_hours and (consecutive_losses < 3) and (i >= cooldown_until_idx)

            # Slicing current day up to now
            day_idxs = day_indices[bar_day]
            start_day_idx = day_idxs[0]
            if (i - start_day_idx) < 15:
                continue

            c1_slice = df_records[start_day_idx : i + 1]
            sub_1m = df.iloc[max(0, i - 100) : i + 1]

            # 3m slice
            m3_idxs = [k for k in day_3m_indices.get(bar_day, []) if df_3m_records[k]["date"] <= curr_bar["date"]]
            if len(m3_idxs) < 5:
                continue
            c3_slice = [df_3m_records[k] for k in m3_idxs]

            indicators = TechnicalIndicators.analyze_indicators(sub_1m)
            today_1m_df = df.iloc[start_day_idx : i + 1]
            today_3m_df = df_3m_all.iloc[m3_idxs]
            structure = self.structure_engine.compute_structure(
                today_1m_df, today_3m_df, pdh=pdh_map.get(bar_day), pdl=pdl_map.get(bar_day)
            )

            # Mock OI data based on day trend
            oi_mock = {"oi_bias": "BULLISH_PE_WRITING" if indicators.get("ema_bullish") else "BEARISH_CE_WRITING", "pcr": 1.2 if indicators.get("ema_bullish") else 0.8}

            # Evaluate Engines & Arbitrate
            decision, raw_sigs = self.coordinator.evaluate_all_engines(
                candles_1m=c1_slice,
                candles_3m=c3_slice,
                structure=structure,
                indicators=indicators,
                oi_data=oi_mock,
                has_open_position=(active_trade is not None),
                bar_idx=i,
                active_engine_mask=active_engine_mask
            )

            # Record signal statistics
            triggered_sigs = [s for s in raw_sigs if s.triggered]
            total_signals += len(triggered_sigs)

            if len(triggered_sigs) > 1 and len(set(s.direction for s in triggered_sigs)) == 1:
                duplicate_signals_count += (len(triggered_sigs) - 1)

            if not decision.should_execute:
                if active_trade and len(triggered_sigs) > 0:
                    missed_opportunities += 1
                for r in decision.rejection_reasons:
                    rejection_reasons_counter[r] = rejection_reasons_counter.get(r, 0) + 1
                continue

            if not can_open:
                continue

            # Execute Trade
            dir_str = "BULLISH" if decision.direction == "CE" else "BEARISH"
            strike, delta, base_prem = exec_engine.select_strike(curr_bar["close"], dir_str)
            entry_premium = base_prem - self.config.buy_limit_discount_offset + exec_engine.slippage_entry
            initial_stop = entry_premium - exec_engine.max_premium_loss_cap

            active_trade = {
                "trade_id": f"TRD_{len(trades)+1:03d}",
                "entry_time": time_str,
                "entry_bar_idx": i,
                "direction": dir_str,
                "strike": strike,
                "delta": delta,
                "entry_spot": curr_bar["close"],
                "entry_premium": entry_premium,
                "current_stop": initial_stop,
                "be_activated": False,
                "setup_name": decision.primary_strategy,
                "confidence": decision.combined_confidence,
                "contributing_factors": decision.contributing_strategies,
                "mfe": 0.0,
                "mae": 0.0
            }

        # Compile Comprehensive Metrics
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.exit_reason == "TARGET")
        be_exits = sum(1 for t in trades if t.exit_reason == "BREAK_EVEN")
        sl_exits = sum(1 for t in trades if t.exit_reason == "INITIAL_SL")
        ce_trades = sum(1 for t in trades if t.direction == "BUY CE")
        pe_trades = sum(1 for t in trades if t.direction == "BUY PE")

        gross_pnl = sum(t.gross_pnl for t in trades)
        charges = sum(t.charges for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_wins = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
        gross_losses = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 99.9

        # Drawdown calculation
        equity_curve = []
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cum += t.net_pnl
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > max_dd:
                max_dd = dd

        # Max consecutive losses
        max_cons_losses = 0
        curr_cons = 0
        for t in trades:
            if t.exit_reason == "INITIAL_SL":
                curr_cons += 1
                if curr_cons > max_cons_losses:
                    max_cons_losses = curr_cons
            else:
                curr_cons = 0

        avg_hold = (sum(t.holding_time_minutes for t in trades) / total_trades) if total_trades > 0 else 0.0
        avg_mae = (sum(t.mae_points for t in trades) / total_trades) if total_trades > 0 else 0.0
        avg_mfe = (sum(t.mfe_points for t in trades) / total_trades) if total_trades > 0 else 0.0

        trades_per_day = round(total_trades / len(days_in_order), 1) if days_in_order else 0.0

        return {
            "label": label,
            "total_signals": total_signals,
            "executed_trades": total_trades,
            "trades_per_day": trades_per_day,
            "duplicate_merged": duplicate_signals_count,
            "missed_opportunities": missed_opportunities,
            "ce_trades": ce_trades,
            "pe_trades": pe_trades,
            "wins": wins,
            "be_exits": be_exits,
            "sl_exits": sl_exits,
            "win_rate": round(win_rate, 1),
            "gross_pnl": round(gross_pnl, 2),
            "charges": round(charges, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_dd, 2),
            "max_consecutive_losses": max_cons_losses,
            "avg_holding_time_min": round(avg_hold, 1),
            "avg_mae": round(avg_mae, 2),
            "avg_mfe": round(avg_mfe, 2),
            "rejection_reasons": rejection_reasons_counter,
            "trades": trades
        }

def run_all_engine_comparisons():
    runner = SixEngineBacktestRunner()
    df_all = runner.load_data()

    print("=" * 110)
    print("MASTER EVALUATION: SIX INDEPENDENT 3-POINT OPPORTUNITY DETECTION ENGINES (NIFTY OPTIONS)")
    print("Underlying: NIFTY | Target: +3.0 Pts | Break-Even Lock: +2.0 Pts | Filter: Lunch Chop Paused")
    print("=" * 110)

    # 1. Compare A to G on Full Dataset (ATM)
    matrix = [
        ("A. Momentum Only", ["ENGINE_1_MOMENTUM"]),
        ("B. Retest Only", ["ENGINE_2_RETEST"]),
        ("C. Trap Detection Only", ["ENGINE_3_TRAP"]),
        ("D. Breakout Only", ["ENGINE_4_BREAKOUT"]),
        ("E. FVG Imbalance Only", ["ENGINE_5_FVG"]),
        ("F. OI Intelligence Only", ["ENGINE_6_OI_INTEL"]),
        ("G. ALL SIX COMBINED", None)
    ]

    summary_rows = []
    all_runs_dict = {}

    for label, mask in matrix:
        res = runner.run_simulation(df_all, active_engine_mask=mask, strike_selection="ATM", label=label)
        all_runs_dict[label] = res
        summary_rows.append({
            "Configuration": label,
            "Signals": res["total_signals"],
            "Trades": res["executed_trades"],
            "Trd/Day": res["trades_per_day"],
            "CE/PE": f"{res['ce_trades']}/{res['pe_trades']}",
            "Target (+3)": res["wins"],
            "BE (+2)": res["be_exits"],
            "SL Exits": res["sl_exits"],
            "Win Rate": f"{res['win_rate']}%",
            "Gross P&L": f"₹{res['gross_pnl']:+,.0f}",
            "Charges": f"₹{res['charges']:,.0f}",
            "Net P&L": f"₹{res['net_pnl']:+,.0f}",
            "Profit Factor": f"{res['profit_factor']:.2f}",
            "Max DD": f"₹{res['max_drawdown']:,.0f}",
            "Avg Hold": f"{res['avg_holding_time_min']}m",
            "Merged/Missed": f"{res['duplicate_merged']}/{res['missed_opportunities']}"
        })

    df_summary = pd.DataFrame(summary_rows)
    print("\nTABLE 1: INDEPENDENT ENGINE COMPARISON (ATM OPTIONS - FULL DATASET)")
    print("=" * 110)
    print(df_summary.to_string(index=False))

    # 2. Strike Comparison: ATM vs ITM_1 (All Six Combined)
    print("\n" + "=" * 110)
    print("TABLE 2: OPTION STRIKE COMPARISON (ALL SIX COMBINED): ATM VS ONE-STEP ITM (ITM_1)")
    print("=" * 110)
    atm_res = all_runs_dict["G. ALL SIX COMBINED"]
    itm_res = runner.run_simulation(df_all, active_engine_mask=None, strike_selection="ITM_1", label="ITM_1 Combined")

    df_strikes = pd.DataFrame([
        {
            "Strike": "ATM (Delta ~0.50)",
            "Trades": atm_res["executed_trades"],
            "Win Rate": f"{atm_res['win_rate']}%",
            "Target (+3)": atm_res["wins"],
            "BE (+2)": atm_res["be_exits"],
            "SL Exits": atm_res["sl_exits"],
            "Gross P&L": f"₹{atm_res['gross_pnl']:+,.2f}",
            "Charges": f"₹{atm_res['charges']:,.2f}",
            "Net P&L": f"₹{atm_res['net_pnl']:+,.2f}",
            "Profit Factor": f"{atm_res['profit_factor']:.2f}",
            "Max DD": f"₹{atm_res['max_drawdown']:,.2f}"
        },
        {
            "Strike": "ITM_1 (Delta ~0.60)",
            "Trades": itm_res["executed_trades"],
            "Win Rate": f"{itm_res['win_rate']}%",
            "Target (+3)": itm_res["wins"],
            "BE (+2)": itm_res["be_exits"],
            "SL Exits": itm_res["sl_exits"],
            "Gross P&L": f"₹{itm_res['gross_pnl']:+,.2f}",
            "Charges": f"₹{itm_res['charges']:,.2f}",
            "Net P&L": f"₹{itm_res['net_pnl']:+,.2f}",
            "Profit Factor": f"{itm_res['profit_factor']:.2f}",
            "Max DD": f"₹{itm_res['max_drawdown']:,.2f}"
        }
    ])
    print(df_strikes.to_string(index=False))

    # 3. Walk-Forward Chronological Splits (All Six Combined ATM)
    print("\n" + "=" * 110)
    print("TABLE 3: WALK-FORWARD SPLITS (DEVELOPMENT VS VALIDATION VS OUT-OF-SAMPLE)")
    print("=" * 110)
    dev_dates = [pd.to_datetime("2026-11-05").date(), pd.to_datetime("2026-11-06").date(), pd.to_datetime("2026-11-08").date()]
    val_dates = [pd.to_datetime("2026-11-09").date(), pd.to_datetime("2026-11-11").date()]
    oos_dates = [pd.to_datetime("2026-11-12").date(), pd.to_datetime("2026-11-13").date()]

    df_dev = df_all[df_all["date"].dt.date.isin(dev_dates)].reset_index(drop=True)
    df_val = df_all[df_all["date"].dt.date.isin(val_dates)].reset_index(drop=True)
    df_oos = df_all[df_all["date"].dt.date.isin(oos_dates)].reset_index(drop=True)

    dev_res = runner.run_simulation(df_dev, active_engine_mask=None, strike_selection="ATM", label="Dev Split")
    val_res = runner.run_simulation(df_val, active_engine_mask=None, strike_selection="ATM", label="Val Split")
    oos_res = runner.run_simulation(df_oos, active_engine_mask=None, strike_selection="ATM", label="OOS Split")

    df_splits = pd.DataFrame([
        {
            "Split": "Development (Nov 05 - Nov 08)",
            "Days": len(dev_dates),
            "Trades": dev_res["executed_trades"],
            "Trd/Day": dev_res["trades_per_day"],
            "Win Rate": f"{dev_res['win_rate']}%",
            "Gross P&L": f"₹{dev_res['gross_pnl']:+,.2f}",
            "Charges": f"₹{dev_res['charges']:,.2f}",
            "Net P&L": f"₹{dev_res['net_pnl']:+,.2f}",
            "Profit Factor": f"{dev_res['profit_factor']:.2f}"
        },
        {
            "Split": "Validation (Nov 09 - Nov 11)",
            "Days": len(val_dates),
            "Trades": val_res["executed_trades"],
            "Trd/Day": val_res["trades_per_day"],
            "Win Rate": f"{val_res['win_rate']}%",
            "Gross P&L": f"₹{val_res['gross_pnl']:+,.2f}",
            "Charges": f"₹{val_res['charges']:,.2f}",
            "Net P&L": f"₹{val_res['net_pnl']:+,.2f}",
            "Profit Factor": f"{val_res['profit_factor']:.2f}"
        },
        {
            "Split": "Out-of-Sample (Nov 12 - Nov 13)",
            "Days": len(oos_dates),
            "Trades": oos_res["executed_trades"],
            "Trd/Day": oos_res["trades_per_day"],
            "Win Rate": f"{oos_res['win_rate']}%",
            "Gross P&L": f"₹{oos_res['gross_pnl']:+,.2f}",
            "Charges": f"₹{oos_res['charges']:,.2f}",
            "Net P&L": f"₹{oos_res['net_pnl']:+,.2f}",
            "Profit Factor": f"{oos_res['profit_factor']:.2f}"
        }
    ])
    print(df_splits.to_string(index=False))

    # Save output JSON & CSV
    out_data = {
        "comparison_table": summary_rows,
        "strikes": df_strikes.to_dict("records"),
        "splits": df_splits.to_dict("records"),
        "rejection_summary": atm_res["rejection_reasons"]
    }
    with open("six_engine_comparison_results.json", "w") as f:
        json.dump(out_data, f, indent=2)

    df_trades = pd.DataFrame([t.__dict__ for t in atm_res["trades"]])
    if not df_trades.empty:
        df_trades.to_csv("six_engine_combined_trades.csv", index=False)
        print("\nSaved trade-by-trade log to 'six_engine_combined_trades.csv'")
    print("Saved comparison results to 'six_engine_comparison_results.json'")

if __name__ == "__main__":
    run_all_engine_comparisons()
