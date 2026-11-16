import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import numpy as np
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.momentum")

class MomentumDetectionEngine:
    """
    Engine 1: Momentum Detection Engine (Upgraded - Phase 3)
    Identifies high-quality directional momentum while filtering out exhaustion:
    - Strong directional candles (body >= 60% of total range)
    - Rejection of overextended candles (avoids chasing after 2.5x median range candles)
    - Small opposing wicks (opposing wick <= 30% of total range)
    - Sudden volume expansion (volume > 1.3x 10-bar average)
    - Momentum continuation (price holding above/below EMA8 and EMA 8/21 aligned)
    - VWAP alignment
    - ADX confirmation (filters out low-ADX chop)
    """

    def __init__(self, min_body_ratio: float = 0.60, min_vol_ratio: float = 1.30):
        self.strategy_id = "ENGINE_1_MOMENTUM"
        self.strategy_name = "Momentum Detection Engine"
        self.min_body_ratio = min_body_ratio
        self.min_vol_ratio = min_vol_ratio

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> OpportunitySignal:
        # Prioritize 3-minute candles to filter out 1-minute micro-noise and false momentum
        bars = candles_3m if (candles_3m and len(candles_3m) >= 10) else candles_1m
        if len(bars) < 10:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="Insufficient bars",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Insufficient history (<10 bars)"
            )

        curr_bar = bars[-1]
        prev_bar = bars[-2]
        time_str = str(curr_bar.get("date", ""))
        curr_price = float(curr_bar["close"])
        curr_open = float(curr_bar["open"])
        curr_high = float(curr_bar["high"])
        curr_low = float(curr_bar["low"])
        curr_vol = float(curr_bar.get("volume", 0))

        bar_range = curr_high - curr_low
        if bar_range <= 0:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition="Zero range bar",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Zero range bar"
            )

        # 1. Check for Candle Overextension (Exhaustion Risk)
        recent_ranges = [float(b["high"]) - float(b["low"]) for b in bars[-11:-1]]
        median_range = float(np.median(recent_ranges)) if recent_ranges else bar_range
        if median_range > 0 and (bar_range > 4.5 * median_range and bar_range > 35.0):
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition="Candle overextended",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason=f"REJECTED_OVEREXTENDED_CANDLE (Range {bar_range:.1f} > 4.5x median {median_range:.1f})"
            )

        # Volume baseline (10-period SMA)
        recent_vols = [float(b.get("volume", 0)) for b in bars[-11:-1]]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols and sum(recent_vols) > 0 else curr_vol
        vol_ratio = (curr_vol / avg_vol) if avg_vol > 0 else 1.0

        body = abs(curr_price - curr_open)
        body_ratio = body / bar_range

        # Recent 10-bar swing extremes (excluding current bar)
        recent_10 = bars[-11:-1]
        swing_high_10 = max(float(b["high"]) for b in recent_10)
        swing_low_10 = min(float(b["low"]) for b in recent_10)

        ema8 = float(indicators.get("ema8", curr_price))
        ema21 = float(indicators.get("ema21", curr_price))
        vwap = float(indicators.get("vwap", curr_price))
        adx = float(indicators.get("adx", 20.0))

        # Filter out low-ADX chop regimes
        if adx < 16.0:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition="Low ADX chop",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason=f"REJECTED_LOW_ADX ({adx:.1f} < 16.0)"
            )

        # 1. Bullish Momentum (CE Signal)
        upper_wick = curr_high - curr_price
        upper_wick_ratio = upper_wick / bar_range
        is_bullish_candle = (curr_price > curr_open) and (body_ratio >= self.min_body_ratio) and (upper_wick_ratio <= 0.32)
        vol_expanded = vol_ratio >= self.min_vol_ratio
        broke_micro_high = curr_price > swing_high_10 or (curr_high >= swing_high_10 and curr_price >= prev_bar["high"])
        price_above_ema = curr_price >= ema8 and ema8 >= ema21 * 0.998
        price_above_vwap = curr_price >= vwap

        if is_bullish_candle and (vol_expanded or broke_micro_high) and price_above_ema and price_above_vwap:
            score = 75.0
            if vol_expanded:
                score += 8.0
            if broke_micro_high:
                score += 7.0
            if adx >= 22.0:
                score += 5.0
            score = min(95.0, score)

            sl_dist = max(3.0, min(6.5, curr_price - curr_low + 1.0))

            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=True,
                direction="CE",
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition=f"Bullish momentum expansion (body {body_ratio:.0%}, vol {vol_ratio:.1f}x, ADX {adx:.1f})",
                confidence=score,
                stop_loss_pts=sl_dist,
                target_pts=3.0,
                supporting_metadata={
                    "body_ratio": round(body_ratio, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "broken_high": swing_high_10,
                    "ema8": ema8,
                    "vwap": vwap,
                    "adx": adx
                }
            )

        # 2. Bearish Momentum (PE Signal)
        lower_wick = curr_price - curr_low
        lower_wick_ratio = lower_wick / bar_range
        is_bearish_candle = (curr_price < curr_open) and (body_ratio >= self.min_body_ratio) and (lower_wick_ratio <= 0.32)
        broke_micro_low = curr_price < swing_low_10 or (curr_low <= swing_low_10 and curr_price <= prev_bar["low"])
        price_below_ema = curr_price <= ema8 and ema8 <= ema21 * 1.002
        price_below_vwap = curr_price <= vwap

        if is_bearish_candle and (vol_expanded or broke_micro_low) and price_below_ema and price_below_vwap:
            score = 75.0
            if vol_expanded:
                score += 8.0
            if broke_micro_low:
                score += 7.0
            if adx >= 22.0:
                score += 5.0
            score = min(95.0, score)

            sl_dist = max(3.0, min(6.5, curr_high - curr_price + 1.0))

            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=True,
                direction="PE",
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition=f"Bearish momentum expansion (body {body_ratio:.0%}, vol {vol_ratio:.1f}x, ADX {adx:.1f})",
                confidence=score,
                stop_loss_pts=sl_dist,
                target_pts=3.0,
                supporting_metadata={
                    "body_ratio": round(body_ratio, 2),
                    "vol_ratio": round(vol_ratio, 2),
                    "broken_low": swing_low_10,
                    "ema8": ema8,
                    "vwap": vwap,
                    "adx": adx
                }
            )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No momentum expansion trigger",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No expansion candle or volume/EMA/VWAP confluence"
        )
