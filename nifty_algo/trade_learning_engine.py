import os
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger("nifty_algo.learning")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class TradeJournalEntry:
    trade_id: str
    entry_time: str
    exit_time: str
    direction: str  # 'CE' or 'PE'
    strike: float
    tradingsymbol: str
    entry_premium: float
    exit_premium: float
    quantity: int
    market_regime: str
    active_strategy: str
    signal_confidence: float
    adx: float
    atr: float
    vwap_position: str
    ema_alignment: str
    volume_ratio: float
    fvg_status: str
    oi_status: str
    heavyweight_alignment: str
    entry_spread: float
    slippage_points: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    total_charges: float
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class DailyPerformanceReport:
    report_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: float
    gross_pnl: float
    total_charges: float
    net_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown_inr: float
    stop_loss_frequency: float
    false_breakout_frequency: float
    avg_slippage_pts: float
    strategy_performance: Dict[str, Dict[str, Any]]
    regime_performance: Dict[str, Dict[str, Any]]
    hourly_performance: Dict[str, Dict[str, Any]]
    regime_strategy_warnings: List[str] = field(default_factory=list)


@dataclass
class ParameterImprovementProposal:
    proposal_id: str
    created_at: str
    rationale: str
    parameter_path: str
    current_value: Any
    proposed_value: Any
    historical_backtest_improvement_pct: float
    out_of_sample_validated: bool
    status: str = "PENDING_OPERATOR_APPROVAL"  # Never auto-promoted to live!


