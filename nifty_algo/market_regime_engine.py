import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger("nifty_algo.regime")


class MarketRegime(str, Enum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    REVERSAL = "REVERSAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeClassification:
    regime: MarketRegime
    confidence: float  # 0.0 to 100.0
    adx: float
    adx_slope: float  # Positive = strengthening, negative = weakening
    atr: float
    atr_expansion_ratio: float  # current ATR / 20-period median ATR
    price_vs_vwap: str  # "ABOVE", "BELOW", "AT_VWAP"
    ema_15m_alignment: str  # "BULLISH", "BEARISH", "COMPRESSED"
    structure_bias: str  # "BULLISH_HH_HL", "BEARISH_LH_LL", "RANGE_BOUND"
    heavyweight_bias: str  # "BULLISH", "BEARISH", "DIVERGENT", "NEUTRAL"
    reasons: List[str] = field(default_factory=list)

    # Strategy permission flags based on regime
    allow_momentum: bool = True
    allow_breakout: bool = True
    allow_retest: bool = True
    allow_trap: bool = True
    allow_ce: bool = True
    allow_pe: bool = True


@dataclass
class MarketRegimeConfig:
    adx_trending_min: float = 22.0
    adx_sideways_max: float = 18.0
    atr_volatility_expansion_ratio: float = 1.45
    vwap_proximity_pts: float = 5.0
    ema_compression_pct: float = 0.08  # |EMA8 - EMA21| / Price <= 0.08% is compressed
    min_bars_required: int = 15


class MarketRegimeEngine:
    """
    Market Regime Classification Engine (Phase 2)
    Classifies market conditions using multi-timeframe inputs:
    - 15m / 5m EMA 8 & 21
    - 3m price action & fractal structure
    - VWAP & VWAP crossings
    - ADX & ADX slope
    - ATR & ATR expansion
    - Higher Highs / Higher Lows vs Lower Highs / Lower Lows
    - Volume expansion
    - Heavyweight alignment

    Gates strategy activation to eliminate chop losses during sideways regimes.
    """

    def __init__(self, config: Optional[MarketRegimeConfig] = None):
        self.config = config or MarketRegimeConfig()

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        if len(df) < 2:
            return pd.Series([0.0] * len(df))
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr = np.zeros(len(df))
        tr[0] = high[0] - low[0]
        for i in range(1, len(df)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
        tr_series = pd.Series(tr, index=df.index)
        return tr_series.rolling(window=period, min_periods=1).mean()

    @staticmethod
    def _compute_adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series]:
        """Returns (ADX, ADX_slope)"""
        if len(df) < period + 2:
            return pd.Series([0.0] * len(df)), pd.Series([0.0] * len(df))

        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = low.diff() * -1

        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(period, min_periods=1).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(period, min_periods=1).mean() / atr.replace(0, 1e-9))
        minus_di = 100 * (pd.Series(minus_dm).rolling(period, min_periods=1).mean() / atr.replace(0, 1e-9))

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9))
        adx = dx.rolling(period, min_periods=1).mean().fillna(0)
        slope = adx.diff().fillna(0)
        return adx, slope

    def classify_regime(
        self,
        df_3m: pd.DataFrame,
        df_1m: Optional[pd.DataFrame] = None,
        indicators: Optional[Dict[str, Any]] = None,
        structure: Optional[Dict[str, Any]] = None,
        heavyweight_eval: Optional[Any] = None,
        liquidity_sweep_detected: bool = False
    ) -> RegimeClassification:
        """
        Classifies the market into one of the 6 core regimes.
        """
        if df_3m is None or len(df_3m) < self.config.min_bars_required:
            return RegimeClassification(
                regime=MarketRegime.UNKNOWN,
                confidence=30.0,
                adx=0.0,
                adx_slope=0.0,
                atr=0.0,
                atr_expansion_ratio=1.0,
                price_vs_vwap="UNKNOWN",
                ema_15m_alignment="UNKNOWN",
                structure_bias="UNKNOWN",
                heavyweight_bias="NEUTRAL",
                reasons=["Insufficient historical bars for classification (<15 bars)"],
                allow_momentum=False,
                allow_breakout=False,
                allow_retest=False,
                allow_trap=False,
                allow_ce=False,
                allow_pe=False
            )

        df = df_3m.copy()
        current_close = float(df["close"].iloc[-1])
        reasons: List[str] = []

        # 1. ATR & Volatility Expansion
        atr_series = self._compute_atr(df, period=14)
        current_atr = float(atr_series.iloc[-1])
        baseline_atr = float(atr_series.tail(30).median()) if len(atr_series) >= 10 else current_atr
        atr_expansion = (current_atr / baseline_atr) if baseline_atr > 0 else 1.0

        # Check for abnormal candle size
        recent_candle_ranges = (df["high"] - df["low"]).tail(5)
        median_range = (df["high"] - df["low"]).tail(30).median()
        has_abnormal_candle = any(r > 2.5 * median_range for r in recent_candle_ranges) if median_range > 0 else False

        # 2. ADX & Trend Strength
        adx_series, slope_series = self._compute_adx(df, period=14)
        current_adx = float(adx_series.iloc[-1])
        adx_slope = float(slope_series.iloc[-3:].mean()) if len(slope_series) >= 3 else 0.0

        # 3. EMA 8 & 21 (from 3m and resampled 15m if available)
        ema8 = float(df["close"].ewm(span=8, adjust=False).mean().iloc[-1])
        ema21 = float(df["close"].ewm(span=21, adjust=False).mean().iloc[-1])
        ema_diff_pct = abs(ema8 - ema21) / current_close * 100.0

        # 4. VWAP
        vwap_val = None
        if indicators and "vwap" in indicators and indicators["vwap"]:
            vwap_val = float(indicators["vwap"])
        elif "volume" in df.columns and df["volume"].sum() > 0:
            tp = (df["high"] + df["low"] + df["close"]) / 3.0
            vwap_val = float((tp * df["volume"]).cumsum().iloc[-1] / df["volume"].cumsum().iloc[-1])

        if vwap_val:
            vwap_dist = current_close - vwap_val
            if abs(vwap_dist) <= self.config.vwap_proximity_pts:
                price_vs_vwap = "AT_VWAP"
            elif vwap_dist > 0:
                price_vs_vwap = "ABOVE"
            else:
                price_vs_vwap = "BELOW"
        else:
            price_vs_vwap = "UNKNOWN"

        # 5. Market Structure: Higher Highs / Lower Lows
        recent_highs = df["high"].tail(6).values
        recent_lows = df["low"].tail(6).values
        is_higher_highs = recent_highs[-1] > recent_highs[0] and recent_lows[-1] > recent_lows[0]
        is_lower_lows = recent_highs[-1] < recent_highs[0] and recent_lows[-1] < recent_lows[0]

        if is_higher_highs:
            structure_bias = "BULLISH_HH_HL"
        elif is_lower_lows:
            structure_bias = "BEARISH_LH_LL"
        else:
            structure_bias = "RANGE_BOUND"

        # 6. Heavyweight Bias
        hw_bias = "NEUTRAL"
        if heavyweight_eval:
            if getattr(heavyweight_eval, "is_full_bullish", False):
                hw_bias = "BULLISH"
            elif getattr(heavyweight_eval, "is_full_bearish", False):
                hw_bias = "BEARISH"
            elif getattr(heavyweight_eval, "is_divergent", False):
                hw_bias = "DIVERGENT"

        # 7. Classification Logic

        # RULE A: High Volatility
        if atr_expansion >= self.config.atr_volatility_expansion_ratio or has_abnormal_candle:
            reasons.append(f"ATR expanded {atr_expansion:.2f}x above baseline")
            if has_abnormal_candle:
                reasons.append("Abnormally large candles detected (>2.5x median)")
            return RegimeClassification(
                regime=MarketRegime.HIGH_VOLATILITY,
                confidence=85.0,
                adx=current_adx,
                adx_slope=adx_slope,
                atr=current_atr,
                atr_expansion_ratio=atr_expansion,
                price_vs_vwap=price_vs_vwap,
                ema_15m_alignment="VOLATILE",
                structure_bias=structure_bias,
                heavyweight_bias=hw_bias,
                reasons=reasons,
                allow_momentum=True,  # Fast moves possible but requires high confirmation
                allow_breakout=False, # Breakouts in high volatility often whip
                allow_retest=True,
                allow_trap=True,
                allow_ce=True,
                allow_pe=True
            )

        # RULE B: Reversal Regime (Confirmed Liquidity Sweep + Structure Rejection)
        if liquidity_sweep_detected:
            reasons.append("Confirmed liquidity sweep / retail trap observed at key structural level")
            return RegimeClassification(
                regime=MarketRegime.REVERSAL,
                confidence=80.0,
                adx=current_adx,
                adx_slope=adx_slope,
                atr=current_atr,
                atr_expansion_ratio=atr_expansion,
                price_vs_vwap=price_vs_vwap,
                ema_15m_alignment="REVERSAL",
                structure_bias=structure_bias,
                heavyweight_bias=hw_bias,
                reasons=reasons,
                allow_momentum=False,
                allow_breakout=False,
                allow_retest=True,
                allow_trap=True,
                allow_ce=True,
                allow_pe=True
            )

        # RULE C: Sideways / Range Chop
        is_adx_flat = current_adx < self.config.adx_sideways_max
        is_ema_compressed = ema_diff_pct < self.config.ema_compression_pct
        is_vwap_chopping = price_vs_vwap == "AT_VWAP"
        is_hw_divergent = hw_bias == "DIVERGENT"

        sideways_evidence = sum([is_adx_flat, is_ema_compressed, is_vwap_chopping, structure_bias == "RANGE_BOUND", is_hw_divergent])

        if sideways_evidence >= 3 or (is_adx_flat and is_ema_compressed):
            reasons.append(f"Sideways indicators triggered ({sideways_evidence}/5 evidence points)")
            if is_adx_flat:
                reasons.append(f"ADX low ({current_adx:.1f} < {self.config.adx_sideways_max:.1f})")
            if is_ema_compressed:
                reasons.append(f"EMA 8/21 compressed ({ema_diff_pct:.3f}%)")
            if is_vwap_chopping:
                reasons.append("Price oscillating around VWAP")
            if is_hw_divergent:
                reasons.append("Heavyweights divergent (fighting each other)")

            return RegimeClassification(
                regime=MarketRegime.SIDEWAYS,
                confidence=75.0 + (sideways_evidence * 5.0),
                adx=current_adx,
                adx_slope=adx_slope,
                atr=current_atr,
                atr_expansion_ratio=atr_expansion,
                price_vs_vwap=price_vs_vwap,
                ema_15m_alignment="COMPRESSED",
                structure_bias=structure_bias,
                heavyweight_bias=hw_bias,
                reasons=reasons,
                allow_momentum=False,  # STRICTLY FORBIDDEN IN CHOP
                allow_breakout=False,  # STRICTLY FORBIDDEN IN CHOP
                allow_retest=False,
                allow_trap=True,       # Only retail trap / fakeout reversal allowed
                allow_ce=False,
                allow_pe=False
            )

        # RULE D: Trending Bullish
        is_bullish_trend = (
            ema8 > ema21 and
            price_vs_vwap in ("ABOVE", "AT_VWAP") and
            current_adx >= self.config.adx_trending_min and
            structure_bias in ("BULLISH_HH_HL", "RANGE_BOUND") and
            hw_bias != "BEARISH"
        )
        if is_bullish_trend:
            reasons.append(f"Bullish EMA 8 > 21 with price above VWAP and ADX {current_adx:.1f} (slope {adx_slope:+.2f})")
            return RegimeClassification(
                regime=MarketRegime.TRENDING_BULLISH,
                confidence=min(95.0, 70.0 + current_adx),
                adx=current_adx,
                adx_slope=adx_slope,
                atr=current_atr,
                atr_expansion_ratio=atr_expansion,
                price_vs_vwap=price_vs_vwap,
                ema_15m_alignment="BULLISH",
                structure_bias=structure_bias,
                heavyweight_bias=hw_bias,
                reasons=reasons,
                allow_momentum=True,
                allow_breakout=True,
                allow_retest=True,
                allow_trap=False,
                allow_ce=True,
                allow_pe=False  # PE blocked in bullish trend
            )

        # RULE E: Trending Bearish
        is_bearish_trend = (
            ema8 < ema21 and
            price_vs_vwap in ("BELOW", "AT_VWAP") and
            current_adx >= self.config.adx_trending_min and
            structure_bias in ("BEARISH_LH_LL", "RANGE_BOUND") and
            hw_bias != "BULLISH"
        )
        if is_bearish_trend:
            reasons.append(f"Bearish EMA 8 < 21 with price below VWAP and ADX {current_adx:.1f} (slope {adx_slope:+.2f})")
            return RegimeClassification(
                regime=MarketRegime.TRENDING_BEARISH,
                confidence=min(95.0, 70.0 + current_adx),
                adx=current_adx,
                adx_slope=adx_slope,
                atr=current_atr,
                atr_expansion_ratio=atr_expansion,
                price_vs_vwap=price_vs_vwap,
                ema_15m_alignment="BEARISH",
                structure_bias=structure_bias,
                heavyweight_bias=hw_bias,
                reasons=reasons,
                allow_momentum=True,
                allow_breakout=True,
                allow_retest=True,
                allow_trap=False,
                allow_ce=False,  # CE blocked in bearish trend
                allow_pe=True
            )

        # Fallback: Moderate structure or developing trend
        reasons.append(f"Transitional market state (ADX {current_adx:.1f}, EMA spread {ema_diff_pct:.2f}%)")
        return RegimeClassification(
            regime=MarketRegime.UNKNOWN,
            confidence=50.0,
            adx=current_adx,
            adx_slope=adx_slope,
            atr=current_atr,
            atr_expansion_ratio=atr_expansion,
            price_vs_vwap=price_vs_vwap,
            ema_15m_alignment="TRANSITIONAL",
            structure_bias=structure_bias,
            heavyweight_bias=hw_bias,
            reasons=reasons,
            allow_momentum=False,
            allow_breakout=False,
            allow_retest=True,
            allow_trap=True,
            allow_ce=True,
            allow_pe=True
        )
