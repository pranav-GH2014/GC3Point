from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class FVGConfirmationSetup(BaseSetup):
    """
    Setup 9: FVG-based Confirmation
    IMPORTANT RULE: Per Prompt Requirement Section 9, FVG must NEVER independently trigger an entry!
    It acts strictly as an imbalance confirmation module for other primary setups.
    """

    def __init__(self):
        super().__init__("SETUP_9_FVG_CONFIRMATION", "FVG-based Confirmation", "5m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        # Evaluate 3-candle sequence for Fair Value Gap
        if len(candles_3m) < 3:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        c1, c2, c3 = candles_3m[-3], candles_3m[-2], candles_3m[-1]

        # Bullish FVG: Low of candle 3 is higher than High of candle 1
        bullish_gap = c3["low"] - c1["high"]
        if bullish_gap > 3.0:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=False,  # STRICTLY CONFIRMATION ONLY - NEVER INDEPENDENT TRIGGER
                direction="BULLISH",
                confidence=70.0,
                timeframe=self.timeframe,
                entry_level=c3["close"],
                invalidation_level=c1["high"],
                reason=f"Bullish FVG imbalance of {bullish_gap:.2f} pts detected (Confirmation only)",
                supporting_factors={"fvg_type": "BULLISH", "gap_points": bullish_gap, "fvg_top": c3["low"], "fvg_bottom": c1["high"]}
            )

        # Bearish FVG: High of candle 3 is lower than Low of candle 1
        bearish_gap = c1["low"] - c3["high"]
        if bearish_gap > 3.0:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=False,  # STRICTLY CONFIRMATION ONLY - NEVER INDEPENDENT TRIGGER
                direction="BEARISH",
                confidence=70.0,
                timeframe=self.timeframe,
                entry_level=c3["close"],
                invalidation_level=c1["low"],
                reason=f"Bearish FVG imbalance of {bearish_gap:.2f} pts detected (Confirmation only)",
                supporting_factors={"fvg_type": "BEARISH", "gap_points": bearish_gap, "fvg_top": c1["low"], "fvg_bottom": c3["high"]}
            )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No significant FVG detected", {})
