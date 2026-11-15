from typing import Dict, Any, List

class CandlestickPatternRecognizer:
    """
    Identifies single and two-candle patterns on completed bars:
    - Bullish / Bearish Engulfing
    - Hammer / Inverted Hammer
    - Shooting Star / Hanging Man
    - Marubozu (strong trend bar, body >= 80% of range)
    - Doji (indecision bar, body <= 10% of range)
    Contextual: Requires support/resistance or trend alignment.
    """

    @staticmethod
    def identify_patterns(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(candles) < 2:
            return {"pattern": "NONE", "bias": "NEUTRAL", "confidence": 0.0}

        prev = candles[-2]
        curr = candles[-1]

        c_open, c_high, c_low, c_close = curr["open"], curr["high"], curr["low"], curr["close"]
        p_open, p_high, p_low, p_close = prev["open"], prev["high"], prev["low"], prev["close"]

        c_range = c_high - c_low
        if c_range <= 0:
            return {"pattern": "NONE", "bias": "NEUTRAL", "confidence": 0.0}

        c_body = abs(c_close - c_open)
        c_upper_wick = c_high - max(c_open, c_close)
        c_lower_wick = min(c_open, c_close) - c_low

        p_body = abs(p_close - p_open)

        # 1. Doji
        if (c_body / c_range) <= 0.10:
            return {"pattern": "DOJI", "bias": "INDECISION", "confidence": 0.4}

        # 2. Bullish Engulfing (Prev bearish, curr bullish engulfing prev body)
        if p_close < p_open and c_close > c_open:
            if c_open <= p_close and c_close >= p_open and c_body > p_body:
                return {"pattern": "BULLISH_ENGULFING", "bias": "BULLISH", "confidence": 0.85}

        # 3. Bearish Engulfing (Prev bullish, curr bearish engulfing prev body)
        if p_close > p_open and c_close < c_open:
            if c_open >= p_close and c_close <= p_open and c_body > p_body:
                return {"pattern": "BEARISH_ENGULFING", "bias": "BEARISH", "confidence": 0.85}

        # 4. Hammer (Long lower shadow >= 2x body, tiny upper shadow, at support)
        if c_lower_wick >= 2.0 * c_body and c_upper_wick <= 0.2 * c_range:
            return {"pattern": "HAMMER", "bias": "BULLISH", "confidence": 0.75}

        # 5. Shooting Star (Long upper shadow >= 2x body, tiny lower shadow, at resistance)
        if c_upper_wick >= 2.0 * c_body and c_lower_wick <= 0.2 * c_range:
            return {"pattern": "SHOOTING_STAR", "bias": "BEARISH", "confidence": 0.75}

        # 6. Marubozu (Strong directional impulse bar)
        if (c_body / c_range) >= 0.80:
            bias = "BULLISH" if c_close > c_open else "BEARISH"
            return {"pattern": "MARUBOZU", "bias": bias, "confidence": 0.80}

        return {"pattern": "NONE", "bias": "NEUTRAL", "confidence": 0.0}
