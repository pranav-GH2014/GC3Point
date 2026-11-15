from typing import Dict, Any, List

class OpenInterestAnalyzer:
    """
    Analyzes Open Interest changes across CE and PE option chains:
    - Long Buildup (Price Up, OI Up)
    - Short Covering (Price Up, OI Down)
    - Short Buildup (Price Down, OI Up)
    - Long Unwinding (Price Down, OI Down)
    Note: Does not assume OI proves institutional intent, but treats it as supporting market evidence.
    """

    @staticmethod
    def classify_buildup(price_change: float, oi_change: float) -> str:
        if price_change > 0 and oi_change > 0:
            return "LONG_BUILDUP"
        elif price_change > 0 and oi_change < 0:
            return "SHORT_COVERING"
        elif price_change < 0 and oi_change > 0:
            return "SHORT_BUILDUP"
        elif price_change < 0 and oi_change < 0:
            return "LONG_UNWINDING"
        return "NEUTRAL"

    @classmethod
    def analyze_chain_oi(cls, ce_oi_change: float, pe_oi_change: float, pcr: float) -> Dict[str, Any]:
        """
        Calculates Put-Call Ratio (PCR) and dominant market sentiment based on relative OI changes.
        """
        bias = "NEUTRAL"
        if pe_oi_change > ce_oi_change * 1.25 and pcr > 1.0:
            bias = "BULLISH_PE_WRITING"
        elif ce_oi_change > pe_oi_change * 1.25 and pcr < 0.8:
            bias = "BEARISH_CE_WRITING"

        return {
            "pcr": round(pcr, 2),
            "ce_oi_change": ce_oi_change,
            "pe_oi_change": pe_oi_change,
            "oi_bias": bias
        }
