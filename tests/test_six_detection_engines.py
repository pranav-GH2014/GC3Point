import pytest
from nifty_algo.strategies.momentum_detection_engine import MomentumDetectionEngine
from nifty_algo.strategies.retest_detection_engine import RetestDetectionEngine
from nifty_algo.strategies.retail_trap_detection_engine import RetailTrapDetectionEngine
from nifty_algo.strategies.breakout_detection_engine import BreakoutDetectionEngine
from nifty_algo.strategies.fvg_opportunity_engine import FVGOpportunityEngine
from nifty_algo.strategies.oi_intelligence_engine import OIIntelligenceEngine
from nifty_algo.strategies.signal_arbitration_engine import SignalArbitrationEngine
from nifty_algo.strategies.base_setup import OpportunitySignal

def make_candle(close, open_p, high=None, low=None, vol=1000, date_str="2026-11-10 10:00:00"):
    h = high if high is not None else max(close, open_p) + 2.0
    l = low if low is not None else min(close, open_p) - 2.0
    return {"date": date_str, "open": open_p, "high": h, "low": l, "close": close, "volume": vol}

def test_momentum_detection_engine_ce():
    engine = MomentumDetectionEngine(min_body_ratio=0.6, min_vol_ratio=1.2)
    # 11 baseline bars
    candles = [make_candle(24000.0, 23998.0, 24002.0, 23996.0, vol=500) for _ in range(11)]
    # Big green expansion candle with volume
    candles.append(make_candle(24020.0, 24001.0, 24022.0, 24000.0, vol=2000))
    
    indicators = {"ema8": 24005.0, "vwap": 24000.0}
    sig = engine.evaluate(candles, [], {}, indicators)
    assert sig.triggered is True
    assert sig.direction == "CE"
    assert sig.confidence >= 80.0

