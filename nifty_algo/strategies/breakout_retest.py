from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class BreakoutRetestSetup(BaseSetup):
    """
    Setup 1: Breakout and Retest
    - Bullish: Price closed above resistance (PDH, CDH), retests level, holds above it.
    - Bearish: Price closed below support (PDL, CDL), retests level, holds below it.
    """

    def __init__(self):
        super().__init__("SETUP_1_BREAKOUT_RETEST", "Breakout and Retest", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if len(candles_3m) < 3 or not structure:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        c1, c2, c3 = candles_3m[-3], candles_3m[-2], candles_3m[-1]
        curr_price = c3["close"]
        
        # Identify broken levels
        orb_h = structure.get("orb_high", 0.0)
        orb_l = structure.get("orb_low", 0.0)
        cdh = structure.get("cdh", 0.0)
        cdl = structure.get("cdl", 0.0)
        pdh = structure.get("pdh")
        pdl = structure.get("pdl")

        # 1. Bullish Breakout & Retest: Price broke above a resistance level and holds upon retest
        candidate_res = [r for r in [orb_h, pdh] if r and r < curr_price]
        if candidate_res:
            broken_res = max(candidate_res)
            # Breakout bar (c1 or c2) pushed above level, retest touched near level, c3 holds green above level
            if (c1["close"] > broken_res or c2["close"] > broken_res) and c2["low"] <= broken_res + 3.5 and c3["close"] > broken_res and c3["close"] > c3["open"]:
                if indicators.get("ema_bullish") or c3["close"] > indicators.get("ema8", 0):
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BULLISH",
                        confidence=84.0,
                        timeframe=self.timeframe,
                        entry_level=c3["close"],
                        invalidation_level=broken_res - 4.0,
                        reason=f"Confirmed 3m breakout and retest bounce above {broken_res:.2f}",
                        supporting_factors={"retest_level": broken_res, "ema_aligned": True}
                    )

        # 2. Bearish Breakdown & Retest: Price broke below support and rejects upon retest
        candidate_sup = [s for s in [orb_l, pdl] if s and s > curr_price]
        if candidate_sup:
            broken_sup = min(candidate_sup)
            if (c1["close"] < broken_sup or c2["close"] < broken_sup) and c2["high"] >= broken_sup - 3.5 and c3["close"] < broken_sup and c3["close"] < c3["open"]:
                if indicators.get("ema_bearish") or c3["close"] < indicators.get("ema8", 0):
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BEARISH",
                        confidence=84.0,
                        timeframe=self.timeframe,
                        entry_level=c3["close"],
                        invalidation_level=broken_sup + 4.0,
                        reason=f"Confirmed 3m breakdown and retest rejection below {broken_sup:.2f}",
                        supporting_factors={"retest_level": broken_sup, "ema_aligned": True}
                    )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No breakout-retest pattern", {})
