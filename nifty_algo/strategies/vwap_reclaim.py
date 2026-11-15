from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class VWAPReclaimSetup(BaseSetup):
    """
    Setup 3: VWAP Reclaim
    - Bullish: Price dropped below VWAP, then crosses and closes back above VWAP with bullish body.
    - Bearish (VWAP Loss): Price was above VWAP, then breaks and closes below VWAP with bearish body.
    """

    def __init__(self):
        super().__init__("SETUP_3_VWAP_RECLAIM", "VWAP Reclaim", "1m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if len(candles_1m) < 2 or not indicators.get("vwap"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars/VWAP", {})

        prev = candles_1m[-2]
        curr = candles_1m[-1]
        vwap = indicators["vwap"]

        # Bullish Reclaim: Prev below VWAP, Curr closes above VWAP with green body
        if prev["close"] < vwap and curr["close"] > vwap and curr["close"] > curr["open"]:
            if indicators.get("ema_bullish") or curr["close"] > indicators.get("ema8", 0):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=83.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=min(prev["low"], curr["low"]) - 2.0,
                    reason=f"Bullish 1m VWAP reclaim above {vwap:.2f} with momentum",
                    supporting_factors={"vwap": vwap, "prev_close": prev["close"], "curr_close": curr["close"]}
                )

        # Bearish Breakdown: Prev above VWAP, Curr closes below VWAP with red body
        if prev["close"] > vwap and curr["close"] < vwap and curr["close"] < curr["open"]:
            if indicators.get("ema_bearish") or curr["close"] < indicators.get("ema8", 0):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=83.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=max(prev["high"], curr["high"]) + 2.0,
                    reason=f"Bearish 1m VWAP breakdown below {vwap:.2f} with momentum",
                    supporting_factors={"vwap": vwap, "prev_close": prev["close"], "curr_close": curr["close"]}
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No VWAP reclaim", {})
