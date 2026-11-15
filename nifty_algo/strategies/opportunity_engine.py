from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
from .base_setup import BaseSetup, SetupSignal
from .support_resistance_engine import SupportResistanceEngine
from .day_high_low_engine import DayHighLowEngine
from .bos_engine import BOSEngine
from .fvg_engine import FVGEngine
from .candle_pattern_engine import CandlePatternEngine
from .oi_analysis_engine import OIAnalysisEngine
from ..confidence.signal_scoring_engine import SignalScoringEngine, ScoringResult

@dataclass
class OpportunityDecision:
    mode: str  # 'OPPORTUNITY' or 'HIGH_CONVICTION'
    should_enter: bool
    direction: Optional[str]  # 'BULLISH' (Buy CE) or 'BEARISH' (Buy PE)
    primary_setup: str
    confidence_score: float
    entry_price: float
    invalidation_level: float
    reasons: List[str]
    supporting_categories: List[str]
    all_signals: List[SetupSignal]

class OpportunityEngine:
    """
    Coordinates Opportunity Mode (Primary) and High-Conviction Mode (Section 3 & 4).
    Features:
    - Independent signal generation across S/R, Day H/L, BOS, FVG, Candles, and OI.
    - No requirement for all indicators to agree.
    - Merge duplicate signals and resolve conflicting CE/PE priorities (Section 9).
    - Mode-specific validation:
      * OPPORTUNITY: Any single qualifying setup with confidence >= 80.0 triggers.
      * HIGH_CONVICTION: Requires >= 2 independent confirmation categories.
    """

    def __init__(
        self,
        mode: str = "OPPORTUNITY",
        opportunity_min_score: float = 80.0,
        high_conviction_min_score: float = 85.0
    ):
        self.mode = mode.upper()
        self.opportunity_min_score = opportunity_min_score
        self.high_conviction_min_score = high_conviction_min_score

        # Instantiate 6 independent signal generators
        self.sr_engine = SupportResistanceEngine()
        self.dhl_engine = DayHighLowEngine()
        self.bos_engine = BOSEngine()
        self.fvg_engine = FVGEngine()
        self.candle_engine = CandlePatternEngine()
        self.oi_engine = OIAnalysisEngine()

        self.scoring_engine = SignalScoringEngine(
            min_confidence_score=self.opportunity_min_score if self.mode == "OPPORTUNITY" else self.high_conviction_min_score
        )

    def evaluate_opportunity(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None
    ) -> OpportunityDecision:
        if not candles_1m or not candles_3m:
            return OpportunityDecision(
                mode=self.mode, should_enter=False, direction=None, primary_setup="None",
                confidence_score=0.0, entry_price=0.0, invalidation_level=0.0,
                reasons=["No candle data"], supporting_categories=[], all_signals=[]
            )

        # 1. Independent evaluation across all 6 engines
        sig_sr = self.sr_engine.evaluate(candles_1m, candles_3m, structure, indicators)
        sig_dhl = self.dhl_engine.evaluate(candles_1m, candles_3m, structure, indicators)
        sig_bos = self.bos_engine.evaluate(candles_1m, candles_3m, structure, indicators)
        sig_fvg = self.fvg_engine.evaluate(candles_1m, candles_3m, structure, indicators)
        sig_candle = self.candle_engine.evaluate(candles_1m, candles_3m, structure, indicators)
        sig_oi = self.oi_engine.evaluate(candles_1m, candles_3m, structure, indicators, oi_data=oi_data)

        raw_signals = [sig_sr, sig_dhl, sig_bos, sig_fvg, sig_candle, sig_oi]
        triggered_signals = [s for s in raw_signals if s.triggered]

        if not triggered_signals:
            return OpportunityDecision(
                mode=self.mode, should_enter=False, direction=None, primary_setup="None",
                confidence_score=0.0, entry_price=0.0, invalidation_level=0.0,
                reasons=["No setups triggered"], supporting_categories=[], all_signals=raw_signals
            )

        # 2. Score with anti-double-counting engine
        score_res = self.scoring_engine.score(raw_signals, structure, indicators, oi_data)
        if not score_res.is_eligible or not score_res.direction:
            return OpportunityDecision(
                mode=self.mode, should_enter=False, direction=None, primary_setup=score_res.primary_setup,
                confidence_score=score_res.total_score, entry_price=0.0, invalidation_level=0.0,
                reasons=score_res.reasons, supporting_categories=[], all_signals=raw_signals
            )

        # 3. Filter active signals for the winning direction
        direction_signals = [s for s in triggered_signals if s.direction == score_res.direction]
        categories = list(set(s.supporting_factors.get("category", "") for s in direction_signals if s.supporting_factors.get("category")))

        # 4. Mode-Specific Validation
        if self.mode == "HIGH_CONVICTION":
            # High-conviction requirement: At least 2 independent confirmation categories
            if len(categories) < 2:
                return OpportunityDecision(
                    mode=self.mode, should_enter=False, direction=None, primary_setup=score_res.primary_setup,
                    confidence_score=score_res.total_score, entry_price=0.0, invalidation_level=0.0,
                    reasons=[f"High-Conviction Mode requires >= 2 categories; only found {categories}"],
                    supporting_categories=categories, all_signals=raw_signals
                )
            if score_res.total_score < self.high_conviction_min_score:
                return OpportunityDecision(
                    mode=self.mode, should_enter=False, direction=None, primary_setup=score_res.primary_setup,
                    confidence_score=score_res.total_score, entry_price=0.0, invalidation_level=0.0,
                    reasons=[f"Score {score_res.total_score:.1f} < High-Conviction threshold {self.high_conviction_min_score:.1f}"],
                    supporting_categories=categories, all_signals=raw_signals
                )
        else:
            # OPPORTUNITY MODE: A single valid setup with score >= 80.0 qualifies!
            if score_res.total_score < self.opportunity_min_score:
                return OpportunityDecision(
                    mode=self.mode, should_enter=False, direction=None, primary_setup=score_res.primary_setup,
                    confidence_score=score_res.total_score, entry_price=0.0, invalidation_level=0.0,
                    reasons=[f"Score {score_res.total_score:.1f} < Opportunity threshold {self.opportunity_min_score:.1f}"],
                    supporting_categories=categories, all_signals=raw_signals
                )

        # Best signal determines entry level and initial structure stop
        best_signal = max(direction_signals, key=lambda s: s.confidence)

        return OpportunityDecision(
            mode=self.mode,
            should_enter=True,
            direction=score_res.direction,
            primary_setup=best_signal.setup_name,
            confidence_score=score_res.total_score,
            entry_price=candles_1m[-1]["close"],
            invalidation_level=best_signal.invalidation_level,
            reasons=score_res.reasons,
            supporting_categories=categories,
            all_signals=raw_signals
        )
