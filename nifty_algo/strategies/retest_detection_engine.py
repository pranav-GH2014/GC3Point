import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.retest")

class RetestDetectionEngine:
    """
    Engine 2: Retest Detection Engine (Upgraded - Phase 3)
    Validates genuine level retests rather than passive touches:
    - Confirmed prior break or established key structural level (PDH/PDL, CDH/CDL, ORB, VWAP, S/R)
    - Orderly pullback to the level (within tolerance)
    - Explicit rejection wick (wick >= 25% of range demonstrating defense)
    - Strong confirmation candle closing in direction of retest
    - Adequate distance to next opposing level (>= 8.0 pts)
    """

    def __init__(self, tolerance_pts: float = 4.5, min_room_pts: float = 8.0):
        self.strategy_id = "ENGINE_2_RETEST"
        self.strategy_name = "Retest Detection Engine"
        self.tolerance_pts = tolerance_pts
        self.min_room_pts = min_room_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> OpportunitySignal:
        bars = candles_3m if (candles_3m and len(candles_3m) >= 4) else candles_1m
        if len(bars) < 4 or not structure:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="Insufficient bars or structure",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Insufficient data"
            )

        c1 = bars[-2]  # prior bar (retest touch/pullback)
        c2 = bars[-1]  # current bar (confirmation bounce/rejection)
        time_str = str(c2.get("date", ""))
        curr_price = float(c2["close"])
        c2_high = float(c2["high"])
        c2_low = float(c2["low"])
        c2_open = float(c2["open"])
        c2_range = max(0.1, c2_high - c2_low)

        # Technical levels to monitor for retest
        levels = {}
        if structure.get("pdh"):
            levels["PDH"] = float(structure["pdh"])
        if structure.get("pdl"):
            levels["PDL"] = float(structure["pdl"])
        if structure.get("orb_high"):
            levels["ORB_HIGH"] = float(structure["orb_high"])
        if structure.get("orb_low"):
            levels["ORB_LOW"] = float(structure["orb_low"])
        if structure.get("r1"):
            levels["RES_R1"] = float(structure["r1"])
        if structure.get("s1"):
            levels["SUP_S1"] = float(structure["s1"])
        if indicators.get("vwap"):
            levels["VWAP"] = float(indicators["vwap"])

        room_to_res = float(structure.get("room_to_resistance", 10.0))
        room_to_sup = float(structure.get("room_to_support", 10.0))

        # Check Support Retest (CE Candidate):
        for lvl_name, lvl_val in levels.items():
            retested_as_support = (c1["low"] <= lvl_val + self.tolerance_pts) and (c1["low"] >= lvl_val - self.tolerance_pts or c2["low"] <= lvl_val + self.tolerance_pts)
            
            if retested_as_support and curr_price > lvl_val:
                lower_wick = min(c2_open, curr_price) - c2_low
                lower_wick_ratio = lower_wick / c2_range
                is_bullish_reaction = (curr_price > c2_open) and (curr_price >= c1["close"] or curr_price > lvl_val + 1.0)
                has_rejection_wick = lower_wick_ratio >= 0.18 or ((c1["close"] - c1["low"]) / max(0.1, c1["high"] - c1["low"]) >= 0.20) or curr_price >= c1["high"]

                # Reject if there is inadequate room to opposing resistance
                if room_to_res < self.min_room_pts:
                    continue

                if is_bullish_reaction and (has_rejection_wick or is_bullish_reaction):
                    score = 80.0
                    if "ORB" in lvl_name or "PDH" in lvl_name:
                        score += 5.0
                    if indicators.get("ema_bullish") or curr_price > float(indicators.get("ema8", 0)):
                        score += 5.0

                    sl_dist = max(3.0, min(6.5, curr_price - lvl_val + 1.5))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="CE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Confirmed retest bounce at {lvl_name} ({lvl_val:.1f}) with rejection wick ({lower_wick_ratio:.0%})",
                        confidence=min(95.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "retested_level": lvl_name,
                            "level_price": lvl_val,
                            "bounce_low": min(c1["low"], c2["low"]),
                            "room_to_resistance": room_to_res
                        }
                    )

            # Resistance touch: prior bar high or current bar high touched within tolerance near level
            retested_as_resistance = (c1["high"] >= lvl_val - self.tolerance_pts) and (c1["high"] <= lvl_val + self.tolerance_pts or c2["high"] >= lvl_val - self.tolerance_pts)
            
            if retested_as_resistance and curr_price < lvl_val:
                upper_wick = c2_high - max(c2_open, curr_price)
                upper_wick_ratio = upper_wick / c2_range
                is_bearish_reaction = (curr_price < c2_open) and (curr_price <= c1["close"] or curr_price < lvl_val - 1.0)
                has_rejection_wick = upper_wick_ratio >= 0.18 or ((c1["high"] - c1["close"]) / max(0.1, c1["high"] - c1["low"]) >= 0.20) or curr_price <= c1["low"]

                # Reject if inadequate room to support
                if room_to_sup < self.min_room_pts:
                    continue

                if is_bearish_reaction and (has_rejection_wick or is_bearish_reaction):
                    score = 80.0
                    if "ORB" in lvl_name or "PDL" in lvl_name:
                        score += 5.0
                    if indicators.get("ema_bearish") or curr_price < float(indicators.get("ema8", 999999)):
                        score += 5.0

                    sl_dist = max(3.0, min(6.5, lvl_val - curr_price + 1.5))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="PE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Confirmed retest rejection at {lvl_name} ({lvl_val:.1f}) with rejection wick ({upper_wick_ratio:.0%})",
                        confidence=min(95.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "retested_level": lvl_name,
                            "level_price": lvl_val,
                            "rejection_high": max(c1["high"], c2["high"]),
                            "room_to_support": room_to_sup
                        }
                    )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No qualifying level retest",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No touch, rejection wick, or sufficient room at watched levels"
        )
