import pytest
import pandas as pd
from nifty_algo.config.config_loader import AppConfig
from nifty_algo.strategies import (
    BreakoutRetestSetup,
    LiquiditySweepReversalSetup,
    FVGConfirmationSetup,
    SetupSignal
)
from nifty_algo.confidence.scorer import ConfidenceScorer

def test_fvg_never_independently_triggers():
    setup = FVGConfirmationSetup()
    candles_3m = [
        {"open": 24000, "high": 24010, "low": 23990, "close": 24005},
        {"open": 24005, "high": 24040, "low": 24000, "close": 24035},
        {"open": 24035, "high": 24050, "low": 24020, "close": 24045},  # Low 24020 > High 24010 -> Gap of 10 pts
    ]
    sig = setup.evaluate([], candles_3m, {}, {})
    assert sig.direction == "BULLISH"
    # STRICT REQUIREMENT SECTION 9: FVG must NEVER independently trigger an entry!
    assert sig.triggered is False

def test_liquidity_sweep_reversal_bsl():
    setup = LiquiditySweepReversalSetup()
    structure = {
        "last_swing_high": 24100.0,
        "last_swing_low": 23900.0
    }
    # Candle that pierces 24100 to 24115, but closes down at 24090 with long upper rejection wick
    candles_3m = [{
        "open": 24080, "high": 24115, "low": 24075, "close": 24090
    }]
    sig = setup.evaluate([], candles_3m, structure, {})
    assert sig.triggered is True
    assert sig.direction == "BEARISH"  # Sweep of highs leads to short / PE entry
    assert sig.confidence >= 85.0

def test_confidence_scorer_eligibility():
    config = AppConfig()
    scorer = ConfidenceScorer(config)

    # Simulated signals with Setup 1 triggered AND Setup 9 (FVG confirmation)
    signals = [
        SetupSignal(
            setup_id="SETUP_1_BREAKOUT_RETEST",
            setup_name="Breakout Retest",
            triggered=True,
            direction="BULLISH",
            confidence=85.0,
            timeframe="3m",
            entry_level=24050.0,
            invalidation_level=24030.0,
            reason="Retest confirmed",
            supporting_factors={}
        ),
        SetupSignal(
            setup_id="SETUP_9_FVG_CONFIRMATION",
            setup_name="FVG Confirmation",
            triggered=False,  # strictly confirmation
            direction="BULLISH",
            confidence=70.0,
            timeframe="5m",
            entry_level=24050.0,
            invalidation_level=24020.0,
            reason="Bullish FVG support",
            supporting_factors={}
        )
    ]
    structure = {
        "has_sufficient_room_ce": True,
        "orb_high": 24020.0,
        "cdl": 23950.0
    }
    indicators = {
        "current_price": 24060.0,
        "ema_bullish": True,
        "price_above_vwap": True,
        "adx_regime": "STRONG_TREND"
    }

    eval_res = scorer.score(signals, structure, indicators, {"poc": 24000.0}, {"oi_bias": "BULLISH_PE_WRITING"}, pd.DataFrame())
    assert eval_res.total_score >= 80.0
    assert eval_res.is_eligible is True
    assert eval_res.status == "ELIGIBLE"
    assert eval_res.direction == "BULLISH"

def test_momentum_override_rapid_move():
    config = AppConfig()
    scorer = ConfidenceScorer(config)

    # 5 bars moving 55 points rapidly
    df_1m = pd.DataFrame([
        {"open": 24000, "high": 24010, "low": 23995, "close": 24010},
        {"open": 24010, "high": 24025, "low": 24005, "close": 24020},
        {"open": 24020, "high": 24035, "low": 24015, "close": 24030},
        {"open": 24030, "high": 24045, "low": 24025, "close": 24045},
        {"open": 24045, "high": 24060, "low": 24040, "close": 24058},
    ])

    override, direction, points = scorer.check_momentum_override(df_1m)
    assert override is True
    assert direction == "BULLISH"
    assert points >= 50.0
