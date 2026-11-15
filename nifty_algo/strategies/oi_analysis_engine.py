from typing import Dict, Any, List, Optional
from .base_setup import BaseSetup, SetupSignal

class OIAnalysisEngine(BaseSetup):
    """
    Setup F: OI-Based Setup (Section 2F)
    Monitors:
    - PCR (Put-Call Ratio), Strike-wise OI concentration
    - Call unwinding & Put writing (Bullish bias)
    - Put unwinding & Call writing (Bearish bias)
    MANDATORY RULE: OI alone NEVER triggers a trade; requires price action confirmation.
    """

    def __init__(self):
        super().__init__("SETUP_OI_ASSISTED", "OI-Assisted Setup", "1m/3m")

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None
    ) -> SetupSignal:
        if not oi_data or not candles_1m:
            return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "Missing OI data", {})

        curr_1m = candles_1m[-1]
        current_price = curr_1m["close"]

        oi_bias = oi_data.get("oi_bias", "NEUTRAL")  # 'BULLISH_PE_WRITING', 'BEARISH_CE_WRITING', 'BULLISH_CE_UNWINDING', etc.
        pcr = oi_data.get("pcr", 1.0)
        call_oi_change = oi_data.get("total_ce_oi_change", 0)
        put_oi_change = oi_data.get("total_pe_oi_change", 0)

        # 1. Bullish OI Bias + Price Confirmation
        is_bullish_oi = oi_bias in ("BULLISH_PE_WRITING", "BULLISH_CE_UNWINDING") or (pcr > 1.25 and put_oi_change > call_oi_change)
        if is_bullish_oi:
            # Price action confirmation MANDATORY: Price must be closing above open and VWAP or EMA8
            price_confirmed = curr_1m["close"] > curr_1m["open"] and (
                indicators.get("price_above_vwap") or curr_1m["close"] > indicators.get("ema8", 0)
            )
            if price_confirmed:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BULLISH",
                    confidence=82.0,
                    timeframe="1m",
                    entry_level=current_price,
                    invalidation_level=current_price - 8.0,
                    reason=f"Bullish OI confluence ({oi_bias}, PCR={pcr:.2f}) confirmed by price action",
                    supporting_factors={
                        "pcr": pcr,
                        "oi_bias": oi_bias,
                        "price_above_vwap": indicators.get("price_above_vwap"),
                        "category": "OI_CONFIRMATION"
                    }
                )

        # 2. Bearish OI Bias + Price Confirmation
        is_bearish_oi = oi_bias in ("BEARISH_CE_WRITING", "BEARISH_PE_UNWINDING") or (pcr < 0.75 and call_oi_change > put_oi_change)
        if is_bearish_oi:
            # Price action confirmation MANDATORY: Price must be closing below open and VWAP or EMA8
            price_confirmed = curr_1m["close"] < curr_1m["open"] and (
                indicators.get("price_below_vwap") or curr_1m["close"] < indicators.get("ema8", 0)
            )
            if price_confirmed:
                return SetupSignal(
                    setup_id=self.setup_id,
                    setup_name=self.name,
                    triggered=True,
                    direction="BEARISH",
                    confidence=82.0,
                    timeframe="1m",
                    entry_level=current_price,
                    invalidation_level=current_price + 8.0,
                    reason=f"Bearish OI confluence ({oi_bias}, PCR={pcr:.2f}) confirmed by price action",
                    supporting_factors={
                        "pcr": pcr,
                        "oi_bias": oi_bias,
                        "price_below_vwap": indicators.get("price_below_vwap"),
                        "category": "OI_CONFIRMATION"
                    }
                )

        return SetupSignal(self.setup_id, self.name, False, None, 0.0, self.timeframe, 0.0, 0.0, "No OI confirmation", {})
