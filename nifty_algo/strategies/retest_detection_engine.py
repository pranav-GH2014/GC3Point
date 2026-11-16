import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.retest")

class RetestDetectionEngine:
    """
    Engine 2: Retest Detection Engine
    Identifies:
    - Previous day high/low (PDH/PDL) retests
    - Current day high/low (CDH/CDL) retests
    - Opening range (ORB) retests
    - VWAP retests
    - Support and Resistance retests
    - Recent swing high/low retests
    Supports both:
    1. Reversal after retest (support bounce CE / resistance rejection PE)
    2. Breakout followed by successful retest (broken level acts as new support CE / broken support acts as new resistance PE)
    """

    def __init__(self, tolerance_pts: float = 4.5):
        self.strategy_id = "ENGINE_2_RETEST"
        self.strategy_name = "Retest Detection Engine"
        self.tolerance_pts = tolerance_pts

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

        c1 = bars[-2] # prior bar (retest touch)
        c2 = bars[-1] # current bar (confirmation bounce/rejection)
        time_str = str(c2.get("date", ""))
        curr_price = float(c2["close"])

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

        # Check Support Retest (CE Candidate):
        # Either 1) Prior resistance broken, now retested as support (Breakout + Retest)
        # OR 2) Support level tested and holds with bullish candle (Support Reversal Retest)
        for lvl_name, lvl_val in levels.items():
            # Support touch: prior bar low or current bar low touched within tolerance near level
            retested_as_support = (c1["low"] <= lvl_val + self.tolerance_pts) and (c1["low"] >= lvl_val - self.tolerance_pts or c2["low"] <= lvl_val + self.tolerance_pts)
            
            if retested_as_support and curr_price > lvl_val:
                # Confirming bullish reaction: current candle closes green and above prior bar high or level
                is_bullish_reaction = (c2["close"] > c2["open"]) and (curr_price >= c1["close"] or curr_price > lvl_val + 1.0)
                if is_bullish_reaction:
                    score = 80.0
                    if "ORB" in lvl_name or "PDH" in lvl_name:
                        score += 5.0
                    if indicators.get("ema_bullish") or curr_price > float(indicators.get("ema8", 0)):
                        score += 5.0

                    sl_dist = max(3.0, min(8.0, curr_price - lvl_val + 2.0))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="CE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Successful retest of {lvl_name} ({lvl_val:.1f}) with bullish reaction",
                        confidence=min(95.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "retested_level": lvl_name,
                            "level_price": lvl_val,
                            "bounce_low": min(c1["low"], c2["low"])
                        }
                    )

            # Resistance touch: prior bar high or current bar high touched within tolerance near level
            retested_as_resistance = (c1["high"] >= lvl_val - self.tolerance_pts) and (c1["high"] <= lvl_val + self.tolerance_pts or c2["high"] >= lvl_val - self.tolerance_pts)
            
            if retested_as_resistance and curr_price < lvl_val:
                # Confirming bearish reaction: current candle closes red and below prior bar low or level
                is_bearish_reaction = (c2["close"] < c2["open"]) and (curr_price <= c1["close"] or curr_price < lvl_val - 1.0)
                if is_bearish_reaction:
                    score = 80.0
                    if "ORB" in lvl_name or "PDL" in lvl_name:
                        score += 5.0
                    if indicators.get("ema_bearish") or curr_price < float(indicators.get("ema8", 999999)):
                        score += 5.0

                    sl_dist = max(3.0, min(8.0, lvl_val - curr_price + 2.0))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="PE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Successful retest of {lvl_name} ({lvl_val:.1f}) with bearish reaction",
                        confidence=min(95.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "retested_level": lvl_name,
                            "level_price": lvl_val,
                            "rejection_high": max(c1["high"], c2["high"])
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
            rejection_reason="No touch or reaction at watched levels"
        )
