import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.fvg")

class FVGOpportunityEngine:
    """
    Engine 5: Fair Value Gap (FVG) Detection Engine
    Identifies:
    - Bullish FVG: 3-candle imbalance where C3 low > C1 high
    - Bearish FVG: 3-candle imbalance where C3 high < C1 low
    - Price returning to / mitigating FVG zone
    - FVG rejection (rebound in original direction)
    - Immediate FVG continuation when accompanied by strong displacement
    Allows valid FVG setups to independently generate actionable CE or PE signals.
    """

    def __init__(self, min_gap_pts: float = 3.0):
        self.strategy_id = "ENGINE_5_FVG"
        self.strategy_name = "FVG Detection Engine"
        self.min_gap_pts = min_gap_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> OpportunitySignal:
        bars = candles_3m if (candles_3m and len(candles_3m) >= 6) else candles_1m
        if len(bars) < 6:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="Insufficient bars",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Insufficient data (<6 bars)"
            )

        curr_bar = bars[-1]
        time_str = str(curr_bar.get("date", ""))
        curr_price = float(curr_bar["close"])

        # Check the recent 3-candle windows: (c_prev2, c_prev1, curr_bar) and prior
        # Window 1: Immediate FVG formation on the last 3 bars (bars -3, -2, -1)
        c1, c2, c3 = bars[-3], bars[-2], bars[-1]

        # 1. Bullish FVG: c3 low strictly above c1 high
        bull_gap = float(c3["low"]) - float(c1["high"])
        if bull_gap >= self.min_gap_pts and (c2["close"] > c2["open"]):
            # Strong bullish displacement in middle candle (c2)
            c2_range = c2["high"] - c2["low"]
            c2_body = abs(c2["close"] - c2["open"])
            displacement_ok = (c2_range > 0) and (c2_body / c2_range >= 0.55)

            if displacement_ok and c3["close"] > c2["open"]:
                score = 80.0
                if bull_gap >= 5.0:
                    score += 8.0
                if curr_price > float(indicators.get("vwap", 0.0)):
                    score += 5.0

                sl_dist = max(3.0, min(8.0, curr_price - float(c1["high"]) + 1.0))

                return OpportunitySignal(
                    strategy_id=self.strategy_id,
                    strategy_name=self.strategy_name,
                    triggered=True,
                    direction="CE",
                    timestamp=time_str,
                    reference_price=curr_price,
                    entry_condition=f"Bullish FVG Imbalance: Gap {bull_gap:.1f} pts ({c1['high']:.1f} to {c3['low']:.1f})",
                    confidence=min(95.0, score),
                    stop_loss_pts=sl_dist,
                    target_pts=3.0,
                    supporting_metadata={
                        "fvg_type": "BULLISH_IMBALANCE",
                        "gap_points": round(bull_gap, 2),
                        "gap_low": float(c1["high"]),
                        "gap_high": float(c3["low"])
                    }
                )

        # 2. Bearish FVG: c3 high strictly below c1 low
        bear_gap = float(c1["low"]) - float(c3["high"])
        if bear_gap >= self.min_gap_pts and (c2["close"] < c2["open"]):
            c2_range = c2["high"] - c2["low"]
            c2_body = abs(c2["close"] - c2["open"])
            displacement_ok = (c2_range > 0) and (c2_body / c2_range >= 0.55)

            if displacement_ok and c3["close"] < c2["open"]:
                score = 80.0
                if bear_gap >= 5.0:
                    score += 8.0
                if curr_price < float(indicators.get("vwap", 999999.0)):
                    score += 5.0

                sl_dist = max(3.0, min(8.0, float(c1["low"]) - curr_price + 1.0))

                return OpportunitySignal(
                    strategy_id=self.strategy_id,
                    strategy_name=self.strategy_name,
                    triggered=True,
                    direction="PE",
                    timestamp=time_str,
                    reference_price=curr_price,
                    entry_condition=f"Bearish FVG Imbalance: Gap {bear_gap:.1f} pts ({c3['high']:.1f} to {c1['low']:.1f})",
                    confidence=min(95.0, score),
                    stop_loss_pts=sl_dist,
                    target_pts=3.0,
                    supporting_metadata={
                        "fvg_type": "BEARISH_IMBALANCE",
                        "gap_points": round(bear_gap, 2),
                        "gap_low": float(c3["high"]),
                        "gap_high": float(c1["low"])
                    }
                )

        # Window 2: Check FVG Mitigation & Rejection from recent prior gap
        if len(candles_1m) >= 6:
            p_c1, p_c2, p_c3 = candles_1m[-5], candles_1m[-4], candles_1m[-3]
            p_bull_gap = float(p_c3["low"]) - float(p_c1["high"])
            if p_bull_gap >= self.min_gap_pts:
                # Prior bullish gap: curr_bar or prev_bar tapped into the gap (between p_c1 high and p_c3 low) and bounced
                if (curr_bar["low"] <= p_c3["low"] + 1.5) and (curr_price > p_c1["high"]) and (curr_price > curr_bar["open"]):
                    sl_dist = max(3.0, min(8.0, curr_price - float(p_c1["high"]) + 1.0))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="CE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Bullish FVG Rejection: Mitigated gap {p_bull_gap:.1f} pts with green bounce",
                        confidence=85.0,
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={"fvg_type": "BULLISH_REJECTION", "gap_points": round(p_bull_gap, 2)}
                    )

            p_bear_gap = float(p_c1["low"]) - float(p_c3["high"])
            if p_bear_gap >= self.min_gap_pts:
                # Prior bearish gap: tapped into gap and rejected downwards
                if (curr_bar["high"] >= p_c3["high"] - 1.5) and (curr_price < p_c1["low"]) and (curr_price < curr_bar["open"]):
                    sl_dist = max(3.0, min(8.0, float(p_c1["low"]) - curr_price + 1.0))
                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="PE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"Bearish FVG Rejection: Mitigated gap {p_bear_gap:.1f} pts with red rejection",
                        confidence=85.0,
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={"fvg_type": "BEARISH_REJECTION", "gap_points": round(p_bear_gap, 2)}
                    )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No FVG imbalance or rejection",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No qualifying 3-candle imbalance"
        )
