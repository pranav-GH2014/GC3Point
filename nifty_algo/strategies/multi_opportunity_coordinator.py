import logging
from typing import Dict, Any, List, Optional, Tuple
from .base_setup import OpportunitySignal
from .momentum_detection_engine import MomentumDetectionEngine
from .retest_detection_engine import RetestDetectionEngine
from .retail_trap_detection_engine import RetailTrapDetectionEngine
from .breakout_detection_engine import BreakoutDetectionEngine
from .fvg_opportunity_engine import FVGOpportunityEngine
from .oi_intelligence_engine import OIIntelligenceEngine
from .signal_arbitration_engine import SignalArbitrationEngine, ArbitratedDecision

logger = logging.getLogger("nifty_algo.coordinator")

class MultiOpportunityCoordinator:
    """
    Coordinates all Six Independent Opportunity Detection Engines (Section 3)
    and passes their signals to the Signal Arbitration Engine (Section 7).
    Guarantees:
    - Independent signal generation (no engine is a compulsory confirmation for another).
    - Single unified execution candidate.
    - Full transparency and signal audit trail.
    """

    def __init__(
        self,
        min_confidence: float = 80.0,
        primary_engines: Optional[List[str]] = None,
        secondary_boosters: Optional[List[str]] = None,
        booster_boost_pts: float = 8.0,
        allow_standalone_boosters: bool = False
    ):
        self.engine_momentum = MomentumDetectionEngine()
        self.engine_retest = RetestDetectionEngine()
        self.engine_trap = RetailTrapDetectionEngine()
        self.engine_breakout = BreakoutDetectionEngine()
        self.engine_fvg = FVGOpportunityEngine()
        self.engine_oi = OIIntelligenceEngine()
        
        self.arbitrator = SignalArbitrationEngine(
            min_confidence_threshold=min_confidence,
            primary_engines=primary_engines,
            secondary_boosters=secondary_boosters,
            booster_boost_pts=booster_boost_pts,
            allow_standalone_boosters=allow_standalone_boosters
        )

    def evaluate_all_engines(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None,
        has_open_position: bool = False,
        bar_idx: int = 0,
        active_engine_mask: Optional[List[str]] = None,
        heavyweight_eval: Optional[Any] = None,
        market_regime: Optional[str] = None,
        spread_pts: float = 0.50
    ) -> Tuple[ArbitratedDecision, List[OpportunitySignal]]:
        """
        Runs the enabled engines and arbitrates the resulting signals.
        active_engine_mask: Optional list of strategy_ids to run (for individual engine backtests).
        """
        raw_signals: List[OpportunitySignal] = []

        # Engine 1: Momentum
        if not active_engine_mask or "ENGINE_1_MOMENTUM" in active_engine_mask:
            sig1 = self.engine_momentum.evaluate(candles_1m, candles_3m, structure, indicators)
            raw_signals.append(sig1)

        # Engine 2: Retest
        if not active_engine_mask or "ENGINE_2_RETEST" in active_engine_mask:
            sig2 = self.engine_retest.evaluate(candles_1m, candles_3m, structure, indicators)
            raw_signals.append(sig2)

        # Engine 3: Retail Trap
        if not active_engine_mask or "ENGINE_3_TRAP" in active_engine_mask:
            sig3 = self.engine_trap.evaluate(candles_1m, candles_3m, structure, indicators, oi_data=oi_data)
            raw_signals.append(sig3)

        # Engine 4: Breakout
        if not active_engine_mask or "ENGINE_4_BREAKOUT" in active_engine_mask:
            sig4 = self.engine_breakout.evaluate(candles_1m, candles_3m, structure, indicators)
            raw_signals.append(sig4)

        # Engine 5: FVG
        if not active_engine_mask or "ENGINE_5_FVG" in active_engine_mask:
            sig5 = self.engine_fvg.evaluate(candles_1m, candles_3m, structure, indicators)
            raw_signals.append(sig5)

        # Engine 6: OI Intelligence
        if not active_engine_mask or "ENGINE_6_OI_INTEL" in active_engine_mask:
            sig6 = self.engine_oi.evaluate(candles_1m, candles_3m, structure, indicators, oi_data=oi_data)
            raw_signals.append(sig6)

        # Pass all signals through arbitration
        decision = self.arbitrator.arbitrate(
            signals=raw_signals,
            indicators=indicators,
            has_open_position=has_open_position,
            current_bar_idx=bar_idx,
            heavyweight_eval=heavyweight_eval,
            market_regime=market_regime,
            structure=structure,
            spread_pts=spread_pts
        )

        return decision, raw_signals
