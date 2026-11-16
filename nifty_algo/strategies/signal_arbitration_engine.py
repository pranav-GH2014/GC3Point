import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.arbitration")

@dataclass
class ScoreBreakdown:
    market_structure: float = 0.0     # Max 20
    candle_price_action: float = 0.0  # Max 20
    momentum_volume: float = 0.0      # Max 15
    ema_vwap: float = 0.0             # Max 10
    liquidity_smc: float = 0.0        # Max 10
    heavyweight: float = 0.0          # Max 10
    oi_intelligence: float = 0.0      # Max 5
    fvg: float = 0.0                  # Max 5
    execution_quality: float = 0.0    # Max 5

    @property
    def total_score(self) -> float:
        return min(100.0, max(0.0, (
            self.market_structure +
            self.candle_price_action +
            self.momentum_volume +
            self.ema_vwap +
            self.liquidity_smc +
            self.heavyweight +
            self.oi_intelligence +
            self.fvg +
            self.execution_quality
        )))

    def to_dict(self) -> Dict[str, float]:
        return {
            "market_structure": round(self.market_structure, 1),
            "candle_price_action": round(self.candle_price_action, 1),
            "momentum_volume": round(self.momentum_volume, 1),
            "ema_vwap": round(self.ema_vwap, 1),
            "liquidity_smc": round(self.liquidity_smc, 1),
            "heavyweight": round(self.heavyweight, 1),
            "oi_intelligence": round(self.oi_intelligence, 1),
            "fvg": round(self.fvg, 1),
            "execution_quality": round(self.execution_quality, 1),
            "total_score": round(self.total_score, 1)
        }


@dataclass
class ArbitratedDecision:
    should_execute: bool
    direction: Optional[str]            # 'CE' or 'PE'
    primary_strategy: str               # Winning strategy name
    contributing_strategies: List[str]  # All strategies that triggered in this direction
    combined_confidence: float          # Combined & ranked confidence (0 to 100)
    decision_tier: str                  # 'REJECT', 'OBSERVE', 'QUALIFIED', 'HIGH_PRIORITY'
    reference_spot: float               # Spot entry reference price
    stop_loss_pts: float                # Structural SL in points
    target_pts: float                   # Target points
    entry_reason: str                   # Consolidated description
    rejection_reasons: List[str]        # List of reasons if skipped or rejected
    score_breakdown: Optional[ScoreBreakdown] = None
    duplicate_merged: bool = False      # Whether simultaneous co-directional signals were merged
    conflict_detected: bool = False     # Whether opposing CE/PE signals occurred


