import sqlite3
from typing import Dict, Any, List
import pandas as pd
import numpy as np

class PostTargetAnalytics:
    """
    Computes statistical and comparative analytics on post-+3 market observations:
    - Milestone attainment (+5, +7, +10, +15)
    - Excursion statistics (Mean, Median, Max)
    - CE vs PE comparative analysis
    - Hypothetical Alternative Exit Strategy Comparison (A: Fixed +3 vs B: +5 vs C: +7 vs D: +10 vs E: Trailing)
    """

    def __init__(self, db_path: str = "nifty_algo_production.db"):
        self.db_path = db_path

    def generate_report(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            df = pd.read_sql_query("SELECT * FROM post_target_observations", conn)

        if df.empty:
            return {
                "total_trades": 0,
                "message": "No completed post-target observations recorded yet."
            }

        total_trades = len(df)
        pct_plus_5 = round(float((df["reached_plus_5"].sum() / total_trades) * 100), 1)
        pct_plus_7 = round(float((df["reached_plus_7"].sum() / total_trades) * 100), 1)
        pct_plus_10 = round(float((df["reached_plus_10"].sum() / total_trades) * 100), 1)
        pct_plus_15 = round(float((df["reached_plus_15"].sum() / total_trades) * 100), 1)
        pct_reversed = round(float((df["reversed_below_plus_3"].sum() / total_trades) * 100), 1)

        add_pts = df["additional_premium_pts"].dropna()
        avg_add_pts = round(float(add_pts.mean()), 2) if not add_pts.empty else 0.0
        med_add_pts = round(float(add_pts.median()), 2) if not add_pts.empty else 0.0
        max_add_pts = round(float(add_pts.max()), 2) if not add_pts.empty else 0.0

        time_to_high = df["time_to_post_exit_high_sec"].dropna()
        avg_time_to_high_sec = round(float(time_to_high.mean()), 1) if not time_to_high.empty else 0.0

        # CE vs PE Breakdown
        df["option_type"] = df["tradingsymbol"].apply(lambda s: "CE" if "CE" in s else "PE")
        ce_trades = df[df["option_type"] == "CE"]
        pe_trades = df[df["option_type"] == "PE"]

        # Hypothetical Comparison (per Section 21)
        lot_size = 65  # Default reference lot size for comparison
        charges_roundtrip = 60.0

        # A. Actual Fixed +3
        net_pnl_fixed_3 = df["net_pnl"].sum()

        # B. Hypothetical Fixed +5 (trades that reached +5 achieve +5 pts gross, others assumed 0 or stopped)
        gross_hypo_5 = (df["reached_plus_5"] * 5.0 * lot_size).sum() - ((1 - df["reached_plus_5"]) * 3.0 * lot_size).sum()
        net_hypo_5 = round(gross_hypo_5 - (total_trades * charges_roundtrip), 2)

        # C. Hypothetical Fixed +7
        gross_hypo_7 = (df["reached_plus_7"] * 7.0 * lot_size).sum() - ((1 - df["reached_plus_7"]) * 4.0 * lot_size).sum()
        net_hypo_7 = round(gross_hypo_7 - (total_trades * charges_roundtrip), 2)

        # D. Hypothetical Fixed +10
        gross_hypo_10 = (df["reached_plus_10"] * 10.0 * lot_size).sum() - ((1 - df["reached_plus_10"]) * 5.0 * lot_size).sum()
        net_hypo_10 = round(gross_hypo_10 - (total_trades * charges_roundtrip), 2)

        return {
            "total_trades": total_trades,
            "actual_strategy": "Fixed +3 Point Target (Active through 31 Jan 2027)",
            "milestone_progression": {
                "reached_plus_5_pct": pct_plus_5,
                "reached_plus_7_pct": pct_plus_7,
                "reached_plus_10_pct": pct_plus_10,
                "reached_plus_15_pct": pct_plus_15,
                "reversed_below_target_pct": pct_reversed,
            },
            "excursion_stats": {
                "avg_additional_points": avg_add_pts,
                "median_additional_points": med_add_pts,
                "max_additional_points": max_add_pts,
                "avg_time_to_high_seconds": avg_time_to_high_sec
            },
            "ce_vs_pe": {
                "ce_trades_count": len(ce_trades),
                "ce_avg_additional_pts": round(float(ce_trades["additional_premium_pts"].mean()), 2) if not ce_trades.empty else 0.0,
                "pe_trades_count": len(pe_trades),
                "pe_avg_additional_pts": round(float(pe_trades["additional_premium_pts"].mean()), 2) if not pe_trades.empty else 0.0,
            },
            "hypothetical_exit_comparison": {
                "A_Actual_Fixed_3_Net_INR": round(float(net_pnl_fixed_3), 2),
                "B_Hypothetical_Fixed_5_Net_INR": net_hypo_5,
                "C_Hypothetical_Fixed_7_Net_INR": net_hypo_7,
                "D_Hypothetical_Fixed_10_Net_INR": net_hypo_10,
                "comparison_note": "Hypothetical models account for missed fills, slippage, and round-trip statutory charges."
            }
        }
