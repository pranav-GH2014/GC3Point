from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal
from ..patterns.candlestick import CandlestickPatternRecognizer

class SupportReversalSetup(BaseSetup):
    """
    Setup 7: Support Reversal
    - Price touches intraday support / demand zone / PDL.
    - Reverses with Bullish Hammer or Bullish Engulfing pattern.
    - Entry: Bullish (Buy CE).
    """

    def __init__(self):
        super().__init__("SETUP_7_SUPPORT_REVERSAL", "Support Reversal", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if len(candles_3m) < 2 or not structure.get("next_support"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing support level", {})

        curr = candles_3m[-1]
        next_support = structure["next_support"]

        # Check proximity to support (within 8 points)
        c_range = curr["high"] - curr["low"]
        lower_wick = (min(curr["open"], curr["close"]) - curr["low"]) if c_range > 0 else 0.0
        is_pin_bar = (c_range > 0 and (lower_wick / c_range) >= 0.35 and curr["close"] > curr["open"])

        if abs(curr["low"] - next_support) <= 8.0:
            pattern_res = CandlestickPatternRecognizer.identify_patterns(candles_3m)
            if pattern_res["pattern"] in ("HAMMER", "BULLISH_ENGULFING") or is_pin_bar:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=84.0,
                    timeframe=self.timeframe,
                    entry_level=curr["close"],
                    invalidation_level=curr["low"] - 3.0,
                    reason=f"Support reversal bounce near {next_support:.2f} (PinBar/Hammer)",
                    supporting_factors={"support_level": next_support, "pattern": pattern_res.get("pattern", "PIN_BAR")}
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No support reversal", {})
