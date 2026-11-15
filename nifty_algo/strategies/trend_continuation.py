from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal

class TrendContinuationSetup(BaseSetup):
    """
    Setup 5: Trend Continuation
    - Pullback in established trend (EMA 8/21 aligned, ADX >= 18)
    - Bullish: Pullback to EMA 8 or EMA 21, candle closes green back in trend direction
    - Bearish: Rally into EMA 8 or EMA 21, candle closes red back in trend direction
    """

    def __init__(self):
        super().__init__("SETUP_5_TREND_CONTINUATION", "Trend Continuation", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if not candles_3m or not indicators.get("ema8") or not indicators.get("ema21"):
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing data", {})

        curr = candles_3m[-1]
        ema8 = indicators["ema8"]
        ema21 = indicators["ema21"]
        adx_regime = indicators.get("adx_regime", "WEAK_SIDEWAYS")

        # Must have at least moderate trend (ADX >= 18)
        if adx_regime == "WEAK_SIDEWAYS":
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "ADX < 18 (Sideways)", {})

        # Bullish Continuation: bounce off EMA 8 or EMA 21
        bullish_bounce = (curr["low"] <= ema8 + 1.5 and curr["close"] > ema8 and curr["close"] > curr["open"]) or \
                         (curr["low"] <= ema21 + 1.5 and curr["close"] > ema21 and curr["close"] > curr["open"])
        if ema8 > ema21 and bullish_bounce:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BULLISH",
                confidence=82.0,
                timeframe=self.timeframe,
                entry_level=curr["close"],
                invalidation_level=ema21 - 3.0,
                reason=f"Bullish trend continuation bounce off EMA ({ema8:.2f}/{ema21:.2f}) with ADX={indicators.get('adx')}",
                supporting_factors={"ema8": ema8, "ema21": ema21, "adx": indicators.get("adx")}
            )

        # Bearish Continuation: rejection off EMA 8 or EMA 21
        bearish_rejection = (curr["high"] >= ema8 - 1.5 and curr["close"] < ema8 and curr["close"] < curr["open"]) or \
                            (curr["high"] >= ema21 - 1.5 and curr["close"] < ema21 and curr["close"] < curr["open"])
        if ema8 < ema21 and bearish_rejection:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BEARISH",
                confidence=82.0,
                timeframe=self.timeframe,
                entry_level=curr["close"],
                invalidation_level=ema21 + 3.0,
                reason=f"Bearish trend continuation rejection off EMA ({ema8:.2f}/{ema21:.2f}) with ADX={indicators.get('adx')}",
                supporting_factors={"ema8": ema8, "ema21": ema21, "adx": indicators.get("adx")}
            )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No trend continuation trigger", {})
