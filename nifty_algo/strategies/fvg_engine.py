from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal

class FVGEngine(BaseSetup):
    """
    Setup D: Fair Value Gap (FVG) Setup (Section 2D)
    Detects 3-candle imbalances:
    - Bullish FVG: c3['low'] > c1['high'] with middle candle displacement -> BUY CE.
    - Bearish FVG: c3['high'] < c1['low'] with middle candle displacement -> BUY PE.
    - Immediate execution without waiting for a retest when displacement & price trigger confirm.
    """

    def __init__(self, min_gap_pts: float = 2.0, timeframe: str = "1m"):
        super().__init__("SETUP_FVG", "Fair Value Gap (FVG)", timeframe)
        self.min_gap_pts = min_gap_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        candles = candles_1m if self.timeframe == "1m" else candles_3m
        if len(candles) < 3:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]
        current_price = c3["close"]

        c2_body = abs(c2["close"] - c2["open"])
        c2_range = c2["high"] - c2["low"]
        c2_displacement = (c2_body / c2_range) if c2_range > 0 else 0

        # 1. Bullish FVG
        # Third candle low is strictly above first candle high
        if c3["low"] > c1["high"]:
            gap_size = c3["low"] - c1["high"]
            # Middle candle must be a strong upward expansion bar
            if gap_size >= self.min_gap_pts and c2["close"] > c2["open"] and c2_displacement >= 0.55:
                # Confirming price action: c3 holds above gap with green/steady close
                if c3["close"] > c1["high"] and c3["close"] >= c3["open"]:
                    conf = 85.0 if gap_size >= 4.0 else 80.0
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BULLISH",
                        confidence=conf,
                        timeframe=self.timeframe,
                        entry_level=current_price,
                        invalidation_level=c1["high"] - 2.0,
                        reason=f"Bullish 3-candle FVG (+{gap_size:.1f} pts) with displacement {c2_displacement*100:.0f}%",
                        supporting_factors={
                            "gap_size": round(gap_size, 2),
                            "c1_high": c1["high"],
                            "c3_low": c3["low"],
                            "displacement": round(c2_displacement, 2),
                            "category": "FVG"
                        }
                    )

        # 2. Bearish FVG
        # Third candle high is strictly below first candle low
        if c3["high"] < c1["low"]:
            gap_size = c1["low"] - c3["high"]
            if gap_size >= self.min_gap_pts and c2["close"] < c2["open"] and c2_displacement >= 0.55:
                if c3["close"] < c1["low"] and c3["close"] <= c3["open"]:
                    conf = 85.0 if gap_size >= 4.0 else 80.0
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BEARISH",
                        confidence=conf,
                        timeframe=self.timeframe,
                        entry_level=current_price,
                        invalidation_level=c1["low"] + 2.0,
                        reason=f"Bearish 3-candle FVG (-{gap_size:.1f} pts) with displacement {c2_displacement*100:.0f}%",
                        supporting_factors={
                            "gap_size": round(gap_size, 2),
                            "c1_low": c1["low"],
                            "c3_high": c3["high"],
                            "displacement": round(c2_displacement, 2),
                            "category": "FVG"
                        }
                    )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No FVG pattern", {})
