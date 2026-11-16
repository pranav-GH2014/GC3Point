import pytest
from nifty_algo.indicators.open_interest import OpenInterestAnalyzer, format_oi

def test_format_oi():
    assert format_oi(15_000_000) == "1.50 Cr"
    assert format_oi(350_000) == "3.50 L"
    assert format_oi(5_000) == "5.0 K"
    assert format_oi(500) == "500"

def test_open_interest_walls_short_covering_cross():
    # Mock chain with Call Wall at 25200 with Short Covering (Price Up, OI Down)
    chain = [
        {"tradingsymbol": "NIFTY26NOV25100CE", "strike": 25100.0, "instrument_type": "CE", "oi": 2000000, "oi_change": 10000, "ltp": 80.0, "price_change": 10.0},
        {"tradingsymbol": "NIFTY26NOV25200CE", "strike": 25200.0, "instrument_type": "CE", "oi": 5000000, "oi_change": -150000, "ltp": 45.0, "price_change": 8.0},
        {"tradingsymbol": "NIFTY26NOV25000PE", "strike": 25000.0, "instrument_type": "PE", "oi": 6000000, "oi_change": 250000, "ltp": 50.0, "price_change": -5.0},
        {"tradingsymbol": "NIFTY26NOV24900PE", "strike": 24900.0, "instrument_type": "PE", "oi": 3000000, "oi_change": 50000, "ltp": 30.0, "price_change": -3.0},
    ]
    spot = 25175.0
    hw_eval = type("HwEval", (), {"is_bullish_aligned": True, "is_bearish_aligned": False})()

    res = OpenInterestAnalyzer.calculate_oi_walls(chain, spot, hw_eval)

    assert res["has_data"] is True
    assert res["call_wall"]["strike"] == 25200.0
    assert res["call_wall"]["oi"] == 5000000.0
    assert res["call_wall"]["prediction"] == "WILL_CROSS"
    assert res["call_wall"]["confidence"] >= 80

    assert res["put_wall"]["strike"] == 25000.0
    assert res["put_wall"]["oi"] == 6000000.0
    assert res["put_wall"]["prediction"] == "BOUNCE_EXPECTED"

def test_open_interest_walls_call_defended_bounce():
    # Call writers actively adding massive OI at 25300
    chain = [
        {"tradingsymbol": "NIFTY26NOV25200CE", "strike": 25200.0, "instrument_type": "CE", "oi": 3000000, "oi_change": 50000, "ltp": 55.0, "price_change": -5.0},
        {"tradingsymbol": "NIFTY26NOV25300CE", "strike": 25300.0, "instrument_type": "CE", "oi": 8000000, "oi_change": 600000, "ltp": 25.0, "price_change": -8.0},
        {"tradingsymbol": "NIFTY26NOV25100PE", "strike": 25100.0, "instrument_type": "PE", "oi": 4000000, "oi_change": -200000, "ltp": 60.0, "price_change": -10.0},
    ]
    spot = 25250.0
    hw_eval = type("HwEval", (), {"is_bullish_aligned": False, "is_bearish_aligned": True})()

    res = OpenInterestAnalyzer.calculate_oi_walls(chain, spot, hw_eval)

    assert res["call_wall"]["strike"] == 25300.0
    assert res["call_wall"]["prediction"] == "BOUNCE_EXPECTED"
    assert res["put_wall"]["prediction"] == "WILL_BREAK"

def test_open_interest_fallback():
    res = OpenInterestAnalyzer.calculate_oi_walls([], 25140.0)
    assert res["has_data"] is False
    assert res["call_wall"]["strike"] == 25200.0
    assert res["put_wall"]["strike"] == 25100.0
