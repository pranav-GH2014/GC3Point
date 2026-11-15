import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

class MarketStructureEngine:
    """
    Computes key structural levels on NIFTY:
    - Previous Day High / Low (PDH / PDL)
    - Current Day High / Low (CDH / CDL)
    - Opening Range (ORB 9:15 - 9:30 AM or first 15 mins)
    - Fractal Swing Highs and Swing Lows (3-minute structure)
    - Supply / Demand Zones
    - Distance to next opposing level
    """

    def __init__(self, swing_lookback: int = 3, min_room_pts: float = 8.0):
        self.swing_lookback = swing_lookback
        self.min_room_pts = min_room_pts

    def identify_swings(self, df_3m: pd.DataFrame) -> Tuple[List[float], List[float]]:
        """Identifies recent confirmed swing highs and lows using fractal lookback."""
        if len(df_3m) < self.swing_lookback * 2 + 1:
            return [], []

        highs = df_3m["high"].values
        lows = df_3m["low"].values
        swing_highs = []
        swing_lows = []

        k = self.swing_lookback
        for i in range(k, len(df_3m) - k):
            # Swing High
            if all(highs[i] > highs[i - j] for j in range(1, k + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, k + 1)):
                swing_highs.append(float(highs[i]))

            # Swing Low
            if all(lows[i] < lows[i - j] for j in range(1, k + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, k + 1)):
                swing_lows.append(float(lows[i]))

        return swing_highs, swing_lows

    def compute_structure(
        self,
        df_1m: pd.DataFrame,
        df_3m: pd.DataFrame,
        pdh: Optional[float] = None,
        pdl: Optional[float] = None
    ) -> Dict[str, Any]:
        if df_1m.empty:
            return {}

        current_price = float(df_1m["close"].iloc[-1])
        cdh = float(df_1m["high"].max())
        cdl = float(df_1m["low"].min())

        # Opening Range (First 15 minutes: 9:15 to 9:30)
        df_orb = df_1m.iloc[:15] if len(df_1m) >= 15 else df_1m
        orb_high = float(df_orb["high"].max())
        orb_low = float(df_orb["low"].min())

        # Swings from 3-minute structure
        swing_highs, swing_lows = self.identify_swings(df_3m)
        last_swing_high = swing_highs[-1] if swing_highs else cdh
        last_swing_low = swing_lows[-1] if swing_lows else cdl

        # Resistances above current price
        all_resistances = [r for r in set(swing_highs + [cdh] + ([pdh] if pdh else []) + [orb_high]) if r > current_price]
        all_supports = [s for s in set(swing_lows + [cdl] + ([pdl] if pdl else []) + [orb_low]) if s < current_price]

        next_resistance = min(all_resistances) if all_resistances else cdh + 100.0
        next_support = max(all_supports) if all_supports else cdl - 100.0

        room_to_resistance = max(0.0, next_resistance - current_price)
        room_to_support = max(0.0, current_price - next_support)

        return {
            "current_price": current_price,
            "pdh": pdh,
            "pdl": pdl,
            "cdh": cdh,
            "cdl": cdl,
            "orb_high": orb_high,
            "orb_low": orb_low,
            "last_swing_high": last_swing_high,
            "last_swing_low": last_swing_low,
            "next_resistance": next_resistance,
            "next_support": next_support,
            "room_to_resistance": round(room_to_resistance, 2),
            "room_to_support": round(room_to_support, 2),
            "has_sufficient_room_ce": room_to_resistance >= self.min_room_pts,
            "has_sufficient_room_pe": room_to_support >= self.min_room_pts,
        }
