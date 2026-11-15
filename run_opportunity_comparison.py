import os
import json
import logging
import pandas as pd
from nifty_algo.config.config_loader import ConfigLoader
from nifty_algo.backtesting.backtest_comparison import BacktestComparisonRunner

logging.basicConfig(level=logging.WARNING)

def run_all_comparisons():
    config = ConfigLoader.load("config.json")
    runner = BacktestComparisonRunner(config=config)
    df_all = runner.load_data()

    # Define Data Splits
    # Development: Nov 05 - Nov 08
    # Validation: Nov 09 - Nov 11
    # Out-of-Sample: Nov 12 - Nov 13
    dev_dates = [pd.to_datetime("2026-11-05").date(), pd.to_datetime("2026-11-06").date(), pd.to_datetime("2026-11-08").date()]
    val_dates = [pd.to_datetime("2026-11-09").date(), pd.to_datetime("2026-11-11").date()]
    oos_dates = [pd.to_datetime("2026-11-12").date(), pd.to_datetime("2026-11-13").date()]

    df_dev = df_all[df_all["date"].dt.date.isin(dev_dates)].reset_index(drop=True)
    df_val = df_all[df_all["date"].dt.date.isin(val_dates)].reset_index(drop=True)
    df_oos = df_all[df_all["date"].dt.date.isin(oos_dates)].reset_index(drop=True)

    print("=" * 100)
    print("MASTER COMPARATIVE BACKTEST: OPPORTUNITY-BASED NIFTY OPTIONS SCALPING ALGO")
    print("Underlying: NIFTY | Target: +3.0 Pts | Break-Even Activation: +2.0 Pts | Intraday (9:20 - 15:00)")
    print(f"Total Dataset: {len(df_all)} bars | Dev: {len(df_dev)} | Val: {len(df_val)} | OOS: {len(df_oos)}")
    print("=" * 100)

    # 1. Compare All 8 Setups / Modes on Full Active Period (ATM)
    setups_to_test = [
        ("Support / Resistance", "SETUP_SUPPORT_RESISTANCE", "STANDALONE"),
        ("Day High / Day Low", "SETUP_DAY_HIGH_LOW", "STANDALONE"),
        ("Break of Structure (BOS)", "SETUP_BOS", "STANDALONE"),
        ("Fair Value Gap (FVG)", "SETUP_FVG", "STANDALONE"),
        ("Candle Pattern Engine", "SETUP_CANDLE_PATTERN", "STANDALONE"),
        ("OI-Assisted Setup", "SETUP_OI_ASSISTED", "STANDALONE"),
        ("OPPORTUNITY MODE (Primary)", None, "OPPORTUNITY"),
        ("HIGH-CONVICTION MODE", None, "HIGH_CONVICTION"),
    ]

    results_table = []
    trade_logs_all = []

    for label, setup_id, mode in setups_to_test:
        trades, m = runner.run_simulation(
            df=df_all,
            mode=mode,
            specific_setup=setup_id,
            strike_selection="ATM",
            split_name="Full Dataset"
        )
        trade_logs_all.extend(trades)
        results_table.append({
            "Mode / Setup": label,
            "Trades": m.total_trades,
            "Trades/Day": m.trades_per_day,
            "Wins": m.target_exits,
            "BE Exits": m.break_even_exits,
            "SL Exits": m.initial_sl_exits,
            "Win Rate": f"{m.win_rate:.1f}%",
            "Gross P&L": f"₹{m.gross_pnl:+,.0f}",
            "Charges": f"₹{m.total_charges:,.0f}",
            "Net P&L": f"₹{m.net_pnl:+,.0f}",
            "Profit Factor": f"{m.profit_factor:.2f}",
            "Max DD": f"₹{m.max_drawdown_inr:,.0f}",
            "Avg Hold (m)": m.avg_holding_time_minutes,
            "MAE (pts)": m.avg_mae_points,
            "MFE (pts)": m.avg_mfe_points,
            "Missed Opps": m.missed_opportunities_due_to_open_position
        })

    df_summary = pd.DataFrame(results_table)
    print("\n" + "=" * 100)
    print("TABLE 1: COMPARATIVE PERFORMANCE OF ALL 8 SETUPS / MODES (ATM OPTIONS)")
    print("=" * 100)
    print(df_summary.to_string(index=False))

    # 2. Compare ATM vs One-Step ITM (ITM_1) for Opportunity Mode
    print("\n" + "=" * 100)
    print("TABLE 2: ATM VS ONE-STEP ITM (ITM_1) EXECUTION COMPARISON (OPPORTUNITY MODE)")
    print("=" * 100)
    atm_trades, atm_m = runner.run_simulation(df_all, mode="OPPORTUNITY", strike_selection="ATM", split_name="Full")
    itm_trades, itm_m = runner.run_simulation(df_all, mode="OPPORTUNITY", strike_selection="ITM_1", split_name="Full")

    df_atm_itm = pd.DataFrame([
        {
            "Strike": "ATM (Delta ~0.50)",
            "Trades": atm_m.total_trades,
            "Win Rate": f"{atm_m.win_rate:.1f}%",
            "Target (+3)": atm_m.target_exits,
            "BE (+2 lock)": atm_m.break_even_exits,
            "SL Exits": atm_m.initial_sl_exits,
            "Gross P&L": f"₹{atm_m.gross_pnl:+,.2f}",
            "Charges": f"₹{atm_m.total_charges:,.2f}",
            "Net P&L": f"₹{atm_m.net_pnl:+,.2f}",
            "Profit Factor": f"{atm_m.profit_factor:.2f}",
            "Max DD": f"₹{atm_m.max_drawdown_inr:,.2f}"
        },
        {
            "Strike": "ITM_1 (Delta ~0.60)",
            "Trades": itm_m.total_trades,
            "Win Rate": f"{itm_m.win_rate:.1f}%",
            "Target (+3)": itm_m.target_exits,
            "BE (+2 lock)": itm_m.break_even_exits,
            "SL Exits": itm_m.initial_sl_exits,
            "Gross P&L": f"₹{itm_m.gross_pnl:+,.2f}",
            "Charges": f"₹{itm_m.total_charges:,.2f}",
            "Net P&L": f"₹{itm_m.net_pnl:+,.2f}",
            "Profit Factor": f"{itm_m.profit_factor:.2f}",
            "Max DD": f"₹{itm_m.max_drawdown_inr:,.2f}"
        }
    ])
    print(df_atm_itm.to_string(index=False))

    # 3. Development vs Validation vs Out-of-Sample (OOS) Splits for Opportunity Mode
    print("\n" + "=" * 100)
    print("TABLE 3: WALK-FORWARD DATA SPLITS (DEVELOPMENT VS VALIDATION VS OUT-OF-SAMPLE)")
    print("=" * 100)
    _, dev_m = runner.run_simulation(df_dev, mode="OPPORTUNITY", strike_selection="ATM", split_name="Dev (Nov 05-08)")
    _, val_m = runner.run_simulation(df_val, mode="OPPORTUNITY", strike_selection="ATM", split_name="Val (Nov 09-11)")
    _, oos_m = runner.run_simulation(df_oos, mode="OPPORTUNITY", strike_selection="ATM", split_name="OOS (Nov 12-13)")

    df_splits = pd.DataFrame([
        {
            "Data Split": "Development (Nov 05 - Nov 08)",
            "Days": len(dev_dates),
            "Trades": dev_m.total_trades,
            "Trades/Day": dev_m.trades_per_day,
            "Win Rate": f"{dev_m.win_rate:.1f}%",
            "Gross P&L": f"₹{dev_m.gross_pnl:+,.2f}",
            "Net P&L": f"₹{dev_m.net_pnl:+,.2f}",
            "Profit Factor": f"{dev_m.profit_factor:.2f}"
        },
        {
            "Data Split": "Validation (Nov 09 - Nov 11)",
            "Days": len(val_dates),
            "Trades": val_m.total_trades,
            "Trades/Day": val_m.trades_per_day,
            "Win Rate": f"{val_m.win_rate:.1f}%",
            "Gross P&L": f"₹{val_m.gross_pnl:+,.2f}",
            "Net P&L": f"₹{val_m.net_pnl:+,.2f}",
            "Profit Factor": f"{val_m.profit_factor:.2f}"
        },
        {
            "Data Split": "Out-of-Sample (Nov 12 - Nov 13)",
            "Days": len(oos_dates),
            "Trades": oos_m.total_trades,
            "Trades/Day": oos_m.trades_per_day,
            "Win Rate": f"{oos_m.win_rate:.1f}%",
            "Gross P&L": f"₹{oos_m.gross_pnl:+,.2f}",
            "Net P&L": f"₹{oos_m.net_pnl:+,.2f}",
            "Profit Factor": f"{oos_m.profit_factor:.2f}"
        }
    ])
    print(df_splits.to_string(index=False))

    # 4. Opportunity Mode Detailed Trade Log
    print("\n" + "=" * 100)
    print("DETAILED TRADE LOG (OPPORTUNITY MODE - FULL PERIOD):")
    print("=" * 100)
    df_trades_opp = pd.DataFrame([t.__dict__ for t in atm_trades])
    if not df_trades_opp.empty:
        cols = ["trade_id", "date", "entry_time", "exit_time", "direction", "setup_name", "points_pnl", "gross_pnl", "charges", "net_pnl", "exit_reason", "mae_points", "mfe_points"]
        print(df_trades_opp[cols].to_string(index=False))
        df_trades_opp.to_csv("opportunity_mode_trades.csv", index=False)
        print("\nSaved trade log to 'opportunity_mode_trades.csv'")

    # Save summary json
    summary_out = {
        "comparison_table": results_table,
        "atm_vs_itm": df_atm_itm.to_dict("records"),
        "splits": df_splits.to_dict("records")
    }
    with open("opportunity_comparison_results.json", "w") as f:
        json.dump(summary_out, f, indent=2)
    print("Saved comparison summary to 'opportunity_comparison_results.json'")

if __name__ == "__main__":
    run_all_comparisons()
