import pytest
from nifty_algo.indicators.heavyweight_alignment_engine import (
    HeavyweightAlignmentEngine,
    DEFAULT_HDFCBANK_TOKEN,
    DEFAULT_RELIANCE_TOKEN,
    DEFAULT_ICICIBANK_TOKEN
)
from nifty_algo.strategies.signal_arbitration_engine import SignalArbitrationEngine
from nifty_algo.strategies.base_setup import OpportunitySignal

def test_heavyweight_engine_full_bullish_alignment():
    engine = HeavyweightAlignmentEngine()

    # HDFCBANK: Open=1700, VWAP=1705, LTP=1715 (Bullish)
    engine.update_snapshot("HDFCBANK", ltp=1715.0, vwap=1705.0, open_price=1700.0)
    # RELIANCE: Open=1250, VWAP=1252, LTP=1260 (Bullish)
    engine.update_snapshot("RELIANCE", ltp=1260.0, vwap=1252.0, open_price=1250.0)
    # ICICIBANK: Open=1280, VWAP=1282, LTP=1290 (Bullish)
    engine.update_snapshot("ICICIBANK", ltp=1290.0, vwap=1282.0, open_price=1280.0)

    res = engine.evaluate()
    assert res.is_bullish_aligned is True
    assert res.is_bearish_aligned is False
    assert res.is_divergence_trap is False
    assert "FULL_BULLISH_ALIGNMENT" in res.summary

    # Test Arbitration Boost for CE
    arbitrator = SignalArbitrationEngine(min_confidence_threshold=80.0)
    sig_ce = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM",
        strategy_name="Momentum Detection",
        direction="CE",
        confidence=75.0,  # Below 80 alone
        timestamp="09:30",
        reference_price=25000.0,
        stop_loss_pts=5.0,
        target_pts=3.0,
        entry_condition="Bullish Displacement",
        triggered=True
    )

    decision = arbitrator.arbitrate(
        signals=[sig_ce],
        indicators={},
        has_open_position=False,
        heavyweight_eval=res
    )

    # 75.0 + 10.0 (Heavyweight Boost) = 85.0 -> Executes!
    assert decision.should_execute is True
    assert decision.combined_confidence == 85.0
    assert any("BIG_3_BULLISH_ALIGNMENT" in c for c in decision.contributing_strategies)

def test_heavyweight_engine_full_bearish_alignment():
    engine = HeavyweightAlignmentEngine()

    # All 3 below VWAP and Open
    engine.update_snapshot("HDFCBANK", ltp=1690.0, vwap=1705.0, open_price=1700.0)
    engine.update_snapshot("RELIANCE", ltp=1240.0, vwap=1252.0, open_price=1250.0)
    engine.update_snapshot("ICICIBANK", ltp=1270.0, vwap=1282.0, open_price=1280.0)

    res = engine.evaluate()
    assert res.is_bearish_aligned is True
    assert res.is_bullish_aligned is False
    assert "FULL_BEARISH_ALIGNMENT" in res.summary

    # PE receives +10 boost, CE receives -15 penalty
    arbitrator = SignalArbitrationEngine(min_confidence_threshold=80.0)
    sig_pe = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM",
        strategy_name="Momentum Detection",
        direction="PE",
        confidence=78.0,
        timestamp="09:30",
        reference_price=25000.0,
        stop_loss_pts=5.0,
        target_pts=3.0,
        entry_condition="Bearish Breakdown",
        triggered=True
    )

    decision = arbitrator.arbitrate(
        signals=[sig_pe],
        indicators={},
        has_open_position=False,
        heavyweight_eval=res
    )
    # 78.0 + 10.0 = 88.0 -> Executes!
    assert decision.should_execute is True
    assert decision.combined_confidence == 88.0

    # Opposing CE signal is penalized by -15 pts
    sig_ce = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM",
        strategy_name="Momentum Detection",
        direction="CE",
        confidence=82.0,
        timestamp="09:30",
        reference_price=25000.0,
        stop_loss_pts=5.0,
        target_pts=3.0,
        entry_condition="Fake CE Bounce",
        triggered=True
    )
    decision_ce = arbitrator.arbitrate(
        signals=[sig_ce],
        indicators={},
        has_open_position=False,
        heavyweight_eval=res
    )
    # 82.0 - 15.0 = 67.0 (< 80) -> Blocked!
    assert decision_ce.should_execute is False
    assert "OPPOSING_BIG_3_BEARISH_ALIGNMENT" in decision_ce.rejection_reasons

def test_heavyweight_engine_divergence_chop_trap():
    engine = HeavyweightAlignmentEngine()

    # The Classic Midday Tug-of-War: Reliance is Bullish, but HDFC is Bearish!
    engine.update_snapshot("RELIANCE", ltp=1260.0, vwap=1252.0, open_price=1250.0)  # Bullish
    engine.update_snapshot("HDFCBANK", ltp=1690.0, vwap=1705.0, open_price=1700.0)  # Bearish
    engine.update_snapshot("ICICIBANK", ltp=1280.0, vwap=1280.0, open_price=1280.0)  # Neutral

    res = engine.evaluate()
    assert res.is_divergence_trap is True
    assert "DIVERGENCE_CHOP_TRAP" in res.summary

    # Breakout signal alone has 82.0 (normally passes >= 80)
    arbitrator = SignalArbitrationEngine(min_confidence_threshold=80.0)
    sig_breakout = OpportunitySignal(
        strategy_id="ENGINE_4_BREAKOUT",
        strategy_name="Breakout Detection",
        direction="CE",
        confidence=82.0,
        timestamp="09:30",
        reference_price=25000.0,
        stop_loss_pts=5.0,
        target_pts=3.0,
        entry_condition="Day High Breakout",
        triggered=True
    )

    decision = arbitrator.arbitrate(
        signals=[sig_breakout],
        indicators={},
        has_open_position=False,
        heavyweight_eval=res
    )

    # 82.0 - 10.0 (Divergence Chop Penalty) = 72.0 (< 80) -> BLOCKED from entering sideways chop!
    assert decision.should_execute is False
    assert decision.combined_confidence == 72.0
    assert "HEAVYWEIGHT_DIVERGENCE_CHOP_WARNING" in decision.rejection_reasons

