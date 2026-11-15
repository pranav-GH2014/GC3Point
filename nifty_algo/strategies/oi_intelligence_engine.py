import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.oi_intel")

class OIIntelligenceEngine:
    """
    Engine 6: OI Intelligence Engine
    Monitors:
    - CE and PE strike-wise OI changes and concentrations
    - OI buildup and unwinding (Long Buildup, Short Covering, Short Buildup, Long Unwinding)
    - Put-Call Ratio (PCR) divergence
    - Institutional Put writing (Bullish support) and Call writing (Bearish resistance)
    CRITICAL MANDATE:
    Never triggers on OI alone! Operates as an independent opportunity engine ONLY when
    confirmed by an aligned 1-minute directional price candle. Does NOT impose itself
    as a mandatory filter on the other 5 engines.
    """

    def __init__(self, pcr_bull_threshold: float = 1.05, pcr_bear_threshold: float = 0.95):
        self.strategy_id = "ENGINE_6_OI_INTEL"
        self.strategy_name = "OI Intelligence Engine"
        self.pcr_bull_threshold = pcr_bull_threshold
        self.pcr_bear_threshold = pcr_bear_threshold

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None
    ) -> OpportunitySignal:
        if len(candles_1m) < 5 or not oi_data:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="No OI data available",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Missing OI stream or data"
            )

        curr_bar = candles_1m[-1]
        time_str = str(curr_bar.get("date", ""))
        curr_price = float(curr_bar["close"])
        curr_open = float(curr_bar["open"])
        curr_high = float(curr_bar["high"])
        curr_low = float(curr_bar["low"])

        pcr = float(oi_data.get("pcr", 1.0))
        oi_bias = oi_data.get("oi_bias", "NEUTRAL")
        ce_oi_change = float(oi_data.get("ce_oi_change", 0.0))
        pe_oi_change = float(oi_data.get("pe_oi_change", 0.0))

        # Price Action Confirmation Gate:
        # Candle body direction must align with OI positioning
        is_green_candle = curr_price > curr_open
        is_red_candle = curr_price < curr_open
        bar_range = curr_high - curr_low
        body = abs(curr_price - curr_open)
        has_substance = (bar_range > 0) and (body / bar_range >= 0.40)

        # 1. Bullish OI Intelligence (CE Signal):
        # Heavy PE writing (Put additions outpace Call additions) OR Call unwinding,
        # AND confirmed by a green directional candle closing above VWAP or EMA8.
        bullish_oi = (oi_bias == "BULLISH_PE_WRITING") or (pe_oi_change > ce_oi_change * 1.2 and pcr >= self.pcr_bull_threshold)
        price_confirms_bull = is_green_candle and has_substance and (curr_price >= float(indicators.get("ema8", 0.0)))

        if bullish_oi and price_confirms_bull:
            score = 80.0
            if pcr >= 1.25:
                score += 8.0
            if curr_price > float(indicators.get("vwap", 0.0)):
                score += 5.0

            sl_dist = max(3.0, min(8.0, curr_price - curr_low + 1.0))

            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=True,
                direction="CE",
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition=f"Bullish OI Alignment: Put Writing dominant (PCR {pcr:.2f}) + confirming green candle",
                confidence=min(95.0, score),
                stop_loss_pts=sl_dist,
                target_pts=3.0,
                supporting_metadata={
                    "pcr": round(pcr, 2),
                    "oi_bias": oi_bias,
                    "ce_change": ce_oi_change,
                    "pe_change": pe_oi_change
                }
            )

        # 2. Bearish OI Intelligence (PE Signal):
        # Heavy CE writing (Call additions outpace Put additions) OR Put unwinding,
        # AND confirmed by a red directional candle closing below VWAP or EMA8.
        bearish_oi = (oi_bias == "BEARISH_CE_WRITING") or (ce_oi_change > pe_oi_change * 1.2 and pcr <= self.pcr_bear_threshold)
        price_confirms_bear = is_red_candle and has_substance and (curr_price <= float(indicators.get("ema8", 999999.0)))

        if bearish_oi and price_confirms_bear:
            score = 80.0
            if pcr <= 0.80:
                score += 8.0
            if curr_price < float(indicators.get("vwap", 999999.0)):
                score += 5.0

            sl_dist = max(3.0, min(8.0, curr_high - curr_price + 1.0))

            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=True,
                direction="PE",
                timestamp=time_str,
                reference_price=curr_price,
                entry_condition=f"Bearish OI Alignment: Call Writing dominant (PCR {pcr:.2f}) + confirming red candle",
                confidence=min(95.0, score),
                stop_loss_pts=sl_dist,
                target_pts=3.0,
                supporting_metadata={
                    "pcr": round(pcr, 2),
                    "oi_bias": oi_bias,
                    "ce_change": ce_oi_change,
                    "pe_change": pe_oi_change
                }
            )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No OI intelligence trigger",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="OI bias and price candle unaligned"
        )
