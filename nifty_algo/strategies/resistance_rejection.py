from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal
from ..patterns.candlestick import CandlestickPatternRecognizer

class ResistanceRejectionSetup(BaseSetup):
    """
    Setup 8: Resistance Rejection
    - Price touches intraday resistance / supply zone / PDH.
    - Rejects with Shooting Star or Bearish Engulfing pattern.
    - Entry: Bearish (Buy PE).
    """

    def __init__(self):
        super().__init__("SETUP_8_RESISTANCE_REJECTION", "Resistance Rejection", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if len(candles_3m) < 2 or not structure.get("next_resistance"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing resistance level", {})

        curr = candles_3m[-1]
        next_resistance = structure["next_resistance"]

        # Check proximity to resistance (within 8 points)
        c_range = curr["high"] - curr["low"]
        upper_wick = (curr["high"] - max(curr["open"], curr["close"])) if c_range > 0 else 0.0
        is_pin_bar = (c_range > 0 and (upper_wick / c_range) >= 0.35 and curr["close"] < curr["open"])

        if abs(curr["high"] - next_resistance) <= 8.0:
            pattern_res = CandlestickPatternRecognizer.identify_patterns(candles_3m)
            if pattern_res["pattern"] in ("SHOOTING_STAR", "BEARISH_ENGULFING") or is_pin_bar:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=84.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=curr["high"] + 3.0,
                    reason=f"Resistance rejection near {next_resistance:.2f} (ShootingStar/PinBar)",
                    supporting_factors={"resistance_level": next_resistance, "pattern": pattern_res.get("pattern", "PIN_BAR")}
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No resistance rejection", {})
