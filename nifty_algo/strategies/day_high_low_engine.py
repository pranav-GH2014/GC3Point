from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal

class DayHighLowEngine(BaseSetup):
    """
    Setup B: Day High and Day Low Setup (Section 2B)
    - Sweep & Reclaim: Sweep below Day Low / PDL followed by reclaim -> BUY CE.
    - Sweep & Reject: Sweep above Day High / PDH followed by rejection -> BUY PE.
    - Genuine Breakout: Strong displacement close beyond Day High/Low (distinguished from sweep).
    """

    def __init__(self, sweep_min_penetration: float = 2.0, sweep_max_penetration: float = 25.0):
        super().__init__("SETUP_DAY_HIGH_LOW", "Day High / Day Low Engine", "1m/3m")
        self.sweep_min_penetration = sweep_min_penetration
        self.sweep_max_penetration = sweep_max_penetration

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        if len(candles_3m) < 2 or len(candles_1m) < 2 or not structure:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing data", {})

        curr_3m = candles_3m[-1]
        prev_3m = candles_3m[-2]
        curr_1m = candles_1m[-1]
        current_price = curr_1m["close"]

        cdh = structure.get("cdh")
        cdl = structure.get("cdl")
        pdh = structure.get("pdh")
        pdl = structure.get("pdl")

        c3_range = curr_3m["high"] - curr_3m["low"]
        if c3_range <= 0:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Zero range candle", {})

        # Evaluate against CDL / PDL (Low levels)
        low_levels = [lvl for lvl in [cdl, pdl] if lvl is not None]
        for lvl in low_levels:
            # 1. Sweep Below Low and Reclaim (Bullish CE)
            # Candle pierced below level, but closed back above level
            penetration = lvl - curr_3m["low"]
            if self.sweep_min_penetration <= penetration <= self.sweep_max_penetration:
                if curr_3m["close"] > lvl and curr_1m["close"] > lvl:
                    lower_wick = min(curr_3m["open"], curr_3m["close"]) - curr_3m["low"]
                    wick_ratio = lower_wick / c3_range
                    if wick_ratio >= 0.30 or curr_3m["close"] > curr_3m["open"]:
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BULLISH",
                            confidence=84.0,
                            timeframe="3m+1m",
                            entry_level=current_price,
                            invalidation_level=curr_3m["low"] - 3.0,
                            reason=f"Day Low sweep of {lvl:.1f} (-{penetration:.1f} pts) & bullish reclaim",
                            supporting_factors={
                                "level": lvl,
                                "type": "SWEEP_RECLAIM",
                                "penetration": round(penetration, 2),
                                "wick_ratio": round(wick_ratio, 2),
                                "category": "LIQUIDITY_SWEEP"
                            }
                        )

            # 2. Genuine Bearish Breakdown beyond Day Low (PE)
            # Body closes convincingly below level (not a wick trap)
            body = abs(curr_3m["close"] - curr_3m["open"])
            if prev_3m["close"] >= lvl and curr_3m["close"] < lvl - 2.0:
                # Must be a solid red candle closing near lows
                if curr_3m["close"] < curr_3m["open"] and (body / c3_range) >= 0.55:
                    lower_wick = curr_3m["close"] - curr_3m["low"]
                    if (lower_wick / c3_range) < 0.35:  # Not a rejection wick
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BEARISH",
                            confidence=82.0,
                            timeframe="3m",
                            entry_level=current_price,
                            invalidation_level=lvl + 4.0,
                            reason=f"Genuine breakdown below Day Low {lvl:.1f} with displacement",
                            supporting_factors={
                                "level": lvl,
                                "type": "GENUINE_BREAKDOWN",
                                "category": "DAY_LEVEL_BREAKOUT"
                            }
                        )

        # Evaluate against CDH / PDH (High levels)
        high_levels = [lvl for lvl in [cdh, pdh] if lvl is not None]
        for lvl in high_levels:
            # 1. Sweep Above High and Rejection (Bearish PE)
            # Candle pierced above level, but closed back below level
            penetration = curr_3m["high"] - lvl
            if self.sweep_min_penetration <= penetration <= self.sweep_max_penetration:
                if curr_3m["close"] < lvl and curr_1m["close"] < lvl:
                    upper_wick = curr_3m["high"] - max(curr_3m["open"], curr_3m["close"])
                    wick_ratio = upper_wick / c3_range
                    if wick_ratio >= 0.30 or curr_3m["close"] < curr_3m["open"]:
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BEARISH",
                            confidence=84.0,
                            timeframe="3m+1m",
                            entry_level=current_price,
                            invalidation_level=curr_3m["high"] + 3.0,
                            reason=f"Day High sweep of {lvl:.1f} (+{penetration:.1f} pts) & bearish rejection",
                            supporting_factors={
                                "level": lvl,
                                "type": "SWEEP_REJECTION",
                                "penetration": round(penetration, 2),
                                "wick_ratio": round(wick_ratio, 2),
                                "category": "LIQUIDITY_SWEEP"
                            }
                        )

            # 2. Genuine Bullish Breakout beyond Day High (CE)
            body = abs(curr_3m["close"] - curr_3m["open"])
            if prev_3m["close"] <= lvl and curr_3m["close"] > lvl + 2.0:
                if curr_3m["close"] > curr_3m["open"] and (body / c3_range) >= 0.55:
                    upper_wick = curr_3m["high"] - curr_3m["close"]
                    if (upper_wick / c3_range) < 0.35:
                        return SetupSignal(
                            setup_id=self.setup_id,
                            setup_name=self.name,
                            triggered=True,
                            direction="BULLISH",
                            confidence=82.0,
                            timeframe="3m",
                            entry_level=current_price,
                            invalidation_level=lvl - 4.0,
                            reason=f"Genuine breakout above Day High {lvl:.1f} with displacement",
                            supporting_factors={
                                "level": lvl,
                                "type": "GENUINE_BREAKOUT",
                                "category": "DAY_LEVEL_BREAKOUT"
                            }
                        )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No Day H/L setup", {})
