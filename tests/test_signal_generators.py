import pytest
from nifty_algo.strategies.base_setup import SetupSignal
from nifty_algo.strategies.support_resistance_engine import SupportResistanceEngine
from nifty_algo.strategies.day_high_low_engine import DayHighLowEngine
from nifty_algo.strategies.bos_engine import BOSEngine
from nifty_algo.strategies.fvg_engine import FVGEngine
from nifty_algo.strategies.candle_pattern_engine import CandlePatternEngine
from nifty_algo.strategies.oi_analysis_engine import OIAnalysisEngine
from nifty_algo.confidence.signal_scoring_engine import SignalScoringEngine
from nifty_algo.execution.trade_execution_engine import TradeExecutionEngine

def test_support_resistance_engine_ce_bounce():
    engine = SupportResistanceEngine(proximity_threshold_pts=8.0)
    structure = {"last_swing_low": 25000.0, "cdl": 25000.0}
    indicators = {"price_above_vwap": True, "ema_bullish": True}
    
    # 3m candle forms lower rejection wick near 25000 support
    c3 = [{"open": 25010.0, "high": 25015.0, "low": 24998.0, "close": 25012.0}]
    c1 = [
        {"open": 25005.0, "high": 25010.0, "low": 25000.0, "close": 25008.0},
        {"open": 25008.0, "high": 25014.0, "low": 25005.0, "close": 25012.0}
    ]

    sig = engine.evaluate(c1, c3, structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "BULLISH"
    assert sig.supporting_factors["category"] == "SUPPORT_RESISTANCE"

def test_day_high_low_sweep_and_reclaim():
    engine = DayHighLowEngine()
    structure = {"cdl": 25000.0, "cdh": 25150.0}
    indicators = {}

    # Candle pierces below CDL (24995) but reclaims and closes at 25006
    c3 = [
        {"open": 25010.0, "high": 25012.0, "low": 25002.0, "close": 25005.0},
        {"open": 25005.0, "high": 25008.0, "low": 24995.0, "close": 25006.0}
    ]
    c1 = [
        {"open": 25005.0, "high": 25008.0, "low": 25000.0, "close": 25002.0},
        {"open": 25002.0, "high": 25008.0, "low": 24995.0, "close": 25006.0}
    ]

    sig = engine.evaluate(c1, c3, structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "BULLISH"
    assert sig.supporting_factors["type"] == "SWEEP_RECLAIM"

def test_bos_engine_bullish_break():
    engine = BOSEngine(min_displacement_ratio=0.50)
    structure = {"last_swing_high": 25100.0, "last_swing_low": 25000.0}
    indicators = {}

    # Candle 1 & 2 below 25100, Candle 3 breaks above 25100 with displacement body (18 pts body / 24 pts range = 75%)
    c3 = [
        {"open": 25080.0, "high": 25095.0, "low": 25075.0, "close": 25090.0},
        {"open": 25085.0, "high": 25098.0, "low": 25080.0, "close": 25092.0},
        {"open": 25090.0, "high": 25114.0, "low": 25088.0, "close": 25110.0}
    ]
    c1 = [
        {"open": 25090.0, "high": 25100.0, "low": 25088.0, "close": 25095.0},
        {"open": 25105.0, "high": 25114.0, "low": 25102.0, "close": 25110.0}
    ]

    sig = engine.evaluate(c1, c3, structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "BULLISH"
    assert sig.supporting_factors["category"] == "BOS"

def test_fvg_engine_bullish_imbalance():
    engine = FVGEngine(min_gap_pts=2.0, timeframe="1m")
    structure = {}
    indicators = {}

    # 3-candle FVG: c3 low (25022) > c1 high (25015), gap = 7 pts. c2 is strong expansion candle.
    c1_list = [
        {"open": 25005.0, "high": 25015.0, "low": 25000.0, "close": 25012.0},
        {"open": 25013.0, "high": 25035.0, "low": 25012.0, "close": 25032.0},
        {"open": 25030.0, "high": 25040.0, "low": 25022.0, "close": 25035.0}
    ]

    sig = engine.evaluate(c1_list, [], structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "BULLISH"
    assert sig.supporting_factors["category"] == "FVG"
    assert sig.supporting_factors["gap_size"] == 7.0

def test_candle_pattern_inside_bar_breakout():
    engine = CandlePatternEngine(min_significant_pts=5.0)
    structure = {}
    indicators = {}

    # Mother bar: 25000 to 25030
    # Inside bar: 25005 to 25025
    # Breakout bar: breaks above 25030 to close at 25035
    c3 = [
        {"open": 25005.0, "high": 25030.0, "low": 25000.0, "close": 25025.0},
        {"open": 25010.0, "high": 25025.0, "low": 25005.0, "close": 25020.0},
        {"open": 25022.0, "high": 25038.0, "low": 25020.0, "close": 25035.0}
    ]
    c1 = [{"open": 25030.0, "high": 25038.0, "low": 25028.0, "close": 25035.0}]

    sig = engine.evaluate(c1, c3, structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "BULLISH"
    assert sig.supporting_factors["pattern"] == "INSIDE_BAR_BREAKOUT"

def test_oi_analysis_engine_never_triggers_alone():
    engine = OIAnalysisEngine()
    structure = {}
    indicators = {"price_above_vwap": False}

    # Strong bullish OI data, but price action is bearish red candle
    c1 = [{"open": 25020.0, "high": 25022.0, "low": 25008.0, "close": 25010.0}]  # Red candle!
    oi_data = {"oi_bias": "BULLISH_PE_WRITING", "pcr": 1.4, "total_pe_oi_change": 500000, "total_ce_oi_change": 100000}

    sig = engine.evaluate(c1, [], structure, indicators, oi_data=oi_data)
    # MUST NOT trigger without price confirmation!
    assert sig.triggered is False

def test_scoring_engine_anti_double_counting():
    scorer = SignalScoringEngine(min_confidence_score=80.0)
    
    # Simulate both BOS and Candle pattern co-occurring
    sig_bos = SetupSignal(
        setup_id="SETUP_BOS", setup_name="BOS", triggered=True, direction="BULLISH",
        confidence=85.0, timeframe="3m", entry_level=25100.0, invalidation_level=25095.0,
        reason="BOS Break", supporting_factors={"category": "BOS"}
    )
    sig_candle = SetupSignal(
        setup_id="SETUP_CANDLE_PATTERN", setup_name="Candle", triggered=True, direction="BULLISH",
        confidence=82.0, timeframe="3m", entry_level=25100.0, invalidation_level=25095.0,
        reason="Marubozu", supporting_factors={"category": "CANDLE_PATTERN"}
    )

    res = scorer.score([sig_bos, sig_candle], {}, {})
    assert res.anti_double_counting_applied is True
    # Candle pattern should receive 50% discount (10 pts instead of 20 pts)
    assert res.breakdown["candle_pattern"] == 10.0
    assert res.breakdown["bos"] == 25.0

def test_trade_execution_break_even_activation():
    from datetime import datetime
    engine = TradeExecutionEngine(lot_size=65, target_pts=3.0, break_even_activation_pts=2.0)
    
    active = {
        "trade_id": "TRD_01",
        "entry_time": "09:30",
        "entry_bar_idx": 0,
        "direction": "BULLISH",
        "strike": 25000.0,
        "delta": 0.50,
        "entry_spot": 25000.0,
        "entry_premium": 135.0,
        "current_stop": 130.0,
        "be_activated": False,
        "mfe": 0.0,
        "mae": 0.0,
        "setup_name": "BOS",
        "confidence": 85.0,
        "contributing_factors": []
    }

    # Bar 1: Spot rises +4.5 pts (low holds at 25000.0) -> option high reaches 137.25 (+2.25 pts > +2.0 BE activation)
    bar1 = {"date": datetime(2026, 11, 9, 9, 31), "open": 25000.0, "high": 25004.5, "low": 25000.0, "close": 25004.0}
    res1 = engine.process_exit_conditions(active, bar1, bar_idx=1, entry_bar_idx=0)
    # Trade remains OPEN, but BE activated and stop moved to entry 135.0!
    assert res1 is None
    assert active["be_activated"] is True
    assert active["current_stop"] == 135.0

    # Bar 2: Spot pulls back to 24999.0 -> option low reaches 134.5 (below 135.0 stop)
    # Stop is hit at 135.0 -> exits with BREAK_EVEN!
    bar2 = {"date": datetime(2026, 11, 9, 9, 32), "open": 25004.0, "high": 25004.0, "low": 24999.0, "close": 24999.5}
    res2 = engine.process_exit_conditions(active, bar2, bar_idx=2, entry_bar_idx=0)
    assert res2 is not None
    assert res2.exit_reason == "BREAK_EVEN"
    assert res2.break_even_activated is True
    assert res2.points_pnl == -0.05  # -slippage only

def test_trade_execution_without_break_even():
    from datetime import datetime
    # Engine configured with break_even_activation_pts=None (BE REMOVED)
    engine = TradeExecutionEngine(lot_size=65, target_pts=3.0, break_even_activation_pts=None, max_premium_loss_cap=5.0)
    
    active = {
        "trade_id": "TRD_02",
        "entry_time": "09:30",
        "entry_bar_idx": 0,
        "direction": "BULLISH",
        "strike": 25000.0,
        "delta": 0.50,
        "entry_spot": 25000.0,
        "entry_premium": 135.0,
        "current_stop": 130.0,  # 5.0 pt SL
        "be_activated": False,
        "mfe": 0.0,
        "mae": 0.0,
        "setup_name": "MOMENTUM",
        "confidence": 85.0,
        "contributing_factors": []
    }

    # Bar 1: Spot rises +4.5 pts -> option high reaches 137.25 (+2.25 pts)
    bar1 = {"date": datetime(2026, 11, 9, 9, 31), "open": 25000.0, "high": 25004.5, "low": 25000.0, "close": 25004.0}
    res1 = engine.process_exit_conditions(active, bar1, bar_idx=1, entry_bar_idx=0)
    assert res1 is None
    # BE must NOT be activated! Current stop remains at initial 130.0!
    assert active["be_activated"] is False
    assert active["current_stop"] == 130.0

    # Bar 2: Spot pulls back to 24999.0 -> option low reaches 134.5 (below 135.0 entry, but above 130.0 SL)
    # Trade must REMAIN OPEN because BE is removed!
    bar2 = {"date": datetime(2026, 11, 9, 9, 32), "open": 25004.0, "high": 25004.0, "low": 24999.0, "close": 25001.0}
    res2 = engine.process_exit_conditions(active, bar2, bar_idx=2, entry_bar_idx=0)
    assert res2 is None
    assert active["current_stop"] == 130.0

    # Bar 3: Spot surges +6.5 pts -> option high reaches 138.25 (> 138.0 target) -> Exits with TARGET!
    bar3 = {"date": datetime(2026, 11, 9, 9, 33), "open": 25001.0, "high": 25006.5, "low": 25001.0, "close": 25006.0}
    res3 = engine.process_exit_conditions(active, bar3, bar_idx=3, entry_bar_idx=0)
    assert res3 is not None
    assert res3.exit_reason == "TARGET"
    assert res3.points_pnl == 2.95  # 3.0 - 0.05 slippage

