import os
import pytest
from nifty_algo.trade_learning_engine import TradeLearningEngine, TradeJournalEntry

def test_trade_learning_engine_record_and_report(tmp_path):
    journal_path = str(tmp_path / "test_journal.jsonl")
    history_path = str(tmp_path / "config_history")
    engine = TradeLearningEngine(journal_file=journal_path, history_dir=history_path)

    # 1. Record a winning trade
    t1 = TradeJournalEntry(
        trade_id="TRD_001",
        entry_time="2026-11-16 09:30:00",
        exit_time="2026-11-16 09:35:00",
        direction="CE",
        strike=25200.0,
        tradingsymbol="NIFTY26NOV25200CE",
        entry_premium=100.0,
        exit_premium=103.0,
        quantity=65,
        market_regime="TRENDING_BULLISH",
        active_strategy="ENGINE_1_MOMENTUM",
        signal_confidence=88.0,
        adx=25.0,
        atr=12.0,
        vwap_position="ABOVE",
        ema_alignment="BULLISH",
        volume_ratio=1.5,
        fvg_status="FRESH",
        oi_status="ALIGNED",
        heavyweight_alignment="BULLISH",
        entry_spread=0.3,
        slippage_points=0.1,
        exit_reason="Target +3.0 Points Hit",
        gross_pnl=195.0,
        net_pnl=135.0,
        total_charges=60.0
    )
    engine.record_trade(t1)

    # 2. Record a losing trade
    t2 = TradeJournalEntry(
        trade_id="TRD_002",
        entry_time="2026-11-16 11:30:00",
        exit_time="2026-11-16 11:40:00",
        direction="PE",
        strike=25200.0,
        tradingsymbol="NIFTY26NOV25200PE",
        entry_premium=100.0,
        exit_premium=96.0,
        quantity=65,
        market_regime="SIDEWAYS",
        active_strategy="ENGINE_4_BREAKOUT",
        signal_confidence=82.0,
        adx=15.0,
        atr=8.0,
        vwap_position="AT_VWAP",
        ema_alignment="COMPRESSED",
        volume_ratio=1.1,
        fvg_status="NONE",
        oi_status="NEUTRAL",
        heavyweight_alignment="DIVERGENT",
        entry_spread=0.5,
        slippage_points=0.2,
        exit_reason="Stop Loss Hit",
        gross_pnl=-260.0,
        net_pnl=-320.0,
        total_charges=60.0
    )
    engine.record_trade(t2)

    # 3. Generate Report
    report = engine.generate_daily_report("2026-11-16")
    assert report.total_trades == 2
    assert report.winning_trades == 1
    assert report.losing_trades == 1
    assert report.win_rate_pct == 50.0
    assert report.net_pnl == (135.0 - 320.0)  # -185.0
    assert "ENGINE_1_MOMENTUM" in report.strategy_performance
    assert "SIDEWAYS" in report.regime_performance
    # Check that warning triggered for negative PnL in SIDEWAYS regime
    assert any("SIDEWAYS" in w for w in report.regime_strategy_warnings)

    # 4. Propose tuning without auto-promoting
    proposal = engine.propose_parameter_tuning(
        rationale="Disallow breakouts in sideways regime",
        parameter_path="strategies.breakout.allow_sideways",
        current_value=True,
        proposed_value=False,
        backtest_improvement_pct=14.5,
        out_of_sample_validated=True
    )
    assert proposal.status == "PENDING_OPERATOR_APPROVAL"
    assert proposal.historical_backtest_improvement_pct == 14.5
