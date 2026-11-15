from typing import Dict, Any
from .base_setup import BaseSetup, SetupSignal
from ..liquidity.liquidity_engine import LiquidityEngine

class LiquiditySweepReversalSetup(BaseSetup):
    """
    Setup 2: Liquidity Sweep Followed by Reversal
    - BSL Sweep: High crosses key resistance/swing high, rejected with wick >= 35%, closes below. Entry: Bearish (Buy PE).
    - SSL Sweep: Low crosses key support/swing low, rejected with wick >= 35%, closes above. Entry: Bullish (Buy CE).
    """

    def __init__(self):
        super().__init__("SETUP_2_LIQUIDITY_SWEEP_REVERSAL", "Liquidity Sweep Followed by Reversal", "3m")

    def evaluate(self, candles_1m: list, candles_3m: list, structure: Dict[str, Any], indicators: Dict[str, Any]) -> SetupSignal:
        if not candles_3m or not structure:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Insufficient bars", {})

        curr_candle = candles_3m[-1]
        last_swing_high = structure.get("last_swing_high", 0.0)
        last_swing_low = structure.get("last_swing_low", 0.0)

        # 1. Check BSL Sweep (Bearish reversal)
        bsl_res = LiquidityEngine.detect_liquidity_sweep(curr_candle, last_swing_high, "BSL")
        if bsl_res["is_sweep"]:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BEARISH",
                confidence=90.0,
                timeframe=self.timeframe,
                entry_level=curr_candle["close"],
                invalidation_level=curr_candle["high"] + 2.0,
                reason=f"BSL Liquidity sweep at {last_swing_high:.2f} with {bsl_res['wick_ratio']*100:.0f}% rejection wick",
                supporting_factors={"sweep_type": "BSL", "wick_ratio": bsl_res["wick_ratio"]}
            )

        # 2. Check SSL Sweep (Bullish reversal)
        ssl_res = LiquidityEngine.detect_liquidity_sweep(curr_candle, last_swing_low, "SSL")
        if ssl_res["is_sweep"]:
            return SetupSignal(
                setup_id=self.setup_id,
                setup_name=self.name,
                triggered=True,
                direction="BULLISH",
                confidence=90.0,
                timeframe=self.timeframe,
                entry_level=curr_candle["close"],
                invalidation_level=curr_candle["low"] - 2.0,
                reason=f"SSL Liquidity sweep at {last_swing_low:.2f} with {ssl_res['wick_ratio']*100:.0f}% rejection wick",
                supporting_factors={"sweep_type": "SSL", "wick_ratio": ssl_res["wick_ratio"]}
            )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No liquidity sweep detected", {})
