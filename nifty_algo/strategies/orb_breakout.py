from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class OpeningRangeBreakoutSetup(BaseSetup):
    """
    Setup 6: Opening-Range Breakout (ORB)
    - Calculated over the first 15 minutes (9:15 - 9:30 AM IST).
    - Entries allowed only after 9:20 AM IST per Prompt Schedule.
    - Bullish: 3m candle closes completely above ORB High with volume and EMA alignment.
    - Bearish: 3m candle closes completely below ORB Low with volume and EMA alignment.
    """

    def __init__(self):
        super().__init__("SETUP_6_ORB_BREAKOUT", "Opening-Range Breakout", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if not candles_3m or not structure.get("orb_high") or not structure.get("orb_low"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "ORB levels not established", {})

        curr = candles_3m[-1]
        prev = candles_3m[-2] if len(candles_3m) >= 2 else curr
        orb_high = structure["orb_high"]
        orb_low = structure["orb_low"]

        # Bullish ORB Breakout: Fresh breakout or retest bounce
        is_fresh_breakout_ce = (prev["close"] <= orb_high and curr["close"] > orb_high)
        is_retest_bounce_ce = (curr["low"] <= orb_high + 3.0 and curr["close"] > orb_high and curr["close"] > curr["open"])

        if is_fresh_breakout_ce or is_retest_bounce_ce:
            if indicators.get("ema_bullish") and indicators.get("price_above_vwap"):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=85.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=orb_high - 5.0,
                    reason=f"Confirmed 3m ORB breakout/retest above {orb_high:.2f}",
                    supporting_factors={"orb_high": orb_high, "orb_low": orb_low, "is_fresh": is_fresh_breakout_ce}
                )

        # Bearish ORB Breakdown: Fresh breakdown or retest rejection
        is_fresh_breakdown_pe = (prev["close"] >= orb_low and curr["close"] < orb_low)
        is_retest_rejection_pe = (curr["high"] >= orb_low - 3.0 and curr["close"] < orb_low and curr["close"] < curr["open"])

        if is_fresh_breakdown_pe or is_retest_rejection_pe:
            if indicators.get("ema_bearish") and indicators.get("price_below_vwap"):
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=85.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=orb_low + 5.0,
                    reason=f"Confirmed 3m ORB breakdown/retest below {orb_low:.2f}",
                    supporting_factors={"orb_high": orb_high, "orb_low": orb_low, "is_fresh": is_fresh_breakdown_pe}
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Inside opening range", {})
