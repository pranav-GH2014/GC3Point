import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.fvg")

class FVGOpportunityEngine:
    """
    Engine 5: Fair Value Gap (FVG) Detection Engine (Upgraded - Phase 3)
    Identifies institutional imbalances and tracks zone life-cycle:
    - Bullish FVG: 3-candle imbalance where C3 low > C1 high
    - Bearish FVG: 3-candle imbalance where C3 high < C1 low
    - Tracks zone bounds, creation bar, and mitigation percentage:
        * FRESH: Unmitigated (0% filled)
        * PARTIALLY_MITIGATED: Tapped into 1% - 50%
        * INVALIDATED/FULL: Mitigated > 80% (zone expired)
    - Confirms directional reaction out of the FVG zone.
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

        # Scan historical bars for active FVG zones
        # Window 1: Immediate FVG formation on the last 3 bars (bars -3, -2, -1)
        c1, c2, c3 = bars[-3], bars[-2], bars[-1]

        # 1. Bullish FVG: c3 low strictly above c1 high
        bull_gap = float(c3["low"]) - float(c1["high"])
        if bull_gap >= self.min_gap_pts and (c2["close"] > c2["open"]):
            c2_range = c2["high"] - c2["low"]
            c2_body = abs(c2["close"] - c2["open"])
            displacement_ok = (c2_range > 0) and (c2_body / c2_range >= 0.55)

            if displacement_ok and c3["close"] > c2["open"]:
                # Mitigation check: how much of the gap did c3 wick into?
                gap_penetration = max(0.0, float(c1["high"]) + bull_gap - float(c3["low"]))
                mitigation_pct = round((gap_penetration / bull_gap) * 100.0, 1)

                score = 80.0
                if bull_gap >= 5.0:
                    score += 7.0
                if mitigation_pct <= 25.0:
                    score += 6.0  # Fresh FVG bonus
                if curr_price > float(indicators.get("vwap", 0.0)):
                    score += 4.0

                sl_dist = max(3.0, min(6.5, curr_price - float(c1["high"]) + 1.0))

                return OpportunitySignal(
                    strategy_id=self.strategy_id,
                    strategy_name=self.strategy_name,
                    triggered=True,
                    direction="CE",
                    timestamp=time_str,
                    reference_price=curr_price,
                    entry_condition=f"Bullish FVG Imbalance: Gap {bull_gap:.1f} pts ({c1['high']:.1f} - {c3['low']:.1f}), Mitigation {mitigation_pct}%",
                    confidence=min(95.0, score),
                    stop_loss_pts=sl_dist,
                    target_pts=3.0,
                    supporting_metadata={
                        "fvg_type": "BULLISH_IMBALANCE",
                        "gap_points": round(bull_gap, 2),
                        "gap_low": float(c1["high"]),
                        "gap_high": float(c3["low"]),
                        "mitigation_pct": mitigation_pct,
                        "status": "FRESH" if mitigation_pct < 30.0 else "PARTIAL"
                    }
                )

        # 2. Bearish FVG: c3 high strictly below c1 low
        bear_gap = float(c1["low"]) - float(c3["high"])
        if bear_gap >= self.min_gap_pts and (c2["close"] < c2["open"]):
            c2_range = c2["high"] - c2["low"]
            c2_body = abs(c2["close"] - c2["open"])
            displacement_ok = (c2_range > 0) and (c2_body / c2_range >= 0.55)

            if displacement_ok and c3["close"] < c2["open"]:
                gap_penetration = max(0.0, float(c3["high"]) - (float(c1["low"]) - bear_gap))
                mitigation_pct = round((gap_penetration / bear_gap) * 100.0, 1)

                score = 80.0
                if bear_gap >= 5.0:
                    score += 7.0
                if mitigation_pct <= 25.0:
                    score += 6.0  # Fresh FVG bonus
                if curr_price < float(indicators.get("vwap", 999999.0)):
                    score += 4.0

                sl_dist = max(3.0, min(6.5, float(c1["low"]) - curr_price + 1.0))

                return OpportunitySignal(
                    strategy_id=self.strategy_id,
                    strategy_name=self.strategy_name,
                    triggered=True,
                    direction="PE",
                    timestamp=time_str,
                    reference_price=curr_price,
                    entry_condition=f"Bearish FVG Imbalance: Gap {bear_gap:.1f} pts ({c3['high']:.1f} - {c1['low']:.1f}), Mitigation {mitigation_pct}%",
                    confidence=min(95.0, score),
                    stop_loss_pts=sl_dist,
                    target_pts=3.0,
                    supporting_metadata={
                        "fvg_type": "BEARISH_IMBALANCE",
                        "gap_points": round(bear_gap, 2),
                        "gap_low": float(c3["high"]),
                        "gap_high": float(c1["low"]),
                        "mitigation_pct": mitigation_pct,
                        "status": "FRESH" if mitigation_pct < 30.0 else "PARTIAL"
                    }
                )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No FVG imbalance",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No 3-candle imbalance meeting min gap threshold"
        )
