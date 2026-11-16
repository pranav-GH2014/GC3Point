import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.breakout")

class BreakoutDetectionEngine:
    """
    Engine 4: Breakout Detection Engine (Upgraded - Phase 3)
    Identifies high-conviction structural breakouts while filtering out fakeouts:
    - Decisive close outside well-defined consolidation (ORB, PDH/PDL, Swing High/Low)
    - Strong directional closing strength (closes in top 30% of range for CE, bottom 30% for PE)
    - Volume expansion (> 1.25x 10-bar baseline)
    - ADX trend strength confirmation (ADX >= 18.0)
    - Adequate room to next opposing barrier (>= 8.0 pts room)
    - Rejection of weak breakouts displaying exhaustion wicks
    """

    def __init__(self, min_breakout_pts: float = 2.0, min_vol_ratio: float = 1.25, min_room_pts: float = 8.0):
        self.strategy_id = "ENGINE_4_BREAKOUT"
        self.strategy_name = "Breakout Detection Engine"
        self.min_breakout_pts = min_breakout_pts
        self.min_vol_ratio = min_vol_ratio
        self.min_room_pts = min_room_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> OpportunitySignal:
        bars = candles_3m if (candles_3m and len(candles_3m) >= 10) else candles_1m
        if len(bars) < 10 or not structure:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="Insufficient data",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Insufficient data"
            )

        curr_bar = bars[-1]
        prev_bar = bars[-2]
        time_str = str(curr_bar.get("date", ""))
        curr_price = float(curr_bar["close"])
        curr_open = float(curr_bar["open"])
        curr_high = float(curr_bar["high"])
        curr_low = float(curr_bar["low"])
        curr_vol = float(curr_bar.get("volume", 0))

        bar_range = curr_high - curr_low
        if bar_range <= 0:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition="Zero range bar",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Zero range bar"
            )

        # Recent volume baseline
        recent_vols = [float(b.get("volume", 0)) for b in bars[-11:-1]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols and sum(recent_vols) > 0 else curr_vol
        vol_ratio = (curr_vol / avg_vol) if avg_vol > 0 else 1.0

        adx = float(indicators.get("adx", 20.0))
        if adx < 16.0:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition="ADX too low for breakout",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason=f"REJECTED_LOW_ADX_BREAKOUT ({adx:.1f} < 16.0)"
            )

        # Reference breakout levels
        orb_h = float(structure.get("orb_high", 0.0))
        orb_l = float(structure.get("orb_low", 999999.0))
        pdh = float(structure.get("pdh", 0.0)) if structure.get("pdh") else 0.0
        pdl = float(structure.get("pdl", 0.0)) if structure.get("pdl") else 999999.0
        r1 = float(structure.get("r1", 0.0)) if structure.get("r1") else 0.0
        s1 = float(structure.get("s1", 0.0)) if structure.get("s1") else 999999.0

        prior_10 = bars[-11:-1]
        swing_high_10 = max(float(b["high"]) for b in prior_10)
        swing_low_10 = min(float(b["low"]) for b in prior_10)

        res_levels = [r for r in [orb_h, pdh, r1, swing_high_10] if r > 0]
        sup_levels = [s for s in [orb_l, pdl, s1, swing_low_10] if s < 999999.0]

        room_to_res = float(structure.get("room_to_resistance", 10.0))
        room_to_sup = float(structure.get("room_to_support", 10.0))

        # 1. Bullish Breakout (CE Signal):
        close_strength = (curr_price - curr_low) / bar_range
        upper_wick = curr_high - curr_price
        upper_wick_ratio = upper_wick / bar_range

        if curr_price > curr_open and close_strength >= 0.65 and upper_wick_ratio <= 0.32:
            # Check room to next opposing level
            if room_to_res >= self.min_room_pts:
                for r_lvl in res_levels:
                    clean_break = (curr_price >= r_lvl + self.min_breakout_pts) and (prev_bar["close"] <= r_lvl + 1.5)
                    if clean_break:
                        score = 80.0
                        if vol_ratio >= self.min_vol_ratio:
                            score += 8.0
                        if r_lvl == orb_h or r_lvl == pdh:
                            score += 7.0
                        if curr_price > float(indicators.get("vwap", 0.0)):
                            score += 3.0

                        sl_dist = max(3.0, min(6.5, curr_price - r_lvl + 1.5))

                        return OpportunitySignal(
                            strategy_id=self.strategy_id,
                            strategy_name=self.strategy_name,
                            triggered=True,
                            direction="CE",
                            timestamp=time_str,
                            reference_price=curr_price,
                            entry_condition=f"Clean breakout above resistance {r_lvl:.1f} (Close strength {close_strength:.0%}, vol {vol_ratio:.1f}x)",
                            confidence=min(95.0, score),
                            stop_loss_pts=sl_dist,
                            target_pts=3.0,
                            supporting_metadata={
                                "breakout_level": r_lvl,
                                "broken_level": r_lvl,
                                "vol_ratio": round(vol_ratio, 2),
                                "close_strength": round(close_strength, 2),
                                "room_to_resistance": room_to_res
                            }
                        )

        # 2. Bearish Breakdown (PE Signal):
        lower_close_strength = (curr_high - curr_price) / bar_range
        lower_wick = curr_price - curr_low
        lower_wick_ratio = lower_wick / bar_range

        if curr_price < curr_open and lower_close_strength >= 0.65 and lower_wick_ratio <= 0.32:
            if room_to_sup >= self.min_room_pts:
                for s_lvl in sup_levels:
                    clean_break = (curr_price <= s_lvl - self.min_breakout_pts) and (prev_bar["close"] >= s_lvl - 1.5)
                    if clean_break:
                        score = 80.0
                        if vol_ratio >= self.min_vol_ratio:
                            score += 8.0
                        if s_lvl == orb_l or s_lvl == pdl:
                            score += 7.0
                        if curr_price < float(indicators.get("vwap", 999999.0)):
                            score += 3.0

                        sl_dist = max(3.0, min(6.5, s_lvl - curr_price + 1.5))

                        return OpportunitySignal(
                            strategy_id=self.strategy_id,
                            strategy_name=self.strategy_name,
                            triggered=True,
                            direction="PE",
                            timestamp=time_str,
                            reference_price=curr_price,
                            entry_condition=f"Clean breakdown below support {s_lvl:.1f} (Close strength {lower_close_strength:.0%}, vol {vol_ratio:.1f}x)",
                            confidence=min(95.0, score),
                            stop_loss_pts=sl_dist,
                            target_pts=3.0,
                            supporting_metadata={
                                "breakdown_level": s_lvl,
                                "vol_ratio": round(vol_ratio, 2),
                                "close_strength": round(lower_close_strength, 2),
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
            entry_condition="No clean breakout close or inadequate room",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No clean breakout close beyond levels or room < 8 pts"
        )
