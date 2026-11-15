from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal

class BOSEngine(BaseSetup):
    """
    Setup C: Break of Structure (BOS) Setup (Section 2C)
    - Bullish BOS: Confirmed break above previous swing high + displacement / strong bullish candle -> BUY CE.
    - Bearish BOS: Confirmed break below previous swing low + displacement / strong bearish candle -> BUY PE.
    """

    def __init__(self, min_displacement_ratio: float = 0.50):
        super().__init__("SETUP_BOS", "Break of Structure (BOS)", "3m+1m")
        self.min_displacement_ratio = min_displacement_ratio

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        if len(candles_3m) < 3 or len(candles_1m) < 2 or not structure:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        curr_3m = candles_3m[-1]
        prev_3m = candles_3m[-2]
        curr_1m = candles_1m[-1]
        current_price = curr_1m["close"]

        last_swing_high = structure.get("last_swing_high")
        last_swing_low = structure.get("last_swing_low")

        c3_range = curr_3m["high"] - curr_3m["low"]
        if c3_range <= 0:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Zero range candle", {})

        c3_body = abs(curr_3m["close"] - curr_3m["open"])
        displacement_ratio = c3_body / c3_range

        # 1. Bullish BOS (CE Signal)
        # Previous 3m candle was below or at swing high, current 3m candle breaks and closes above swing high
        if last_swing_high is not None and prev_3m["close"] <= last_swing_high:
            if curr_3m["close"] > last_swing_high and curr_3m["close"] > curr_3m["open"]:
                # Displacement confirmation: solid green candle body
                if displacement_ratio >= self.min_displacement_ratio and curr_1m["close"] > last_swing_high:
                    upper_wick = curr_3m["high"] - curr_3m["close"]
                    # Ensure not an exhausted wick
                    if (upper_wick / c3_range) < 0.40:
                        conf = 85.0 if displacement_ratio >= 0.65 else 80.0
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BULLISH",
                            confidence=conf,
                            timeframe="3m",
                            entry_level=current_price,
                            invalidation_level=last_swing_high - 5.0,
                            reason=f"Bullish BOS break above 3m swing high {last_swing_high:.1f} with {displacement_ratio*100:.0f}% displacement",
                            supporting_factors={
                                "broken_swing_high": last_swing_high,
                                "displacement_ratio": round(displacement_ratio, 2),
                                "category": "BOS"
                            }
                        )

        # 2. Bearish BOS (PE Signal)
        # Previous 3m candle was above or at swing low, current 3m candle breaks and closes below swing low
        if last_swing_low is not None and prev_3m["close"] >= last_swing_low:
            if curr_3m["close"] < last_swing_low and curr_3m["close"] < curr_3m["open"]:
                if displacement_ratio >= self.min_displacement_ratio and curr_1m["close"] < last_swing_low:
                    lower_wick = curr_3m["close"] - curr_3m["low"]
                    if (lower_wick / c3_range) < 0.40:
                        conf = 85.0 if displacement_ratio >= 0.65 else 80.0
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BEARISH",
                            confidence=conf,
                            timeframe="3m",
                            entry_level=current_price,
                            invalidation_level=last_swing_low + 5.0,
                            reason=f"Bearish BOS break below 3m swing low {last_swing_low:.1f} with {displacement_ratio*100:.0f}% displacement",
                            supporting_factors={
                                "broken_swing_low": last_swing_low,
                                "displacement_ratio": round(displacement_ratio, 2),
                                "category": "BOS"
                            }
                        )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No BOS trigger", {})
