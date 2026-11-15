from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal
from ..patterns.candlestick import CandlestickPatternRecognizer

class SupportResistanceEngine(BaseSetup):
    """
    Setup A: Support and Resistance Setup (Section 2A)
    - CE: Established support + bullish rejection / hammer / bullish engulfing + price response.
    - PE: Established resistance + bearish rejection / shooting star / bearish engulfing + price response.
    """

    def __init__(self, proximity_threshold_pts: float = 8.0):
        super().__init__("SETUP_SUPPORT_RESISTANCE", "Support and Resistance", "1m/3m")
        self.proximity_threshold_pts = proximity_threshold_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        if not candles_3m or not candles_1m or not structure:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing data", {})

        curr_3m = candles_3m[-1]
        curr_1m = candles_1m[-1]
        current_price = curr_1m["close"]

        # Support levels: Last swing low, CDL, PDL, ORB Low
        supports = [s for s in [
            structure.get("last_swing_low"),
            structure.get("cdl"),
            structure.get("pdl"),
            structure.get("orb_low")
        ] if s is not None and s <= current_price + self.proximity_threshold_pts]

        # Resistance levels: Last swing high, CDH, PDH, ORB High
        resistances = [r for r in [
            structure.get("last_swing_high"),
            structure.get("cdh"),
            structure.get("pdh"),
            structure.get("orb_high")
        ] if r is not None and r >= current_price - self.proximity_threshold_pts]

        pat_3m = CandlestickPatternRecognizer.identify_patterns(candles_3m)
        pat_1m = CandlestickPatternRecognizer.identify_patterns(candles_1m)

        c3_range = curr_3m["high"] - curr_3m["low"]
        c1_range = curr_1m["high"] - curr_1m["low"]

        # 1. Bullish Support Response (CE Signal)
        if supports:
            nearest_sup = max(supports)
            dist_to_sup = abs(curr_3m["low"] - nearest_sup)
            if dist_to_sup <= self.proximity_threshold_pts:
                # Check for hammer, bullish engulfing, or lower rejection pin-bar
                lower_wick_3m = (min(curr_3m["open"], curr_3m["close"]) - curr_3m["low"]) if c3_range > 0 else 0
                is_pin_bounce = c3_range > 0 and (lower_wick_3m / c3_range) >= 0.35 and curr_3m["close"] > curr_3m["open"]
                is_engulf_or_hammer = pat_3m["pattern"] in ("HAMMER", "BULLISH_ENGULFING") or pat_1m["pattern"] in ("HAMMER", "BULLISH_ENGULFING")
                
                # Price response: price closes above support and shows positive momentum
                price_confirmed = curr_1m["close"] > nearest_sup and curr_1m["close"] > curr_1m["open"]

                if (is_pin_bounce or is_engulf_or_hammer) and price_confirmed:
                    conf = 85.0 if (is_engulf_or_hammer and is_pin_bounce) else 80.0
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BULLISH",
                        confidence=conf,
                        timeframe="3m+1m",
                        entry_level=current_price,
                        invalidation_level=nearest_sup - 4.0,
                        reason=f"Bullish rejection off established support {nearest_sup:.1f} ({pat_3m.get('pattern') or 'PinBar'})",
                        supporting_factors={
                            "support_level": nearest_sup,
                            "pattern_3m": pat_3m.get("pattern"),
                            "pattern_1m": pat_1m.get("pattern"),
                            "dist_to_level": round(dist_to_sup, 2),
                            "category": "SUPPORT_RESISTANCE"
                        }
                    )

        # 2. Bearish Resistance Response (PE Signal)
        if resistances:
            nearest_res = min(resistances)
            dist_to_res = abs(curr_3m["high"] - nearest_res)
            if dist_to_res <= self.proximity_threshold_pts:
                upper_wick_3m = (curr_3m["high"] - max(curr_3m["open"], curr_3m["close"])) if c3_range > 0 else 0
                is_pin_reject = c3_range > 0 and (upper_wick_3m / c3_range) >= 0.35 and curr_3m["close"] < curr_3m["open"]
                is_engulf_or_star = pat_3m["pattern"] in ("SHOOTING_STAR", "BEARISH_ENGULFING") or pat_1m["pattern"] in ("SHOOTING_STAR", "BEARISH_ENGULFING")

                # Price response: price closes below resistance and shows negative momentum
                price_confirmed = curr_1m["close"] < nearest_res and curr_1m["close"] < curr_1m["open"]

                if (is_pin_reject or is_engulf_or_star) and price_confirmed:
                    conf = 85.0 if (is_engulf_or_star and is_pin_reject) else 80.0
                    return SetupSignal(
                        setup_id=self.setup_id,
                        setup_name=self.name,
                        triggered=True,
                        direction="BEARISH",
                        confidence=conf,
                        timeframe="3m+1m",
                        entry_level=current_price,
                        invalidation_level=nearest_res + 4.0,
                        reason=f"Bearish rejection off established resistance {nearest_res:.1f} ({pat_3m.get('pattern') or 'PinBar'})",
                        supporting_factors={
                            "resistance_level": nearest_res,
                            "pattern_3m": pat_3m.get("pattern"),
                            "pattern_1m": pat_1m.get("pattern"),
                            "dist_to_level": round(dist_to_res, 2),
                            "category": "SUPPORT_RESISTANCE"
                        }
                    )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No S/R setup", {})
