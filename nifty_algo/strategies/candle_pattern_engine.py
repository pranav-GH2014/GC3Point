from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal
from ..patterns.candlestick import CandlestickPatternRecognizer

class CandlePatternEngine(BaseSetup):
    """
    Setup E: Candle Pattern Setup (Section 2E)
    Detects meaningful candlestick structures:
    - Bullish / Bearish Engulfing
    - Hammer / Shooting Star
    - Strong Momentum Candles (Marubozu)
    - Rejection Candles (Pin-Bars)
    - Inside-Bar Breakouts
    Filters out insignificant micro-candles.
    """

    def __init__(self, min_significant_pts: float = 6.0):
        super().__init__("SETUP_CANDLE_PATTERN", "Candle Pattern Engine", "1m/3m")
        self.min_significant_pts = min_significant_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        if len(candles_3m) < 3:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        c_mother = candles_3m[-3]
        c_prev = candles_3m[-2]
        c_curr = candles_3m[-1]
        current_price = c_curr["close"]

        c_range = c_curr["high"] - c_curr["low"]
        # Filter out insignificant micro-candles
        if c_range < self.min_significant_pts:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insignificant candle range", {})

        c_body = abs(c_curr["close"] - c_curr["open"])
        body_ratio = c_body / c_range if c_range > 0 else 0
        upper_wick = c_curr["high"] - max(c_curr["open"], c_curr["close"])
        lower_wick = min(c_curr["open"], c_curr["close"]) - c_curr["low"]

        # 1. Inside-Bar Breakout
        is_inside_bar = (c_prev["high"] <= c_mother["high"] and c_prev["low"] >= c_mother["low"])
        if is_inside_bar:
            # Bullish inside-bar break
            if c_curr["close"] > c_mother["high"] and c_curr["close"] > c_curr["open"]:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=83.0,
                    timeframe="3m",
                    entry_level=current_price,
                    invalidation_level=c_prev["low"] - 3.0,
                    reason=f"Bullish inside-bar breakout above mother bar high {c_mother['high']:.1f}",
                    supporting_factors={"pattern": "INSIDE_BAR_BREAKOUT", "category": "CANDLE_PATTERN"}
                )
            # Bearish inside-bar break
            elif c_curr["close"] < c_mother["low"] and c_curr["close"] < c_curr["open"]:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=83.0,
                    timeframe="3m",
                    entry_level=current_price,
                    invalidation_level=c_prev["high"] + 3.0,
                    reason=f"Bearish inside-bar breakdown below mother bar low {c_mother['low']:.1f}",
                    supporting_factors={"pattern": "INSIDE_BAR_BREAKDOWN", "category": "CANDLE_PATTERN"}
                )

        # 2. Standard Contextual Candle Patterns (Engulfing / Hammer / Star)
        pat_res = CandlestickPatternRecognizer.identify_patterns(candles_3m)
        pattern = pat_res.get("pattern")
        bias = pat_res.get("bias")

        if pattern in ("BULLISH_ENGULFING", "HAMMER") and bias == "BULLISH":
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BULLISH",
                confidence=82.0,
                timeframe="3m",
                entry_level=current_price,
                invalidation_level=c_curr["low"] - 3.0,
                reason=f"Confirmed {pattern} with {c_range:.1f} pts significant range",
                supporting_factors={"pattern": pattern, "category": "CANDLE_PATTERN"}
            )
        elif pattern in ("BEARISH_ENGULFING", "SHOOTING_STAR") and bias == "BEARISH":
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BEARISH",
                confidence=82.0,
                timeframe="3m",
                entry_level=current_price,
                invalidation_level=c_curr["high"] + 3.0,
                reason=f"Confirmed {pattern} with {c_range:.1f} pts significant range",
                supporting_factors={"pattern": pattern, "category": "CANDLE_PATTERN"}
            )

        # 3. Strong Momentum Marubozu
        if body_ratio >= 0.75:
            if c_curr["close"] > c_curr["open"]:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=81.0,
                    timeframe="3m",
                    entry_level=current_price,
                    invalidation_level=c_curr["low"] - 3.0,
                    reason=f"Bullish momentum expansion candle ({body_ratio*100:.0f}% body)",
                    supporting_factors={"pattern": "BULLISH_MARUBOZU", "category": "CANDLE_PATTERN"}
                )
            elif c_curr["close"] < c_curr["open"]:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=81.0,
                    timeframe="3m",
                    entry_level=current_price,
                    invalidation_level=c_curr["high"] + 3.0,
                    reason=f"Bearish momentum expansion candle ({body_ratio*100:.0f}% body)",
                    supporting_factors={"pattern": "BEARISH_MARUBOZU", "category": "CANDLE_PATTERN"}
                )

        # 4. Significant Rejection Pin-Bar
        if (lower_wick / c_range) >= 0.45 and c_curr["close"] > c_curr["open"]:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BULLISH",
                confidence=81.0,
                timeframe="3m",
                entry_level=current_price,
                invalidation_level=c_curr["low"] - 3.0,
                reason=f"Bullish rejection pin-bar ({(lower_wick/c_range)*100:.0f}% lower wick)",
                supporting_factors={"pattern": "PIN_BAR_BOUNCE", "category": "CANDLE_PATTERN"}
            )
        elif (upper_wick / c_range) >= 0.45 and c_curr["close"] < c_curr["open"]:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BEARISH",
                confidence=81.0,
                timeframe="3m",
                entry_level=current_price,
                invalidation_level=c_curr["high"] + 3.0,
                reason=f"Bearish rejection pin-bar ({(upper_wick/c_range)*100:.0f}% upper wick)",
                supporting_factors={"pattern": "PIN_BAR_REJECTION", "category": "CANDLE_PATTERN"}
            )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No significant pattern", {})
