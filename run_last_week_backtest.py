import os
import sys
import json
import logging
from datetime import datetime, time
import pandas as pd
import numpy as np

from nifty_algo.config.config_loader import ConfigLoader, AppConfig
from nifty_algo.indicators.technical import TechnicalIndicators
from nifty_algo.indicators.volume_profile import VolumeProfileAnalyzer
from nifty_algo.market_structure.structure_engine import MarketStructureEngine
from nifty_algo.strategies import (
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
from nifty_algo.confidence.scorer import ConfidenceScorer
from nifty_algo.risk.charges import ZerodhaOptionChargesCalculator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest_runner")

def run_backtest_last_week():
    csv_path = "historical_data/nifty_nov05_nov13_1min.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    config = ConfigLoader.load("config.json")
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    structure_engine = MarketStructureEngine(min_room_pts=config.confidence.min_room_to_opposing_level_pts)
    confidence_scorer = ConfidenceScorer(config)

    setups = [
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

    lot_size = 65
    delta = 0.50
    slippage_entry = 0.10
    slippage_exit = 0.05
    target_pts = 3.0
    discount_offset = config.buy_limit_discount_offset

    trades = []
    daily_stats = {}
    current_day = None
    consecutive_losses = 0
    in_trade = False
    active_trade = None
    cooldown_until_idx = -1

    # Filter evaluation strictly starting from Monday 2026-11-09 09:15 AM
    # Bars prior to Monday are used solely for structure / indicator warm-up!
    eval_start_date = pd.to_datetime("2026-11-09 09:15:00+05:30")
    if df["date"].dt.tz is None:
        eval_start_date = pd.to_datetime("2026-11-09 09:15:00")

    print("=" * 80)
    print("RUNNING NIFTY 50 OPTIONS-BUYING BACKTEST — LAST WEEK (NOV 09 TO NOV 13, 2026)")
    print(f"Target: Fixed +{target_pts:.1f} Option Points | BUY Limit Discount: -₹{discount_offset:.2f} | Lot Size: {lot_size}")
    print("Warm-up data: Nov 05 - Nov 08 | Active Execution Period: Nov 09 - Nov 13, 2026")
    print("=" * 80)

    # Pre-build 3-minute and 15-minute bars
    df_indexed = df.set_index("date")
    df_3m_all = df_indexed.resample("3min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    df_15m_all = df_indexed.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()

    for i in range(60, len(df)):
        curr_bar = df.iloc[i]
        bar_time = curr_bar["date"]

        # Only evaluate signals starting from Monday Nov 09
        if bar_time < eval_start_date:
            continue

        bar_day = bar_time.date()
        time_str = bar_time.strftime("%H:%M")

        # New trading day reset
        if bar_day != current_day:
            current_day = bar_day
            consecutive_losses = 0
            cooldown_until_idx = -1
            daily_stats[str(bar_day)] = {"trades": 0, "wins": 0, "losses": 0, "gross_pnl": 0.0, "net_pnl": 0.0}

        # Trading window: 09:20 AM to 15:00 PM (Pausing lunch chop 11:30 - 13:00)
        is_favorable_time = ("09:20" <= time_str < "15:00")
        if config.trading_hours.pause_lunch_chop:
            if config.trading_hours.lunch_chop_start <= time_str < config.trading_hours.lunch_chop_end:
                is_favorable_time = False

        can_open_new = is_favorable_time and (consecutive_losses < config.max_consecutive_losses) and (i >= cooldown_until_idx)

        # 1. Manage Active Trade
        if in_trade and active_trade:
            entry_spot = active_trade["entry_spot"]
            direction = active_trade["direction"]
            opt_entry = active_trade["entry_opt_price"]
            opt_target = opt_entry + target_pts

            # Option price estimation using high/low extremes of current bar
            if direction == "BULLISH":
                opt_high = opt_entry + ((curr_bar["high"] - entry_spot) * delta)
                opt_low = opt_entry + ((curr_bar["low"] - entry_spot) * delta)
                spot_adverse = entry_spot - curr_bar["low"]
            else:
                opt_high = opt_entry + ((entry_spot - curr_bar["low"]) * delta)
                opt_low = opt_entry + ((entry_spot - curr_bar["high"]) * delta)
                spot_adverse = curr_bar["high"] - entry_spot

            # A. Target Check (+3.0 Points)
            if opt_high >= opt_target:
                exit_price = opt_target - slippage_exit
                points_pnl = round(exit_price - opt_entry, 2)
                gross_pnl = round(points_pnl * lot_size, 2)
                charges = ZerodhaOptionChargesCalculator.calculate(opt_entry, exit_price, lot_size)
                net_pnl = round(gross_pnl - charges.total_charges, 2)

                # Track subsequent 30 bars (30 minutes) post-target excursion
                post_bars = df.iloc[i:min(i + 31, len(df))]
                post_high = opt_target
                for _, pb in post_bars.iterrows():
                    p_diff = (pb["high"] - entry_spot) if direction == "BULLISH" else (entry_spot - pb["low"])
                    p_price = opt_entry + (p_diff * delta)
                    if p_price > post_high:
                        post_high = p_price

                add_pts = round(post_high - opt_target, 2)
                reached_5 = (post_high - opt_entry) >= 5.0
                reached_7 = (post_high - opt_entry) >= 7.0
                reached_10 = (post_high - opt_entry) >= 10.0
                reached_15 = (post_high - opt_entry) >= 15.0

                trades.append({
                    "trade_id": f"TRD_{len(trades)+1:02d}",
                    "date": str(bar_day),
                    "entry_time": active_trade["time"].strftime("%H:%M"),
                    "exit_time": bar_time.strftime("%H:%M"),
                    "direction": "BUY CE" if direction == "BULLISH" else "BUY PE",
                    "setup": active_trade["setup"],
                    "confidence": active_trade["confidence"],
                    "entry_spot": round(entry_spot, 2),
                    "entry_opt": round(opt_entry, 2),
                    "exit_opt": round(exit_price, 2),
                    "pts_pnl": points_pnl,
                    "gross_pnl": gross_pnl,
                    "charges": charges.total_charges,
                    "net_pnl": net_pnl,
                    "post_high": round(post_high, 2),
                    "additional_pts": add_pts,
                    "reached_5": reached_5,
                    "reached_7": reached_7,
                    "reached_10": reached_10,
                    "reached_15": reached_15,
                    "result": "WIN"
                })

                daily_stats[str(bar_day)]["trades"] += 1
                daily_stats[str(bar_day)]["wins"] += 1
                daily_stats[str(bar_day)]["gross_pnl"] += gross_pnl
                daily_stats[str(bar_day)]["net_pnl"] += net_pnl
                consecutive_losses = 0
                in_trade = False
                active_trade = None
                cooldown_until_idx = i + 3  # 3 minutes cooldown
                continue

            # B. Invalidation / Stop Loss Check
            max_loss_inr = config.risk.max_loss_per_trade_inr or 450.0
            max_opt_loss_pts = max_loss_inr / lot_size
            opt_drawdown = opt_entry - opt_low
            
            if opt_drawdown >= max_opt_loss_pts or spot_adverse >= 15.0:
                loss_pts = min(opt_drawdown, max_opt_loss_pts)
                exit_price = max(0.5, opt_entry - loss_pts - slippage_exit)
                points_pnl = round(exit_price - opt_entry, 2)
                gross_pnl = round(points_pnl * lot_size, 2)
                charges = ZerodhaOptionChargesCalculator.calculate(opt_entry, exit_price, lot_size)
                net_pnl = round(gross_pnl - charges.total_charges, 2)

                trades.append({
                    "trade_id": f"TRD_{len(trades)+1:02d}",
                    "date": str(bar_day),
                    "entry_time": active_trade["time"].strftime("%H:%M"),
                    "exit_time": bar_time.strftime("%H:%M"),
                    "direction": "BUY CE" if direction == "BULLISH" else "BUY PE",
                    "setup": active_trade["setup"],
                    "confidence": active_trade["confidence"],
                    "entry_spot": round(entry_spot, 2),
                    "entry_opt": round(opt_entry, 2),
                    "exit_opt": round(exit_price, 2),
                    "pts_pnl": points_pnl,
                    "gross_pnl": gross_pnl,
                    "charges": charges.total_charges,
                    "net_pnl": net_pnl,
                    "post_high": round(exit_price, 2),
                    "additional_pts": 0.0,
                    "reached_5": False,
                    "reached_7": False,
                    "reached_10": False,
                    "reached_15": False,
                    "result": "LOSS"
                })

                daily_stats[str(bar_day)]["trades"] += 1
                daily_stats[str(bar_day)]["losses"] += 1
                daily_stats[str(bar_day)]["gross_pnl"] += gross_pnl
                daily_stats[str(bar_day)]["net_pnl"] += net_pnl
                consecutive_losses += 1
                in_trade = False
                active_trade = None
                cooldown_until_idx = i + 3
                continue

        # If already in trade or cannot open new, skip signal evaluation
        if in_trade or not can_open_new:
            continue

        # 2. Evaluate Signals
        # Intraday bars for current session structure & ORB
        today_1m = df[(df["date"].dt.date == bar_day) & (df["date"] <= bar_time)]
        today_3m = df_3m_all[(df_3m_all["date"].dt.date == bar_day) & (df_3m_all["date"] <= bar_time)]
        
        if len(today_1m) < 15:
            continue

        # Trailing bars for smooth indicators
        sub_1m = df.iloc[max(0, i - 120):i + 1]

        # Prior trading day PDH / PDL
        prev_dates = [d for d in df["date"].dt.date.unique() if d < bar_day]
        prev_day = prev_dates[-1] if prev_dates else None
        pdh, pdl = None, None
        if prev_day:
            prev_df = df[df["date"].dt.date == prev_day]
            pdh = float(prev_df["high"].max())
            pdl = float(prev_df["low"].min())

        indicators = TechnicalIndicators.analyze_indicators(sub_1m)
        structure = structure_engine.compute_structure(today_1m, today_3m, pdh=pdh, pdl=pdl)
        volume_profile = VolumeProfileAnalyzer.calculate_profile(today_1m)

        c1_list = today_1m.to_dict("records")
        c3_list = today_3m.to_dict("records")

        signals = [s.evaluate(c1_list, c3_list, structure, indicators) for s in setups]

        conf_eval = confidence_scorer.score(
            signals=signals,
            structure=structure,
            indicators=indicators,
            volume_profile=volume_profile,
            oi_data={"oi_bias": "NEUTRAL"},
            df_1m=today_1m
        )

        if conf_eval.is_eligible and conf_eval.total_score >= config.confidence.min_entry_score:
            direction = conf_eval.direction

            # 15-Minute Trend Alignment Confluence Filter (Section 6)
            sub_15m = df_15m_all[df_15m_all["date"] <= bar_time]
            if not sub_15m.empty and len(sub_15m) >= 5:
                ind_15m = TechnicalIndicators.analyze_indicators(sub_15m)
                if direction == "BULLISH" and ind_15m.get("ema_bearish") and ind_15m.get("price_below_vwap"):
                    continue
                if direction == "BEARISH" and ind_15m.get("ema_bullish") and ind_15m.get("price_above_vwap"):
                    continue

            trig_setup = next((s for s in signals if s.triggered), None)
            setup_name = trig_setup.setup_name if trig_setup else "Momentum Override"

            # Synthetic option pricing based on ATM strike (~130 premium for NIFTY)
            base_opt_price = 135.0
            # Limit entry price = quote - 0.45 + slippage
            entry_opt_price = round(base_opt_price - discount_offset + slippage_entry, 2)

            in_trade = True
            active_trade = {
                "time": bar_time,
                "direction": direction,
                "entry_spot": curr_bar["close"],
                "entry_opt_price": entry_opt_price,
                "setup": setup_name,
                "confidence": conf_eval.total_score
            }

    # 3. Compile and Output Report
    df_trades = pd.DataFrame(trades)
    return df_trades, daily_stats

if __name__ == "__main__":
    df_res, daily_summary = run_backtest_last_week()
    if not df_res.empty:
        total = len(df_res)
        wins = df_res[df_res["result"] == "WIN"]
        losses = df_res[df_res["result"] == "LOSS"]
        win_rate = len(wins) / total * 100
        gross_tot = df_res["gross_pnl"].sum()
        net_tot = df_res["net_pnl"].sum()
        charges_tot = df_res["charges"].sum()

        r5 = df_res["reached_5"].sum() / total * 100
        r7 = df_res["reached_7"].sum() / total * 100
        r10 = df_res["reached_10"].sum() / total * 100
        r15 = df_res["reached_15"].sum() / total * 100

        print("\n" + "=" * 80)
        print("OVERALL PERFORMANCE SUMMARY (LAST WEEK: NOV 09 - NOV 13, 2026)")
        print("=" * 80)
        print(f"Total Completed Trades : {total}")
        print(f"Winning Trades         : {len(wins)} ({win_rate:.1f}%)")
        print(f"Losing Trades          : {len(losses)} ({100 - win_rate:.1f}%)")
        print(f"Total Gross P&L        : ₹{gross_tot:+,.2f}")
        print(f"Statutory Charges      : ₹{charges_tot:,.2f}")
        print(f"Total Net P&L          : ₹{net_tot:+,.2f}")
        print(f"Average Profit / Trade : ₹{net_tot / total:+,.2f}")
        print(f"Profit Factor          : {abs(wins['gross_pnl'].sum() / losses['gross_pnl'].sum()):.2f}" if len(losses) > 0 and losses['gross_pnl'].sum() != 0 else "Profit Factor: 999.00 (No gross losses)")

        print("\n" + "-" * 80)
        print("POST-TARGET MILESTONE EXCURSION (% Reaching Higher Targets After +3 Exit):")
        print("-" * 80)
        print(f"  • Reached +5.0  Points : {r5:.1f}% of trades")
        print(f"  • Reached +7.0  Points : {r7:.1f}% of trades")
        print(f"  • Reached +10.0 Points : {r10:.1f}% of trades")
        print(f"  • Reached +15.0 Points : {r15:.1f}% of trades")
        print(f"  • Avg Additional Points: +{df_res['additional_pts'].mean():.2f} pts after target")

        print("\n" + "-" * 80)
        print("DAY-BY-DAY BREAKDOWN:")
        print("-" * 80)
        for day, stats in daily_summary.items():
            if stats["trades"] > 0:
                w_rate = (stats["wins"] / stats["trades"]) * 100
                print(f"  📅 {day} | Trades: {stats['trades']} | Win Rate: {w_rate:.0f}% | Gross: ₹{stats['gross_pnl']:+,.2f} | Net: ₹{stats['net_pnl']:+,.2f}")
            else:
                print(f"  📅 {day} | Trades: 0 (No qualifying setup >= 80 confidence)")

        print("\n" + "-" * 80)
        print("PERFORMANCE BY SETUP ENGINE:")
        print("-" * 80)
        setup_group = df_res.groupby("setup").agg(
            total_trades=("trade_id", "count"),
            wins=("result", lambda s: (s == "WIN").sum()),
            net_pnl=("net_pnl", "sum")
        )
        setup_group["win_rate"] = (setup_group["wins"] / setup_group["total_trades"] * 100).round(1)
        print(setup_group.to_string())

        print("\n" + "-" * 80)
        print("INDIVIDUAL TRADE EXECUTION LOG:")
        print("-" * 80)
        cols_show = ["trade_id", "date", "entry_time", "exit_time", "direction", "setup", "pts_pnl", "net_pnl", "additional_pts", "result"]
        print(df_res[cols_show].to_string(index=False))
        print("=" * 80)

        # Save results to json
        out_summary = {
            "period": "2026-11-09 to 2026-11-13",
            "total_trades": total,
            "win_rate": round(win_rate, 2),
            "net_pnl": round(net_tot, 2),
            "gross_pnl": round(gross_tot, 2),
            "charges": round(charges_tot, 2),
            "post_target_milestones": {"plus_5": r5, "plus_7": r7, "plus_10": r10, "plus_15": r15},
            "daily_stats": daily_summary
        }
        with open("last_week_backtest_results.json", "w") as f:
            json.dump(out_summary, f, indent=2)
        df_res.to_csv("last_week_backtest_trades.csv", index=False)
        print("\nSaved detailed trade log to 'last_week_backtest_trades.csv'")
        print("Saved summary to 'last_week_backtest_results.json'")
    else:
        print("No trades triggered.")
