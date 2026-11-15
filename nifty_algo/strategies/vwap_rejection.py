from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class VWAPRejectionSetup(BaseSetup):
    """
    Setup 4: VWAP Rejection
    - Bearish Rejection: Price rallies into VWAP from below, forms upper rejection wick, closes below VWAP.
    - Bullish Bounce: Price dips into VWAP from above, forms lower bounce wick, closes above VWAP.
    """

    def __init__(self):
        super().__init__("SETUP_4_VWAP_REJECTION", "VWAP Rejection", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if not candles_3m or not indicators.get("vwap"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars/VWAP", {})

        curr = candles_3m[-1]
        vwap = indicators["vwap"]
        c_range = curr["high"] - curr["low"]
        if c_range <= 0:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Zero range candle", {})

        # Bearish Rejection from below
        if curr["high"] >= vwap - 1.5 and curr["close"] < vwap:
            upper_wick = curr["high"] - max(curr["open"], curr["close"])
            if (upper_wick / c_range >= 0.25 or curr["close"] < curr["open"]) and (indicators.get("ema_bearish") or curr["close"] < indicators.get("ema8", 0)):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=83.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=curr["high"] + 2.0,
                    reason=f"Bearish 3m VWAP rejection at {vwap:.2f} with {upper_wick/c_range*100:.0f}% wick",
                    supporting_factors={"vwap": vwap, "rejection_type": "UPPER_WICK"}
                )

        # Bullish Bounce from above
        if curr["low"] <= vwap + 1.5 and curr["close"] > vwap:
            lower_wick = min(curr["open"], curr["close"]) - curr["low"]
            if (lower_wick / c_range >= 0.25 or curr["close"] > curr["open"]) and (indicators.get("ema_bullish") or curr["close"] > indicators.get("ema8", 0)):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=83.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=curr["low"] - 2.0,
                    reason=f"Bullish 3m VWAP bounce at {vwap:.2f} with {lower_wick/c_range*100:.0f}% wick",
                    supporting_factors={"vwap": vwap, "rejection_type": "LOWER_WICK"}
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No VWAP rejection", {})