class TradeLearningEngine:
    """
    Trade Learning & Adaptive Analytics Engine (Phase 8)
    - Records comprehensive multidimensional telemetry on every executed trade.
    - Post-market daily quantitative analyzer (Win Rate, Profit Factor, Expectancy, Regime-Strategy attribution).
    - Detects regime-specific underperformance (e.g. Breakout failing in Sideways regimes).
    - Proposes validated configuration adjustments without ever auto-promoting to live.
    - Full configuration versioning and rollback capability.
    """

    def __init__(self, journal_file: str = "trade_learning_journal.jsonl", history_dir: str = "config_history"):
        self.journal_file = journal_file
        self.history_dir = history_dir
        os.makedirs(self.history_dir, exist_ok=True)

    def record_trade(self, entry: TradeJournalEntry):
        """Appends a completed trade entry to the persistent JSONL telemetry log."""
        try:
            with open(self.journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
            logger.info("[TRADE JOURNAL RECORDED] Trade %s | Net P&L: ₹%.2f | Strategy: %s | Regime: %s",
                        entry.trade_id, entry.net_pnl, entry.active_strategy, entry.market_regime)
        except Exception as e:
            logger.error("Failed to write trade telemetry: %s", e)

    def load_journal(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.journal_file):
            return []
        trades = []
        try:
            with open(self.journal_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))
        except Exception as e:
            logger.error("Error loading trade journal: %s", e)
        return trades

    def generate_daily_report(self, date_str: Optional[str] = None) -> DailyPerformanceReport:
        all_trades = self.load_journal()
        target_date = date_str or datetime.now(IST).strftime("%Y-%m-%d")

        # Filter trades for target day
        day_trades = [t for t in all_trades if str(t.get("entry_time", "")).startswith(target_date)]

        if not day_trades:
            return DailyPerformanceReport(
                report_date=target_date,
                total_trades=0, winning_trades=0, losing_trades=0, breakeven_trades=0,
                win_rate_pct=0.0, gross_pnl=0.0, total_charges=0.0, net_pnl=0.0,
                avg_win=0.0, avg_loss=0.0, profit_factor=0.0, expectancy=0.0,
                max_drawdown_inr=0.0, stop_loss_frequency=0.0, false_breakout_frequency=0.0,
                avg_slippage_pts=0.0, strategy_performance={}, regime_performance={},
                hourly_performance={}, regime_strategy_warnings=[]
            )

        df = pd.DataFrame(day_trades)
        total = len(df)
        wins = df[df["net_pnl"] > 0]
        losses = df[df["net_pnl"] < 0]
        be = df[df["net_pnl"] == 0]

        win_count = len(wins)
        loss_count = len(losses)
        be_count = len(be)
        win_rate = round((win_count / total) * 100.0, 1) if total > 0 else 0.0

        gross = round(float(df["gross_pnl"].sum()), 2)
        charges = round(float(df["total_charges"].sum()), 2)
        net = round(float(df["net_pnl"].sum()), 2)

        avg_w = round(float(wins["net_pnl"].mean()), 2) if win_count > 0 else 0.0
        avg_l = round(abs(float(losses["net_pnl"].mean())), 2) if loss_count > 0 else 0.0

        gross_win = float(wins["net_pnl"].sum()) if win_count > 0 else 0.0
        gross_loss = abs(float(losses["net_pnl"].sum())) if loss_count > 0 else 0.0
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

        # Mathematical Expectancy
        win_prob = win_count / total if total > 0 else 0.0
        loss_prob = loss_count / total if total > 0 else 0.0
        expectancy = round((win_prob * avg_w) - (loss_prob * avg_l), 2)

        # Max Drawdown
        cum_pnl = df["net_pnl"].cumsum()
        peak = cum_pnl.cummax()
        dd = peak - cum_pnl
        max_dd = round(float(dd.max()), 2) if len(dd) > 0 else 0.0

        sl_hits = df[df["exit_reason"].str.contains("Stop Loss|SL", case=False, na=False)]
        sl_freq = round((len(sl_hits) / total) * 100.0, 1)

        fakeouts = df[df["exit_reason"].str.contains("Trap|Sweep|Rejection", case=False, na=False)]
        fakeout_freq = round((len(fakeouts) / total) * 100.0, 1)

        avg_slip = round(float(df["slippage_points"].mean()), 2) if "slippage_points" in df.columns else 0.0

        # Strategy Performance Attribution
        strat_perf = {}
        for strat, grp in df.groupby("active_strategy"):
            strat_wins = len(grp[grp["net_pnl"] > 0])
            strat_total = len(grp)
            strat_perf[strat] = {
                "trades": strat_total,
                "win_rate": round((strat_wins / strat_total) * 100.0, 1),
                "net_pnl": round(float(grp["net_pnl"].sum()), 2)
            }

        # Regime Performance Attribution
        regime_perf = {}
        regime_warnings = []
        for regime, grp in df.groupby("market_regime"):
            r_wins = len(grp[grp["net_pnl"] > 0])
            r_total = len(grp)
            r_net = round(float(grp["net_pnl"].sum()), 2)
            regime_perf[regime] = {
                "trades": r_total,
                "win_rate": round((r_wins / r_total) * 100.0, 1),
                "net_pnl": r_net
            }
            # Detect underperforming pairs
            if regime == "SIDEWAYS" and r_net < 0:
                regime_warnings.append(f"WARNING: Negative P&L (₹{r_net:.2f}) observed in SIDEWAYS regime. Tighten chop filters.")

        # Hourly Performance
        hourly_perf = {}
        if "entry_time" in df.columns:
            for h, grp in df.groupby(df["entry_time"].str.slice(11, 13)):
                hourly_perf[f"{h}:00"] = {
                    "trades": len(grp),
                    "net_pnl": round(float(grp["net_pnl"].sum()), 2)
                }

        report = DailyPerformanceReport(
            report_date=target_date,
            total_trades=total,
            winning_trades=win_count,
            losing_trades=loss_count,
            breakeven_trades=be_count,
            win_rate_pct=win_rate,
            gross_pnl=gross,
            total_charges=charges,
            net_pnl=net,
            avg_win=avg_w,
            avg_loss=avg_l,
            profit_factor=pf,
            expectancy=expectancy,
            max_drawdown_inr=max_dd,
            stop_loss_frequency=sl_freq,
            false_breakout_frequency=fakeout_freq,
            avg_slippage_pts=avg_slip,
            strategy_performance=strat_perf,
            regime_performance=regime_perf,
            hourly_performance=hourly_perf,
            regime_strategy_warnings=regime_warnings
        )
        return report

    def create_config_backup(self, current_config_dict: Dict[str, Any], tag: str = "snapshot") -> str:
        """Saves a versioned configuration file for rollback safety."""
        ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.history_dir, f"config_{tag}_{ts}.json")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(current_config_dict, f, indent=2)
            logger.info("[CONFIG BACKUP CREATED] Saved to %s", filename)
            return filename
        except Exception as e:
            logger.error("Failed to create config backup: %s", e)
            return ""

    def propose_parameter_tuning(
        self,
        rationale: str,
        parameter_path: str,
        current_value: Any,
        proposed_value: Any,
        backtest_improvement_pct: float,
        out_of_sample_validated: bool
    ) -> ParameterImprovementProposal:
        """
        Creates an audit proposal for human operator approval.
        Under no circumstances does this auto-promote to live trading.
        """
        import uuid
        proposal = ParameterImprovementProposal(
            proposal_id=f"PROP_{uuid.uuid4().hex[:8].upper()}",
            created_at=datetime.now(IST).isoformat(),
            rationale=rationale,
            parameter_path=parameter_path,
            current_value=current_value,
            proposed_value=proposed_value,
            historical_backtest_improvement_pct=backtest_improvement_pct,
            out_of_sample_validated=out_of_sample_validated,
            status="PENDING_OPERATOR_APPROVAL"
        )
        logger.info("[ADAPTIVE TUNING PROPOSAL CREATED] %s: %s -> %s (Backtest +%.1f%%, Validated: %s)",
                    proposal.proposal_id, parameter_path, proposed_value, backtest_improvement_pct, out_of_sample_validated)
        return proposal