class SignalArbitrationEngine:
    """
    Central Signal Arbitration Engine (Upgraded - Phase 5)
    Integrates primary driver conviction with secondary boosters and component score breakdown.
    Supports a 100-point normalized scale:
    - Market Structure: 20 pts
    - Candle / Price Action: 20 pts
    - Momentum / Volume: 15 pts
    - EMA / VWAP: 10 pts
    - Liquidity / SMC: 10 pts
    - Heavyweight Alignment: 10 pts
    - OI Intelligence: 5 pts
    - FVG: 5 pts
    - Execution Quality: 5 pts

    Decision Thresholds:
    - Below 70: REJECT
    - 70 - 79: OBSERVE
    - 80 - 89: QUALIFIED (Permitted for entry)
    - 90 - 100: HIGH_PRIORITY (Expanded runner capability)
    """

    def __init__(
        self,
        min_confidence_threshold: float = 80.0,
        primary_engines: Optional[List[str]] = None,
        secondary_boosters: Optional[List[str]] = None,
        booster_boost_pts: float = 8.0,
        opposing_penalty_pts: float = 6.0,
        allow_standalone_boosters: bool = False
    ):
        self.min_confidence_threshold = min_confidence_threshold
        self.primary_engines = primary_engines if primary_engines is not None else [
            "ENGINE_1_MOMENTUM", "ENGINE_2_RETEST", "ENGINE_3_TRAP", "ENGINE_4_BREAKOUT"
        ]
        self.secondary_boosters = secondary_boosters if secondary_boosters is not None else [
            "ENGINE_5_FVG", "ENGINE_6_OI_INTEL"
        ]
        self.booster_boost_pts = booster_boost_pts
        self.opposing_penalty_pts = opposing_penalty_pts
        self.allow_standalone_boosters = allow_standalone_boosters
        self.last_executed_bar_timestamp: Optional[str] = None

    def arbitrate(
        self,
        signals: List[OpportunitySignal],
        indicators: Dict[str, Any],
        has_open_position: bool,
        current_bar_idx: int = 0,
        heavyweight_eval: Optional[Any] = None,
        market_regime: Optional[str] = None,
        structure: Optional[Dict[str, Any]] = None,
        spread_pts: float = 0.50
    ) -> ArbitratedDecision:
        rejection_reasons = []

        # 1. Immediate Lock Check: Only 1 position at any time
        if has_open_position:
            return ArbitratedDecision(
                should_execute=False,
                direction=None,
                primary_strategy="NONE",
                contributing_strategies=[],
                combined_confidence=0.0,
                decision_tier="REJECT",
                reference_spot=0.0,
                stop_loss_pts=5.0,
                target_pts=3.0,
                entry_reason="Position already active",
                rejection_reasons=["REJECTED_OPEN_POSITION_ACTIVE"]
            )

        # 2. Filter triggered signals
        triggered_signals = [s for s in signals if s.triggered]
        if not triggered_signals:
            return ArbitratedDecision(
                should_execute=False,
                direction=None,
                primary_strategy="NONE",
                contributing_strategies=[],
                combined_confidence=0.0,
                decision_tier="REJECT",
                reference_spot=0.0,
                stop_loss_pts=5.0,
                target_pts=3.0,
                entry_reason="No triggered signals",
                rejection_reasons=["NO_TRIGGERED_SIGNALS"]
            )

        primary_sigs = [
            s for s in triggered_signals 
            if not self.primary_engines or s.strategy_id in self.primary_engines
        ]
        booster_sigs = [
            s for s in triggered_signals 
            if s.strategy_id in self.secondary_boosters
        ]

        if not primary_sigs:
            if not self.allow_standalone_boosters:
                return ArbitratedDecision(
                    should_execute=False,
                    direction=None,
                    primary_strategy="NONE",
                    contributing_strategies=[s.strategy_name for s in booster_sigs],
                    combined_confidence=0.0,
                    decision_tier="REJECT",
                    reference_spot=0.0,
                    stop_loss_pts=5.0,
                    target_pts=3.0,
                    entry_reason="Secondary boosters triggered without primary driver initiation",
                    rejection_reasons=["NO_PRIMARY_DRIVER_INITIATED"]
                )
            else:
                primary_sigs = booster_sigs

        # 3. Direction & Conflict Handling
        ce_primaries = [s for s in primary_sigs if s.direction == "CE"]
        pe_primaries = [s for s in primary_sigs if s.direction == "PE"]

        conflict_detected = False
        selected_primaries: List[OpportunitySignal] = []
        selected_direction: Optional[str] = None

        if ce_primaries and pe_primaries:
            conflict_detected = True
            ce_max = max(s.confidence for s in ce_primaries)
            pe_max = max(s.confidence for s in pe_primaries)

            vwap = float(indicators.get("vwap", 0.0))
            spot = primary_sigs[0].reference_price
            price_above_vwap = spot > vwap
            ema_bullish = bool(indicators.get("ema_bullish", False))
            ema_bearish = bool(indicators.get("ema_bearish", False))

            if ce_max >= pe_max + 5.0 and (price_above_vwap or ema_bullish or market_regime == "TRENDING_BULLISH"):
                selected_primaries = ce_primaries
                selected_direction = "CE"
                rejection_reasons.append("CONFLICT_RESOLVED_CE_DOMINANT")
            elif pe_max >= ce_max + 5.0 and ((not price_above_vwap) or ema_bearish or market_regime == "TRENDING_BEARISH"):
                selected_primaries = pe_primaries
                selected_direction = "PE"
                rejection_reasons.append("CONFLICT_RESOLVED_PE_DOMINANT")
            else:
                return ArbitratedDecision(
                    should_execute=False,
                    direction=None,
                    primary_strategy="NONE",
                    contributing_strategies=[s.strategy_name for s in primary_sigs],
                    combined_confidence=0.0,
                    decision_tier="REJECT",
                    reference_spot=spot,
                    stop_loss_pts=5.0,
                    target_pts=3.0,
                    entry_reason="Conflicting simultaneous CE & PE signals rejected",
                    rejection_reasons=["REJECTED_CONFLICTING_CE_PE_SIGNALS"],
                    conflict_detected=True
                )
        elif ce_primaries:
            selected_primaries = ce_primaries
            selected_direction = "CE"
        else:
            selected_primaries = pe_primaries
            selected_direction = "PE"

        # 4. Regime Suitability Gate
        if market_regime == "SIDEWAYS":
            has_breakout_or_momentum = any(p.strategy_id in ("ENGINE_1_MOMENTUM", "ENGINE_4_BREAKOUT") for p in selected_primaries)
            if has_breakout_or_momentum:
                return ArbitratedDecision(
                    should_execute=False,
                    direction=None,
                    primary_strategy="NONE",
                    contributing_strategies=[p.strategy_name for p in selected_primaries],
                    combined_confidence=50.0,
                    decision_tier="REJECT",
                    reference_spot=selected_primaries[0].reference_price,
                    stop_loss_pts=5.0,
                    target_pts=3.0,
                    entry_reason="Momentum/Breakout prohibited during SIDEWAYS regime",
                    rejection_reasons=["REJECTED_SIDEWAYS_REGIME_RESTRICTION"]
                )

        selected_primaries.sort(key=lambda s: s.confidence, reverse=True)
        best_primary = selected_primaries[0]
        base_confidence = best_primary.confidence

        # 5. Calculate Score Adjustments & Confluence
        final_score = base_confidence

        aligned_boosters = [b for b in booster_sigs if b.direction == selected_direction]
        opposing_boosters = [b for b in booster_sigs if b.direction != selected_direction]

        if aligned_boosters:
            final_score += (len(aligned_boosters) * self.booster_boost_pts)
        if opposing_boosters:
            final_score -= (len(opposing_boosters) * self.opposing_penalty_pts)

        # 6. Apply Heavyweight Alignment
        heavyweight_factors = []
        if heavyweight_eval is not None:
            if selected_direction == "CE":
                if getattr(heavyweight_eval, "is_bullish_aligned", False):
                    boost = getattr(heavyweight_eval, "alignment_boost", 10.0)
                    final_score += boost
                    heavyweight_factors.append(f"BIG_3_BULLISH_ALIGNMENT (+{boost:.0f} pts)")
                elif getattr(heavyweight_eval, "is_partial_bullish", False):
                    p_boost = getattr(heavyweight_eval, "partial_boost", 5.0)
                    final_score += p_boost
                    heavyweight_factors.append(f"BIG_3_PARTIAL_BULLISH (+{p_boost:.0f} pts)")
                elif getattr(heavyweight_eval, "is_bearish_aligned", False):
                    pen = getattr(heavyweight_eval, "opposing_penalty", 15.0)
                    final_score -= pen
                    rejection_reasons.append("OPPOSING_BIG_3_BEARISH_ALIGNMENT")
            elif selected_direction == "PE":
                if getattr(heavyweight_eval, "is_bearish_aligned", False):
                    boost = getattr(heavyweight_eval, "alignment_boost", 10.0)
                    final_score += boost
                    heavyweight_factors.append(f"BIG_3_BEARISH_ALIGNMENT (+{boost:.0f} pts)")
                elif getattr(heavyweight_eval, "is_partial_bearish", False):
                    p_boost = getattr(heavyweight_eval, "partial_boost", 5.0)
                    final_score += p_boost
                    heavyweight_factors.append(f"BIG_3_PARTIAL_BEARISH (+{p_boost:.0f} pts)")
                elif getattr(heavyweight_eval, "is_bullish_aligned", False):
                    pen = getattr(heavyweight_eval, "opposing_penalty", 15.0)
                    final_score -= pen
                    rejection_reasons.append("OPPOSING_BIG_3_BULLISH_ALIGNMENT")

            if getattr(heavyweight_eval, "is_divergence_trap", False):
                pen_trap = getattr(heavyweight_eval, "divergence_trap_penalty", 10.0)
                final_score -= pen_trap
                rejection_reasons.append("HEAVYWEIGHT_DIVERGENCE_CHOP_WARNING")

        final_score = min(99.0, max(0.0, final_score))

        # Build ScoreBreakdown for structured logging and audit
        breakdown = ScoreBreakdown()
        meta = best_primary.supporting_metadata or {}
        room = float(structure.get("room_to_resistance" if selected_direction == "CE" else "room_to_support", 10.0)) if structure else 10.0
        breakdown.market_structure = min(20.0, max(5.0, room * 1.5))
        breakdown.candle_price_action = min(20.0, float(meta.get("body_ratio", 0.65)) * 25.0)
        breakdown.momentum_volume = min(15.0, float(meta.get("vol_ratio", 1.25)) * 10.0)
        breakdown.ema_vwap = 10.0 if indicators.get("price_above_vwap" if selected_direction == "CE" else "price_below_vwap", True) else 5.0
        breakdown.liquidity_smc = 10.0 if any(s.strategy_id in ("ENGINE_2_RETEST", "ENGINE_3_TRAP") for s in selected_primaries) else 6.0
        breakdown.heavyweight = 10.0 if (heavyweight_eval and getattr(heavyweight_eval, "is_bullish_aligned" if selected_direction == "CE" else "is_bearish_aligned", False)) else 5.0
        breakdown.oi_intelligence = 5.0 if aligned_boosters else 2.5
        breakdown.fvg = 5.0 if any(b.strategy_id == "ENGINE_5_FVG" for b in aligned_boosters) else 2.0
        breakdown.execution_quality = 5.0 if spread_pts <= 0.5 else 3.0

        # Determine Decision Tier
        if final_score >= 90.0:
            decision_tier = "HIGH_PRIORITY"
        elif final_score >= self.min_confidence_threshold:
            decision_tier = "QUALIFIED"
        elif final_score >= 70.0:
            decision_tier = "OBSERVE"
        else:
            decision_tier = "REJECT"

        target_pts = 3.0
        if heavyweight_eval is not None and getattr(heavyweight_eval, "is_fast_mover", False):
            if getattr(heavyweight_eval, "fast_move_direction", None) == selected_direction:
                target_pts = float(getattr(heavyweight_eval, "expanded_target_pts", 15.0))
                heavyweight_factors.append(f"SUPER_TREND_TARGET_EXPANSION (+{target_pts:.0f} pts)")

        # Critical rejection check:
        # Rejection reasons like OPPOSING_BIG_3 or OPPOSING_SIGNALS or SIDEWAYS block execution
        has_blocking_rejection = any("OPPOSING" in r or "SIDEWAYS" in r or "REJECTED" in r for r in rejection_reasons)
        should_exec = (final_score >= self.min_confidence_threshold) and not has_blocking_rejection

        if not should_exec and final_score < self.min_confidence_threshold:
            rejection_reasons.append(f"CONFIDENCE_BELOW_{int(self.min_confidence_threshold)}")

        contributing = [best_primary.strategy_name]
        for p in selected_primaries[1:]:
            if p.strategy_name not in contributing:
                contributing.append(p.strategy_name)
        for b in aligned_boosters:
            if b.strategy_name not in contributing:
                contributing.append(f"{b.strategy_name} [BOOSTER]")
        for h in heavyweight_factors:
            if h not in contributing:
                contributing.append(h)

        entry_description = f"[{best_primary.strategy_name}] {best_primary.entry_condition}"
        boost_parts = [b.strategy_name for b in aligned_boosters] + heavyweight_factors
        if boost_parts:
            entry_description += f" (Boosted by: {', '.join(boost_parts)})"

        return ArbitratedDecision(
            should_execute=should_exec,
            direction=selected_direction,
            primary_strategy=best_primary.strategy_name,
            contributing_strategies=contributing,
            combined_confidence=round(final_score, 1),
            decision_tier=decision_tier,
            reference_spot=best_primary.reference_price,
            stop_loss_pts=best_primary.stop_loss_pts,
            target_pts=target_pts,
            entry_reason=entry_description,
            rejection_reasons=rejection_reasons,
            score_breakdown=breakdown,
            duplicate_merged=(len(selected_primaries) > 1 or len(aligned_boosters) > 0),
            conflict_detected=conflict_detected
        )
