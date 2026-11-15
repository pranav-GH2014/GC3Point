import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class TechnicalIndicators:
    """
    Computes EMA 8, EMA 21, intraday VWAP, and ADX(14).
    Uses vectorized NumPy/Pandas calculations.
    """

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """
        Computes intraday VWAP = sum(Price * Volume) / sum(Volume).
        Resets at start of trading day.
        When volume is 0 or unavailable (e.g. NIFTY 50 cash index spot),
        falls back to intraday cumulative typical price average (intraday TWAP/VWAP proxy).
        """
        if df.empty or "close" not in df.columns:
            return pd.Series(dtype=float)

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        has_volume = "volume" in df.columns and (df["volume"] > 0).any()
        
        # Group by date if available, or cumulative sum
        if "date" in df.columns:
            dates = pd.to_datetime(df["date"]).dt.date
            if has_volume:
                pv = typical_price * df["volume"]
                cum_pv = pv.groupby(dates).cumsum()
                cum_vol = df["volume"].groupby(dates).cumsum()
                vwap = cum_pv / cum_vol.replace(0, np.nan)
                return vwap.ffill()
            else:
                cum_tp = typical_price.groupby(dates).cumsum()
                cum_count = typical_price.groupby(dates).cumcount() + 1
                return cum_tp / cum_count
        else:
            if has_volume:
                pv = typical_price * df["volume"]
                cum_pv = pv.cumsum()
                cum_vol = df["volume"].cumsum()
                vwap = cum_pv / cum_vol.replace(0, np.nan)
                return vwap.ffill()
            else:
                cum_tp = typical_price.cumsum()
                cum_count = pd.Series(range(1, len(df) + 1), index=df.index)
                return cum_tp / cum_count

    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Computes Average Directional Index (ADX 14) with +DI and -DI.
        """
        if len(df) < period + 1:
            return pd.DataFrame({"adx": [np.nan] * len(df), "plus_di": [np.nan] * len(df), "minus_di": [np.nan] * len(df)})

        high = df["high"]
        low = df["low"]
        close = df["close"]

        # 1. True Range (TR)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # 2. Directional Movement (+DM, -DM)
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_dm_s = pd.Series(plus_dm, index=df.index)
        minus_dm_s = pd.Series(minus_dm, index=df.index)

        # Wilder's Smoothing
        alpha = 1.0 / period
        atr = tr.ewm(alpha=alpha, adjust=False).mean()
        smooth_plus_dm = plus_dm_s.ewm(alpha=alpha, adjust=False).mean()
        smooth_minus_dm = minus_dm_s.ewm(alpha=alpha, adjust=False).mean()

        plus_di = 100 * (smooth_plus_dm / atr.replace(0, np.nan))
        minus_di = 100 * (smooth_minus_dm / atr.replace(0, np.nan))

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.ewm(alpha=alpha, adjust=False).mean()

        return pd.DataFrame({
            "adx": adx.fillna(0.0),
            "plus_di": plus_di.fillna(0.0),
            "minus_di": minus_di.fillna(0.0)
        })

    @classmethod
    def analyze_indicators(cls, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyzes EMA 8/21 alignment, VWAP relative position, and ADX strength.
        """
        if len(df) < 22:
            return {
                "ema8": None,
                "ema21": None,
                "vwap": None,
                "adx": None,
                "ema_bullish": False,
                "ema_bearish": False,
                "price_above_vwap": False,
                "price_below_vwap": False,
                "adx_regime": "WEAK",
            }

        close = df["close"]
        ema8 = cls.calculate_ema(close, 8).iloc[-1]
        ema21 = cls.calculate_ema(close, 21).iloc[-1]
        vwap_series = cls.calculate_vwap(df)
        vwap = vwap_series.iloc[-1] if not vwap_series.empty else close.iloc[-1]
        adx_df = cls.calculate_adx(df, 14)
        current_adx = adx_df["adx"].iloc[-1]
        current_price = close.iloc[-1]

        # ADX classification per Prompt Section 8:
        # Below 18: Weak/sideways
        # 18-25: Moderate trend
        # Above 25: Stronger trend
        if current_adx < 18.0:
            regime = "WEAK_SIDEWAYS"
        elif current_adx <= 25.0:
            regime = "MODERATE_TREND"
        else:
            regime = "STRONG_TREND"

        return {
            "current_price": float(current_price),
            "ema8": round(float(ema8), 2),
            "ema21": round(float(ema21), 2),
            "vwap": round(float(vwap), 2),
            "adx": round(float(current_adx), 2),
            "ema_bullish": ema8 > ema21,
            "ema_bearish": ema8 < ema21,
            "price_above_vwap": current_price > vwap,
            "price_below_vwap": current_price < vwap,
            "adx_regime": regime,
        }
