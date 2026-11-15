import numpy as np
import pandas as pd
from typing import Dict, Any

class VolumeProfileAnalyzer:
    """
    Computes Point of Control (POC), Value Area High (VAH), Value Area Low (VAL),
    High-Volume Nodes (HVN), and Low-Volume Nodes (LVN) from intraday candle bars.
    """

    @staticmethod
    def calculate_profile(df: pd.DataFrame, num_bins: int = 30) -> Dict[str, Any]:
        if df.empty or len(df) < 5 or "volume" not in df.columns:
            return {
                "poc": None,
                "vah": None,
                "val": None,
                "hvn": [],
                "lvn": [],
                "value_area_pct": 0.70
            }

        price_min = df["low"].min()
        price_max = df["high"].max()
        if price_max == price_min:
            return {"poc": price_min, "vah": price_min, "val": price_min, "hvn": [], "lvn": []}

        bins = np.linspace(price_min, price_max, num_bins + 1)
        bin_volumes = np.zeros(num_bins)

        for _, row in df.iterrows():
            c_high, c_low, c_vol = row["high"], row["low"], row["volume"]
            if c_vol <= 0 or c_high == c_low:
                continue
            # Distribute candle volume across intersected bins
            intersected = np.where((bins[:-1] < c_high) & (bins[1:] > c_low))[0]
            if len(intersected) > 0:
                bin_volumes[intersected] += c_vol / len(intersected)

        bin_centers = (bins[:-1] + bins[1:]) / 2.0
        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float(bin_centers[poc_idx])

        # Value Area 70% calculation
        total_vol = np.sum(bin_volumes)
        target_vol = total_vol * 0.70
        curr_vol = bin_volumes[poc_idx]
        upper_idx, lower_idx = poc_idx, poc_idx

        while curr_vol < target_vol and (upper_idx < num_bins - 1 or lower_idx > 0):
            next_upper = bin_volumes[upper_idx + 1] if upper_idx < num_bins - 1 else 0
            next_lower = bin_volumes[lower_idx - 1] if lower_idx > 0 else 0
            if next_upper >= next_lower and upper_idx < num_bins - 1:
                upper_idx += 1
                curr_vol += next_upper
            elif lower_idx > 0:
                lower_idx -= 1
                curr_vol += next_lower
            else:
                break

        vah_price = float(bin_centers[upper_idx])
        val_price = float(bin_centers[lower_idx])

        # Nodes identification
        mean_vol = np.mean(bin_volumes)
        hvn = [float(bin_centers[i]) for i in range(num_bins) if bin_volumes[i] > mean_vol * 1.5]
        lvn = [float(bin_centers[i]) for i in range(num_bins) if bin_volumes[i] < mean_vol * 0.5]

        return {
            "poc": round(poc_price, 2),
            "vah": round(vah_price, 2),
            "val": round(val_price, 2),
            "hvn": [round(p, 2) for p in hvn[:3]],
            "lvn": [round(p, 2) for p in lvn[:3]],
        }
