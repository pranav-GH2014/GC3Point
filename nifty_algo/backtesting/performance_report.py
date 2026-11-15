from dataclasses import dataclass, field
from typing import List, Dict, Any
import pandas as pd
import numpy as np
from ..execution.trade_execution_engine import TradeRecord

@dataclass
class PerformanceMetrics:
    mode_name: str
    strike_type: str
    data_split: str
    total_trades: int
    trades_per_day: float
    ce_trades: int
    pe_trades: int
    target_exits: int
    break_even_exits: int
    initial_sl_exits: int
    win_rate: float
    gross_pnl: float
    total_charges: float
    net_pnl: float
    profit_factor: float
    max_drawdown_inr: float
    max_consecutive_losses: int
    avg_holding_time_minutes: float
    avg_mae_points: float
    avg_mfe_points: float
    missed_opportunities_due_to_open_position: int
    days_with_1_target: int
    days_with_2_targets: int
    days_with_3_plus_targets: int
    signal_wise_performance: Dict[str, Dict[str, Any]]
    hour_wise_performance: Dict[str, Dict[str, Any]]

class PerformanceReporter:
    """
    Computes comprehensive Section 11 analytics and comparison reports.
    """

    @staticmethod
    def calculate_metrics(
        trades: List[TradeRecord],
        mode_name: str = "OPPORTUNITY",
        strike_type: str = "ATM",
        data_split: str = "Full Dataset",
        missed_opportunities: int = 0
    ) -> PerformanceMetrics:
        if not trades:
            return PerformanceMetrics(
                mode_name=mode_name, strike_type=strike_type, data_split=data_split,
                total_trades=0, trades_per_day=0.0, ce_trades=0, pe_trades=0,
                target_exits=0, break_even_exits=0, initial_sl_exits=0, win_rate=0.0,
                gross_pnl=0.0, total_charges=0.0, net_pnl=0.0, profit_factor=0.0,
                max_drawdown_inr=0.0, max_consecutive_losses=0, avg_holding_time_minutes=0.0,
                avg_mae_points=0.0, avg_mfe_points=0.0,
                missed_opportunities_due_to_open_position=missed_opportunities,
                days_with_1_target=0, days_with_2_targets=0, days_with_3_plus_targets=0,
                signal_wise_performance={}, hour_wise_performance={}
            )

        df = pd.DataFrame([t.__dict__ for t in trades])

        total = len(df)
        ce_count = (df["direction"] == "BUY CE").sum()
        pe_count = (df["direction"] == "BUY PE").sum()

        target_exits = (df["exit_reason"] == "TARGET").sum()
        be_exits = (df["exit_reason"] == "BREAK_EVEN").sum()
        sl_exits = (df["exit_reason"] == "INITIAL_SL").sum()

        win_rate = round((target_exits / total) * 100, 2)
        gross_pnl = round(df["gross_pnl"].sum(), 2)
        charges = round(df["charges"].sum(), 2)
        net_pnl = round(df["net_pnl"].sum(), 2)

        # Profit Factor
        gains = df[df["gross_pnl"] > 0]["gross_pnl"].sum()
        losses = abs(df[df["gross_pnl"] < 0]["gross_pnl"].sum())
        profit_factor = round(gains / losses, 2) if losses > 0 else 99.0

        # Maximum Drawdown
        cum_net = df["net_pnl"].cumsum()
        running_max = cum_net.cummax()
        drawdowns = running_max - cum_net
        max_dd = round(float(drawdowns.max()) if not drawdowns.empty else 0.0, 2)

        # Max consecutive losses
        is_loss = (df["exit_reason"] == "INITIAL_SL").astype(int)
        loss_groups = (is_loss != is_loss.shift()).cumsum()
        consec_losses = is_loss.groupby(loss_groups).sum()
        max_consec_loss = int(consec_losses.max()) if not consec_losses.empty else 0

        # Unique days
        unique_days = df["date"].nunique()
        trades_per_day = round(total / max(1, unique_days), 1)

        # Days achieving targets
        targets_by_day = df[df["exit_reason"] == "TARGET"].groupby("date").size()
        days_1 = int((targets_by_day == 1).sum())
        days_2 = int((targets_by_day == 2).sum())
        days_3_plus = int((targets_by_day >= 3).sum())

        avg_holding = round(float(df["holding_time_minutes"].mean()), 1)
        avg_mae = round(float(df["mae_points"].mean()), 2)
        avg_mfe = round(float(df["mfe_points"].mean()), 2)

        # Signal-wise breakdown
        signal_perf: Dict[str, Dict[str, Any]] = {}
        for setup, s_df in df.groupby("setup_name"):
            s_tot = len(s_df)
            s_wins = (s_df["exit_reason"] == "TARGET").sum()
            signal_perf[str(setup)] = {
                "trades": s_tot,
                "wins": int(s_wins),
                "win_rate": round(s_wins / s_tot * 100, 1),
                "gross_pnl": round(s_df["gross_pnl"].sum(), 2),
                "net_pnl": round(s_df["net_pnl"].sum(), 2),
            }

        # Hour-wise performance
        df["hour"] = df["entry_time"].str[:2]
        hour_perf: Dict[str, Dict[str, Any]] = {}
        for hour, h_df in df.groupby("hour"):
            h_tot = len(h_df)
            h_wins = (h_df["exit_reason"] == "TARGET").sum()
            hour_perf[f"{hour}:00"] = {
                "trades": h_tot,
                "wins": int(h_wins),
                "win_rate": round(h_wins / h_tot * 100, 1),
                "net_pnl": round(h_df["net_pnl"].sum(), 2)
            }

        return PerformanceMetrics(
            mode_name=mode_name,
            strike_type=strike_type,
            data_split=data_split,
            total_trades=total,
            trades_per_day=trades_per_day,
            ce_trades=int(ce_count),
            pe_trades=int(pe_count),
            target_exits=int(target_exits),
            break_even_exits=int(be_exits),
            initial_sl_exits=int(sl_exits),
            win_rate=win_rate,
            gross_pnl=gross_pnl,
            total_charges=charges,
            net_pnl=net_pnl,
            profit_factor=profit_factor,
            max_drawdown_inr=max_dd,
            max_consecutive_losses=max_consec_loss,
            avg_holding_time_minutes=avg_holding,
            avg_mae_points=avg_mae,
            avg_mfe_points=avg_mfe,
            missed_opportunities_due_to_open_position=missed_opportunities,
            days_with_1_target=days_1,
            days_with_2_targets=days_2,
            days_with_3_plus_targets=days_3_plus,
            signal_wise_performance=signal_perf,
            hour_wise_performance=hour_perf
        )
