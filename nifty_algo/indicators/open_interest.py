import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("nifty_algo.open_interest")

def format_oi(oi_val: float) -> str:
    """Format large OI numbers into Indian lakhs (L) or crores (Cr)."""
    abs_oi = abs(oi_val)
    if abs_oi >= 10_000_000:
        return f"{oi_val / 10_000_000:.2f} Cr"
    elif abs_oi >= 100_000:
        return f"{oi_val / 100_000:.2f} L"
    elif abs_oi >= 1_000:
        return f"{oi_val / 1_000:.1f} K"
    return f"{int(oi_val)}"

class OpenInterestAnalyzer:
    """
    Analyzes Open Interest changes across CE and PE option chains:
    - Long Buildup (Price Up, OI Up)
    - Short Covering (Price Up, OI Down)
    - Short Buildup (Price Down, OI Up)
    - Long Unwinding (Price Down, OI Down)
    - Dynamic Call Wall & Put Wall calculation
    - Real-time Predictive Cross Engine: 'WILL CROSS' (Breakout/Breakdown) vs 'BOUNCE EXPECTED' (Wall Holding)
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
        """Calculates Put-Call Ratio (PCR) and dominant market sentiment based on relative OI changes."""
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

    @classmethod
    def calculate_oi_walls(
        cls,
        chain_data: List[Dict[str, Any]],
        spot_price: float,
        hw_eval: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Analyzes CE & PE strikes around spot to identify:
        1. Call Wall (Major Resistance strike with max CE OI)
        2. Put Wall (Major Support strike with max PE OI)
        3. Predictive Indicator: Will NIFTY cross the wall or bounce?
        """
        if not chain_data:
            return cls._generate_fallback_oi(spot_price, hw_eval)

        ce_contracts = [c for c in chain_data if c.get("instrument_type") == "CE"]
        pe_contracts = [c for c in chain_data if c.get("instrument_type") == "PE"]

        if not ce_contracts or not pe_contracts:
            return cls._generate_fallback_oi(spot_price, hw_eval)

        # 1. Total OI and PCR
        total_ce_oi = sum(c.get("oi", 0) for c in ce_contracts)
        total_pe_oi = sum(c.get("oi", 0) for c in pe_contracts)
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0

        # 2. Call Wall (Maximum CE OI strike)
        max_ce = max(ce_contracts, key=lambda x: x.get("oi", 0))
        call_wall_strike = float(max_ce["strike"])
        call_wall_oi = float(max_ce.get("oi", 0))
        call_wall_oi_change = float(max_ce.get("oi_change", 0.0))
        call_wall_ltp = float(max_ce.get("ltp", 0.0))
        call_wall_price_chg = float(max_ce.get("price_change", 0.0))
        call_buildup = cls.classify_buildup(call_wall_price_chg, call_wall_oi_change)

        # 3. Put Wall (Maximum PE OI strike)
        max_pe = max(pe_contracts, key=lambda x: x.get("oi", 0))
        put_wall_strike = float(max_pe["strike"])
        put_wall_oi = float(max_pe.get("oi", 0))
        put_wall_oi_change = float(max_pe.get("oi_change", 0.0))
        put_wall_ltp = float(max_pe.get("ltp", 0.0))
        put_wall_price_chg = float(max_pe.get("price_change", 0.0))
        put_buildup = cls.classify_buildup(put_wall_price_chg, put_wall_oi_change)

        # Heavyweight Context
        hw_bullish = getattr(hw_eval, "is_bullish_aligned", False) if hw_eval else False
        hw_bearish = getattr(hw_eval, "is_bearish_aligned", False) if hw_eval else False

        # 4. Predict: Will Spot CROSS or BOUNCE at Call Wall?
        call_dist = call_wall_strike - spot_price
        # Cross logic for Call Wall (Resistance):
        # Short covering (oi_change < 0 with rising price) or huge PCR + Bullish Heavyweights -> Cross
        if call_buildup == "SHORT_COVERING" or call_wall_oi_change < -50000:
            call_pred = "WILL_CROSS"
            call_conf = 84 + (6 if hw_bullish else 0)
            call_reason = "Short covering at Call Wall: Bears unwinding CE positions, breakout highly probable."
        elif hw_bullish and pcr > 1.25 and call_dist <= 30:
            call_pred = "WILL_CROSS"
            call_conf = 80
            call_reason = "Strong Bullish Heavyweight alignment & high PCR pushing through resistance."
        else:
            call_pred = "BOUNCE_EXPECTED"
            call_conf = 78 + (8 if hw_bearish or pcr < 0.90 else 0)
            call_reason = f"Call writers actively defending {int(call_wall_strike)}. Resistance ceiling holding."

        # 5. Predict: Will Spot BREAK or BOUNCE at Put Wall?
        put_dist = spot_price - put_wall_strike
        # Break logic for Put Wall (Support):
        # Long unwinding (oi_change < 0 with dropping price) or low PCR + Bearish Heavyweights -> Breakdown
        if put_buildup == "LONG_UNWINDING" or put_wall_oi_change < -50000:
            put_pred = "WILL_BREAK"
            put_conf = 83 + (7 if hw_bearish else 0)
            put_reason = "Long unwinding at Put Floor: Bulls capitulating PE positions, breakdown imminent."
        elif hw_bearish and pcr < 0.80 and put_dist <= 30:
            put_pred = "WILL_BREAK"
            put_conf = 80
            put_reason = "Bearish Heavyweights driving relentless selling through Put support floor."
        else:
            put_pred = "BOUNCE_EXPECTED"
            put_conf = 80 + (8 if hw_bullish or pcr > 1.10 else 0)
            put_reason = f"Massive Put writing defending {int(put_wall_strike)}. Rock-solid floor; bounce expected."

        # Dominant Market Sentiment
        if pcr > 1.20 and hw_bullish:
            dominant_sentiment = "STRONG_BULLISH"
        elif pcr < 0.80 and hw_bearish:
            dominant_sentiment = "STRONG_BEARISH"
        elif pcr > 1.05:
            dominant_sentiment = "MILD_BULLISH"
        elif pcr < 0.90:
            dominant_sentiment = "MILD_BEARISH"
        else:
            dominant_sentiment = "NEUTRAL_BALANCED"

        return {
            "has_data": True,
            "pcr": pcr,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "sentiment": dominant_sentiment,
            "call_wall": {
                "strike": call_wall_strike,
                "oi": call_wall_oi,
                "oi_formatted": format_oi(call_wall_oi),
                "oi_change": call_wall_oi_change,
                "oi_change_formatted": format_oi(call_wall_oi_change),
                "buildup": call_buildup,
                "ltp": call_wall_ltp,
                "dist_pts": round(call_dist, 1),
                "prediction": call_pred,
                "confidence": min(95, call_conf),
                "reason": call_reason,
                "status_label": f"CE {int(call_wall_strike)}: {'WILL CROSS! 🚀' if call_pred == 'WILL_CROSS' else 'BOUNCE EXPECTED 🛡️'} ({min(95, call_conf)}%)"
            },
            "put_wall": {
                "strike": put_wall_strike,
                "oi": put_wall_oi,
                "oi_formatted": format_oi(put_wall_oi),
                "oi_change": put_wall_oi_change,
                "oi_change_formatted": format_oi(put_wall_oi_change),
                "buildup": put_buildup,
                "ltp": put_wall_ltp,
                "dist_pts": round(put_dist, 1),
                "prediction": put_pred,
                "confidence": min(95, put_conf),
                "reason": put_reason,
                "status_label": f"PE {int(put_wall_strike)}: {'WILL BREAK! ⚠️' if put_pred == 'WILL_BREAK' else 'BOUNCE EXPECTED 🛡️'} ({min(95, put_conf)}%)"
            }
        }

    @classmethod
    def _generate_fallback_oi(cls, spot_price: float, hw_eval: Optional[Any] = None) -> Dict[str, Any]:
        """Provides dynamic round strike levels for pre-market, mock or warmup mode."""
        spot = spot_price if spot_price > 0 else 25000.0
        call_strike = round((spot + 80.0) / 100.0) * 100.0
        put_strike = round((spot - 80.0) / 100.0) * 100.0

        hw_bullish = getattr(hw_eval, "is_bullish_aligned", False) if hw_eval else False
        hw_bearish = getattr(hw_eval, "is_bearish_aligned", False) if hw_eval else False

        call_pred = "WILL_CROSS" if hw_bullish else "BOUNCE_EXPECTED"
        call_conf = 80 if hw_bullish else 75
        put_pred = "WILL_BREAK" if hw_bearish else "BOUNCE_EXPECTED"
        put_conf = 80 if hw_bearish else 78

        return {
            "has_data": False,
            "pcr": 1.05,
            "total_ce_oi": 5000000,
            "total_pe_oi": 5250000,
            "sentiment": "NEUTRAL_BALANCED",
            "call_wall": {
                "strike": call_strike,
                "oi": 8500000,
                "oi_formatted": "85.0 L",
                "oi_change": 120000,
                "oi_change_formatted": "+1.2 L",
                "buildup": "SHORT_BUILDUP",
                "ltp": 65.0,
                "dist_pts": round(call_strike - spot, 1),
                "prediction": call_pred,
                "confidence": call_conf,
                "reason": f"Call writers stationed at key round strike {int(call_strike)}.",
                "status_label": f"CE {int(call_strike)}: {'WILL CROSS! 🚀' if call_pred == 'WILL_CROSS' else 'BOUNCE EXPECTED 🛡️'} ({call_conf}%)"
            },
            "put_wall": {
                "strike": put_strike,
                "oi": 8200000,
                "oi_formatted": "82.0 L",
                "oi_change": 150000,
                "oi_change_formatted": "+1.5 L",
                "buildup": "LONG_BUILDUP",
                "ltp": 60.0,
                "dist_pts": round(spot - put_strike, 1),
                "prediction": put_pred,
                "confidence": put_conf,
                "reason": f"Put writers supporting key round strike {int(put_strike)}.",
                "status_label": f"PE {int(put_strike)}: {'WILL BREAK! ⚠️' if put_pred == 'WILL_BREAK' else 'BOUNCE EXPECTED 🛡️'} ({put_conf}%)"
            }
        }