def test_retest_detection_engine_support_bounce():
    engine = RetestDetectionEngine(tolerance_pts=4.0)
    structure = {"orb_high": 24100.0, "pdh": 24100.0}
    # Prior bar touches near 24100, current bar closes green above 24100
    c1 = make_candle(24102.0, 24110.0, 24112.0, 24100.5) # touched 24100.5
    c2 = make_candle(24115.0, 24103.0, 24116.0, 24102.0) # green bounce
    candles = [make_candle(24090, 24080) for _ in range(5)] + [c1, c2]
    
    indicators = {"ema8": 24100.0, "ema_bullish": True}
    sig = engine.evaluate(candles, [], structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "CE"
    assert sig.supporting_metadata["retested_level"] in ("ORB_HIGH", "PDH")

def test_retail_trap_detection_engine_bull_trap():
    engine = RetailTrapDetectionEngine()
    structure = {"cdh": 24200.0}
    # Prior bar sweeps above 24200 up to 24215, closes back down at 24198
    c_sweep = make_candle(close=24198.0, open_p=24195.0, high=24215.0, low=24190.0)
    # Current bar confirms down rejection
    c_reject = make_candle(close=24188.0, open_p=24197.0, high=24198.0, low=24185.0)
    candles = [make_candle(24180, 24175) for _ in range(15)] + [c_sweep, c_reject]
    
    indicators = {"vwap": 24195.0}
    sig = engine.evaluate(candles, [], structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "PE"
    assert sig.supporting_metadata["trap_type"] == "BULL_TRAP"

def test_breakout_detection_engine_immediate():
    engine = BreakoutDetectionEngine(min_breakout_pts=2.0)
    structure = {"orb_high": 24150.0}
    # Strong breakout candle closing cleanly above 24150
    candles = [make_candle(24140, 24135, 24145, 24130, vol=500) for _ in range(15)]
    # Breakout bar
    candles.append(make_candle(close=24160.0, open_p=24148.0, high=24162.0, low=24146.0, vol=1500))
    
    indicators = {"vwap": 24140.0}
    sig = engine.evaluate(candles, [], structure, indicators)
    assert sig.triggered is True
    assert sig.direction == "CE"
    assert sig.supporting_metadata["broken_level"] == 24150.0

def test_fvg_opportunity_engine_bullish_imbalance():
    engine = FVGOpportunityEngine(min_gap_pts=3.0)
    # c1 high is 24005.0
    c1 = make_candle(close=24004.0, open_p=24000.0, high=24005.0, low=23998.0)
    # c2 big displacement
    c2 = make_candle(close=24025.0, open_p=24006.0, high=24027.0, low=24005.0)
    # c3 low is 24015.0 (gap between c1 high 24005 and c3 low 24015 is 10 pts)
    c3 = make_candle(close=24030.0, open_p=24018.0, high=24032.0, low=24015.0)
    candles = [make_candle(24000, 23995) for _ in range(5)] + [c1, c2, c3]
    
    indicators = {"vwap": 24010.0}
    sig = engine.evaluate(candles, [], {}, indicators)
    assert sig.triggered is True
    assert sig.direction == "CE"
    assert sig.supporting_metadata["gap_points"] >= 3.0

def test_oi_intelligence_engine_requires_price_confirmation():
    engine = OIIntelligenceEngine()
    # Bullish OI data
    oi_data = {"oi_bias": "BULLISH_PE_WRITING", "pcr": 1.35, "ce_oi_change": 10000, "pe_oi_change": 50000}
    
    # But current price candle is RED (close < open)
    c_red = make_candle(close=23980.0, open_p=23990.0)
    candles = [make_candle(24000, 23995) for _ in range(5)] + [c_red]
    indicators = {"ema8": 23995.0, "vwap": 24000.0}
    
    sig = engine.evaluate(candles, [], {}, indicators, oi_data=oi_data)
    # MUST NOT trigger on OI alone!
    assert sig.triggered is False

    # Now with GREEN confirming candle
    c_green = make_candle(close=24010.0, open_p=23995.0)
    candles.append(c_green)
    sig_confirmed = engine.evaluate(candles, [], {}, indicators, oi_data=oi_data)
    assert sig_confirmed.triggered is True
    assert sig_confirmed.direction == "CE"

def test_signal_arbitration_engine_duplicate_merging_and_conflicts():
    arbitrator = SignalArbitrationEngine(min_confidence_threshold=75.0)
    
    # 1. Duplicate co-directional signals (Engine 1 & Engine 4 both CE)
    sig1 = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM", strategy_name="Momentum Detection", triggered=True,
        direction="CE", timestamp="10:00", reference_price=24100.0, entry_condition="Impulse",
        confidence=85.0, stop_loss_pts=4.0
    )
    sig2 = OpportunitySignal(
        strategy_id="ENGINE_4_BREAKOUT", strategy_name="Breakout Detection", triggered=True,
        direction="CE", timestamp="10:00", reference_price=24100.0, entry_condition="ORB break",
        confidence=88.0, stop_loss_pts=5.0
    )
    decision = arbitrator.arbitrate([sig1, sig2], indicators={}, has_open_position=False)
    assert decision.should_execute is True
    assert decision.direction == "CE"
    assert decision.duplicate_merged is True
    assert len(decision.contributing_strategies) == 2

    # 2. Conflicting equal signals (CE vs PE in primary drivers)
    sig_pe = OpportunitySignal(
        strategy_id="ENGINE_1_MOMENTUM", strategy_name="Momentum Detection", triggered=True,
        direction="PE", timestamp="10:00", reference_price=24100.0, entry_condition="Bearish impulse",
        confidence=88.0, stop_loss_pts=4.0
    )
    decision_conflict = arbitrator.arbitrate([sig2, sig_pe], indicators={"vwap": 24100.0}, has_open_position=False)
    # Equal opposing primary signals without clear resolution stand aside safely
    assert decision_conflict.should_execute is False
    assert decision_conflict.conflict_detected is True

    # 3. Position Active Lock
    decision_locked = arbitrator.arbitrate([sig1], indicators={}, has_open_position=True)
    assert decision_locked.should_execute is False
    assert "REJECTED_OPEN_POSITION_ACTIVE" in decision_locked.rejection_reasons
