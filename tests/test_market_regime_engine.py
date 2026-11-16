import pytest
import pandas as pd
import numpy as np
from nifty_algo.market_regime_engine import MarketRegimeEngine, MarketRegime, MarketRegimeConfig

def generate_candles(trend="bullish", n=30, base_price=25000.0, step=10.0, vol=1000):
    candles = []
    price = base_price
    for i in range(n):
        if trend == "bullish":
            price += step
            c = {"date": f"2026-11-16 10:{i:02d}:00", "open": price - 5, "high": price + 5, "low": price - 6, "close": price, "volume": vol + i * 50}
        elif trend == "bearish":
            price -= step
            c = {"date": f"2026-11-16 10:{i:02d}:00", "open": price + 5, "high": price + 6, "low": price - 5, "close": price, "volume": vol + i * 50}
        elif trend == "sideways":
            delta = 3.0 if i % 2 == 0 else -3.0
            price = base_price + delta
            c = {"date": f"2026-11-16 10:{i:02d}:00", "open": base_price, "high": base_price + 4, "low": base_price - 4, "close": price, "volume": vol}
        elif trend == "high_volatility":
            # Normal quiet market first, then massive volatility explosion
            if i < 20:
                price += 1.0
                c = {"date": f"2026-11-16 10:{i:02d}:00", "open": price, "high": price + 2, "low": price - 2, "close": price, "volume": vol}
            else:
                price += (35.0 if i % 2 == 0 else -30.0)
                c = {"date": f"2026-11-16 10:{i:02d}:00", "open": price - 15, "high": price + 25, "low": price - 25, "close": price, "volume": vol * 4}
        candles.append(c)
    return pd.DataFrame(candles)

def test_regime_insufficient_bars():
    engine = MarketRegimeEngine()
    df = generate_candles(n=5)
    res = engine.classify_regime(df)
    assert res.regime == MarketRegime.UNKNOWN
    assert res.allow_momentum is False
    assert res.allow_breakout is False

def test_regime_trending_bullish():
    engine = MarketRegimeEngine()
    df = generate_candles(trend="bullish", n=35, step=15.0)
    indicators = {"vwap": 24900.0}
    res = engine.classify_regime(df, indicators=indicators)
    assert res.regime == MarketRegime.TRENDING_BULLISH
    assert res.allow_ce is True
    assert res.allow_pe is False
    assert res.allow_momentum is True

def test_regime_trending_bearish():
    engine = MarketRegimeEngine()
    df = generate_candles(trend="bearish", n=35, step=15.0)
    indicators = {"vwap": 25100.0}
    res = engine.classify_regime(df, indicators=indicators)
    assert res.regime == MarketRegime.TRENDING_BEARISH
    assert res.allow_pe is True
    assert res.allow_ce is False

def test_regime_sideways_blocks_momentum_and_breakout():
    engine = MarketRegimeEngine()
    df = generate_candles(trend="sideways", n=35)
    indicators = {"vwap": 25000.0}
    res = engine.classify_regime(df, indicators=indicators)
    assert res.regime == MarketRegime.SIDEWAYS
    assert res.allow_momentum is False
    assert res.allow_breakout is False
    assert res.allow_ce is False
    assert res.allow_pe is False

def test_regime_high_volatility():
    engine = MarketRegimeEngine()
    df = generate_candles(trend="high_volatility", n=35)
    res = engine.classify_regime(df)
    assert res.regime == MarketRegime.HIGH_VOLATILITY
    assert res.allow_breakout is False  # Breakouts in high vol are disabled
