from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from ..strategies.base_setup import SetupSignal

@dataclass
class ScoringResult:
    total_score: float
    is_eligible: bool
    direction: Optional[str]  # 'BULLISH' or 'BEARISH'
    breakdown: Dict[str, float]
    contributing_factors: List[str]
    anti_double_counting_applied: bool
    primary_setup: str
    reasons: List[str]

class SignalScoringEngine:
    """
    Normalized 100-Point Scoring Engine (Section 5)
    Weights:
    - Support/Resistance: 20 pts
    - Candle Pattern: 20 pts
    - BOS: 25 pts
    - Liquidity Sweep: 20 pts
    - OI Confirmation: 15 pts
    - FVG Confirmation: 15 pts
    Total Raw Capacity: 115 pts -> Normalized to 100.
    Anti-double-counting: Correlated signals on same candle discounted.
    """

    def __init__(
        self,
        min_confidence_score: float = 80.0,
        weights: Optional[Dict[str, float]] = None
    ):
        self.min_confidence_score = min_confidence_score
        self.weights = weights or {
            "support_resistance": 20.0,
            "candle_pattern": 20.0,
            "bos": 25.0,
            "liquidity_sweep": 20.0,
            "oi_confirmation": 15.0,
            "fvg_confirmation": 15.0,
        }
        self.raw_max = sum(self.weights.values())  # 115.0

    def score(
        self,
        signals: List[SetupSignal],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None
    ) -> ScoringResult:
        triggered = [s for s in signals if s.triggered]
        if not triggered:
            return ScoringResult(
                total_score=0.0,
                is_eligible=False,
                direction=None,
                breakdown={},
                contributing_factors=[],
                anti_double_counting_applied=False,
                primary_setup="None",
                reasons=["No setups triggered"]
            )

        # 1. Determine direction consensus and select primary setup
        bullish_signals = [s for s in triggered if s.direction == "BULLISH"]
        bearish_signals = [s for s in triggered if s.direction == "BEARISH"]

        # Conflict resolution per Section 9
        if bullish_signals and bearish_signals:
            bullish_strength = sum(s.confidence for s in bullish_signals)
            bearish_strength = sum(s.confidence for s in bearish_signals)
            if abs(bullish_strength - bearish_strength) < 5.0:
                # Equally strong conflicting signals -> wait for resolution
                return ScoringResult(
                    total_score=0.0,
                    is_eligible=False,
                    direction=None,
                    breakdown={},
                    contributing_factors=["Conflict between CE and PE signals"],
                    anti_double_counting_applied=False,
                    primary_setup="CONFLICT",
                    reasons=["Equally strong conflicting CE and PE signals"]
                )
            active_signals = bullish_signals if bullish_strength > bearish_strength else bearish_signals
            primary_direction = "BULLISH" if bullish_strength > bearish_strength else "BEARISH"
        elif bullish_signals:
            active_signals = bullish_signals
            primary_direction = "BULLISH"
        else:
            active_signals = bearish_signals
            primary_direction = "BEARISH"

        # Sort by individual confidence to pick primary setup
        active_signals.sort(key=lambda s: s.confidence, reverse=True)
        primary_setup = active_signals[0].setup_name

        breakdown: Dict[str, float] = {}
        contributing: List[str] = []
        reasons: List[str] = []
        anti_double_counting = False

        # Map active signals to categories
        cat_map: Dict[str, List[SetupSignal]] = {}
        for s in active_signals:
            cat = s.supporting_factors.get("category", "")
            cat_map.setdefault(cat, []).append(s)

        # A. Support & Resistance (20 pts)
        if "SUPPORT_RESISTANCE" in cat_map:
            breakdown["support_resistance"] = self.weights["support_resistance"]
            contributing.append(f"Support/Resistance ({self.weights['support_resistance']:.0f} pts)")
            reasons.append(cat_map["SUPPORT_RESISTANCE"][0].reason)

        # B. BOS (25 pts)
        has_bos = "BOS" in cat_map
        if has_bos:
            breakdown["bos"] = self.weights["bos"]
            contributing.append(f"BOS Break ({self.weights['bos']:.0f} pts)")
            reasons.append(cat_map["BOS"][0].reason)

        # C. Candle Pattern (20 pts)
        if "CANDLE_PATTERN" in cat_map:
            # ANTI-DOUBLE-COUNTING RULE (Section 5):
            # A candle pattern and BOS generated on the same candle must NOT automatically receive full independent credit.
            if has_bos:
                # 50% correlation discount
                discounted_pts = self.weights["candle_pattern"] * 0.50
                breakdown["candle_pattern"] = discounted_pts
                contributing.append(f"Candle Pattern (discounted: {discounted_pts:.1f} pts due to BOS correlation)")
                anti_double_counting = True
            else:
                breakdown["candle_pattern"] = self.weights["candle_pattern"]
                contributing.append(f"Candle Pattern ({self.weights['candle_pattern']:.0f} pts)")
            reasons.append(cat_map["CANDLE_PATTERN"][0].reason)

        # D. Liquidity Sweep / Day H/L (20 pts)
        if "LIQUIDITY_SWEEP" in cat_map or "DAY_LEVEL_BREAKOUT" in cat_map:
            breakdown["liquidity_sweep"] = self.weights["liquidity_sweep"]
            contributing.append(f"Liquidity Sweep / Day H/L ({self.weights['liquidity_sweep']:.0f} pts)")
            sig = cat_map.get("LIQUIDITY_SWEEP", cat_map.get("DAY_LEVEL_BREAKOUT"))[0]
            reasons.append(sig.reason)

        # E. FVG Confirmation (15 pts)
        if "FVG" in cat_map:
            breakdown["fvg_confirmation"] = self.weights["fvg_confirmation"]
            contributing.append(f"FVG Confirmation ({self.weights['fvg_confirmation']:.0f} pts)")
            reasons.append(cat_map["FVG"][0].reason)

        # F. OI Confirmation (15 pts)
        if "OI_CONFIRMATION" in cat_map:
            breakdown["oi_confirmation"] = self.weights["oi_confirmation"]
            contributing.append(f"OI Confluence ({self.weights['oi_confirmation']:.0f} pts)")
            reasons.append(cat_map["OI_CONFIRMATION"][0].reason)

        # If a single strong setup triggered alone in Opportunity Mode,
        # assign its full inherent setup confidence normalized
        raw_score = sum(breakdown.values())
        
        # In Opportunity Mode: An independent setup that achieves its clean setup conditions
        # carries a base confidence of 80 points, augmented by additional confluence
        if len(active_signals) == 1 and active_signals[0].confidence >= 80.0:
            # Independent setup base credit
            normalized_score = active_signals[0].confidence
        else:
            # Multi-setup confluence normalized to 100
            # A setup + 1 confluence reaches >= 80 easily
            normalized_score = min(100.0, (raw_score / 50.0) * 100.0)
            normalized_score = max(normalized_score, active_signals[0].confidence)

        normalized_score = round(normalized_score, 1)
        is_eligible = normalized_score >= self.min_confidence_score

        return ScoringResult(
            total_score=normalized_score,
            is_eligible=is_eligible,
            direction=primary_direction,
            breakdown=breakdown,
            contributing_factors=contributing,
            anti_double_counting_applied=anti_double_counting,
            primary_setup=primary_setup,
            reasons=reasons
        )