def test_heavyweight_engine_websocket_tick_handling():
    engine = HeavyweightAlignmentEngine()
    
    # Simulate Kite WebSocket tick format
    tick_hdfc = {
        "instrument_token": DEFAULT_HDFCBANK_TOKEN,
        "last_price": 1720.0,
        "average_price": 1710.0,
        "ohlc": {"open": 1705.0, "high": 1722.0, "low": 1704.0, "close": 1705.0}
    }
    engine.on_tick(tick_hdfc)

    assert engine.stocks["HDFCBANK"].ltp == 1720.0
    assert engine.stocks["HDFCBANK"].vwap == 1710.0
    assert engine.stocks["HDFCBANK"].bias == "BULLISH"

def test_heavyweight_fast_mover_target_expansion_to_15():
    from datetime import datetime
    from nifty_algo.execution.trade_execution_engine import TradeExecutionEngine

    engine = HeavyweightAlignmentEngine(fast_move_target_pts=15.0)

    # All 3 stocks surging with rapid velocity > +0.5%
    # HDFCBANK: +1.0%
    engine.update_snapshot("HDFCBANK", ltp=1717.0, vwap=1705.0, open_price=1700.0, day_high=1717.0)
    # RELIANCE: +1.2%
    engine.update_snapshot("RELIANCE", ltp=1265.0, vwap=1252.0, open_price=1250.0, day_high=1265.0)
    # ICICIBANK: +0.8%
    engine.update_snapshot("ICICIBANK", ltp=1290.0, vwap=1282.0, open_price=1280.0, day_high=1290.0)

    res = engine.evaluate()
    assert res.is_bullish_aligned is True
    assert res.is_fast_mover is True
    assert res.expanded_target_pts == 15.0
    assert res.fast_move_direction == "CE"
    assert "SUPER_TREND_FAST_MOVE" in res.summary

    # Test that Signal Arbitration Engine expands target_pts to 15.0
    arbitrator = SignalArbitrationEngine(min_confidence_threshold=80.0)
    sig_ce = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM",
        strategy_name="Momentum Detection",
        direction="CE",
        confidence=82.0,
        timestamp="09:30",
        reference_price=25000.0,
        stop_loss_pts=5.0,
        target_pts=3.0,
        entry_condition="Super Trend Impulse",
        triggered=True
    )

    decision = arbitrator.arbitrate(
        signals=[sig_ce],
        indicators={},
        has_open_position=False,
        heavyweight_eval=res
    )

    assert decision.should_execute is True
    assert decision.target_pts == 15.0  # EXPANDED TO +15.0 POINTS!
    assert any("SUPER_TREND_TARGET_EXPANSION" in c for c in decision.contributing_strategies)

    # Test that Trade Execution Engine manages the +15.0 target correctly
    exec_engine = TradeExecutionEngine(lot_size=65, target_pts=3.0, break_even_activation_pts=None)
    active_trade = {
        "trade_id": "TRD_FAST_01",
        "entry_time": "09:30",
        "entry_bar_idx": 0,
        "direction": "BULLISH",
        "strike": 25000.0,
        "delta": 0.50,
        "entry_spot": 25000.0,
        "entry_premium": 130.0,
        "current_stop": 125.0,  # 5.0 pt SL
        "target_pts": decision.target_pts,  # 15.0 pts
        "be_activated": False,
        "mfe": 0.0,
        "mae": 0.0,
        "setup_name": "Momentum Detection",
        "confidence": decision.combined_confidence,
        "contributing_factors": decision.contributing_strategies
    }

    # Bar 1: Spot rises +10 pts -> Option reaches 135.0 (+5.0 pts)
    # Trade must STAY OPEN (does not exit at 3.0 pts because target is 15.0!)
    bar1 = {"date": datetime(2026, 11, 9, 9, 31), "open": 25000.0, "high": 25010.0, "low": 25000.0, "close": 25009.0}
    res1 = exec_engine.process_exit_conditions(active_trade, bar1, bar_idx=1, entry_bar_idx=0)
    assert res1 is None

    # Bar 2: Spot surges +30 pts -> Option reaches 145.0 (+15.0 pts target!)
    bar2 = {"date": datetime(2026, 11, 9, 9, 32), "open": 25009.0, "high": 25030.0, "low": 25008.0, "close": 25028.0}
    res2 = exec_engine.process_exit_conditions(active_trade, bar2, bar_idx=2, entry_bar_idx=0)
    assert res2 is not None
    assert res2.exit_reason == "TARGET"
    assert res2.points_pnl == 14.95  # +15.0 - 0.05 slippage
    assert res2.gross_pnl == 971.75  # ~₹975 gross profit per lot!

