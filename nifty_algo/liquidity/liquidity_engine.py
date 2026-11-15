import pandas as pd
from typing import Dict, Any, Optional

class LiquidityEngine:
    """
    Detects institutional liquidity sweeps and false breakouts:
    - BSL (Buy-Side Liquidity) Sweep: Price breaches swing high / PDH but closes back inside range with rejection wick
    - SSL (Sell-Side Liquidity) Sweep: Price breaches swing low / PDL but closes back inside range with rejection wick
    - False Breakout Veto: Rejection of level with low volume or swift reclaim
    """

    @staticmethod
    def detect_liquidity_sweep(candle: Dict[str, Any], level: float, sweep_type: str = "BSL") -> Dict[str, Any]:
        """
        sweep_type 'BSL': breaches level upwards, but closes below level.
        sweep_type 'SSL': breaches level downwards, but closes above level.
        """
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]
        open_p = candle["open"]
        candle_range = high - low

        if candle_range <= 0:
            return {"is_sweep": False}

        if sweep_type == "BSL":
            # High probed above level, but closed back below it
            breached = high > level
            closed_below = close < level
            upper_wick = high - max(open_p, close)
            wick_ratio = upper_wick / candle_range

            if breached and closed_below and wick_ratio >= 0.35:
                return {
                    "is_sweep": True,
                    "type": "BSL_SWEEP",
                    "bias": "BEARISH",  # Sweep of highs leads to bearish reversal (BUY PE)
                    "wick_ratio": round(wick_ratio, 2),
                    "sweep_depth": round(high - level, 2)
                }

        elif sweep_type == "SSL":
            # Low probed below level, but closed back above it
            breached = low < level
            closed_above = close > level
            lower_wick = min(open_p, close) - low
            wick_ratio = lower_wick / candle_range

            if breached and closed_above and wick_ratio >= 0.35:
                return {
                    "is_sweep": True,
                    "type": "SSL_SWEEP",
                    "bias": "BULLISH",  # Sweep of lows leads to bullish reversal (BUY CE)
                    "wick_ratio": round(wick_ratio, 2),
                    "sweep_depth": round(level - low, 2)
                }

        return {"is_sweep": False}

    @staticmethod
    def detect_false_breakout(df: pd.DataFrame, level: float, breakout_dir: str) -> bool:
        """
        Validates if breakout failed:
        If breakout candle closed beyond level, but subsequent candle immediately closed back inside.
        """
        if len(df) < 2:
            return False

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        if breakout_dir == "UP":
            # Prev broke above, curr collapsed back below
            if prev["close"] > level and curr["close"] < level:
                return True
        elif breakout_dir == "DOWN":
            # Prev broke below, curr reclaimed above
            if prev["close"] < level and curr["close"] > level:
                return True

        return False
