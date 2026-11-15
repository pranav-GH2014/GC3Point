import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.arbitration")

@dataclass
class ArbitratedDecision:
    should_execute: bool
    direction: Optional[str]            # 'CE' or 'PE'
    primary_strategy: str               # Winning strategy name
    contributing_strategies: List[str]  # All strategies that triggered in this direction
    combined_confidence: float          # Combined & ranked confidence
    reference_spot: float               # Spot entry reference price
    stop_loss_pts: float                # Structural SL in points
    target_pts: float                   # Fixed +3.0 option premium target
    entry_reason: str                   # Consolidated description
    rejection_reasons: List[str]        # List of reasons if skipped or rejected
    duplicate_merged: bool = False      # Whether simultaneous co-directional signals were merged
    conflict_detected: bool = False     # Whether opposing CE/PE signals occurred

class SignalArbitrationEngine:
    """
    Central Signal Arbitration Engine (Section 7)
    Supports:
    - Primary Driver vs. Secondary Booster Engine Architecture:
      * Primary Engines (Engine 1 Momentum, Engine 4 Breakout): Initiate trades.
      * Secondary Boosters (Engine 3 Trap, Engine 6 OI): Add confluence boost (+8.0 pts)
        without creating standalone noise.
    - Validates signal freshness.
    - Ranks simultaneous signals.
    - Merges duplicate co-directional signals into one single position.
    - Resolves conflicting CE vs. PE signals using multi-timeframe structure or skips if ambiguous.
    - Enforces the 1-position-at-a-time mandate.
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
        # Default Primary: Engine 1 (Momentum) & Engine 4 (Breakout)
        self.primary_engines = primary_engines if primary_engines is not None else [
            "ENGINE_1_MOMENTUM", "ENGINE_4_BREAKOUT"
        ]
        # Default Boosters: Engine 3 (Trap) & Engine 6 (OI Intelligence)
        self.secondary_boosters = secondary_boosters if secondary_boosters is not None else [
            "ENGINE_3_TRAP", "ENGINE_6_OI_INTEL"
        ]
        self.booster_boost_pts = booster_boost_pts
        self.opposing_penalty_pts = opposing_penalty_pts
        self.allow_standalone_boosters = allow_standalone_boosters
        self.last_executed_bar_idx = -999

    def arbitrate(
        self,
        signals: List[OpportunitySignal],
        indicators: Dict[str, Any],
        has_open_position: bool,
        current_bar_idx: int = 0,
        heavyweight_eval: Optional[Any] = None
    ) -> ArbitratedDecision:
        rejection_reasons = []

        # 1. Immediate Lock Check: Only one open position at any time (Section 9)
        if has_open_position:
            return ArbitratedDecision(
                should_execute=False,
                direction=None,
                primary_strategy="NONE",
                contributing_strategies=[],
                combined_confidence=0.0,
                reference_spot=0.0,
                stop_loss_pts=5.0,
                target_pts=3.0,
                entry_reason="Position already active",
                rejection_reasons=["REJECTED_OPEN_POSITION_ACTIVE"]
            )

        # 2. Filter triggered signals into Primary and Secondary Boosters
        triggered_signals = [s for s in signals if s.triggered]

        if not triggered_signals:
            return ArbitratedDecision(
                should_execute=False,
                direction=None,
                primary_strategy="NONE",
                contributing_strategies=[],
                combined_confidence=0.0,
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

        # If no primary driver fired:
        if not primary_sigs:
            if not self.allow_standalone_boosters:
                return ArbitratedDecision(
                    should_execute=False,
                    direction=None,
                    primary_strategy="NONE",
                    contributing_strategies=[s.strategy_name for s in booster_sigs],
                    combined_confidence=0.0,
                    reference_spot=0.0,
                    stop_loss_pts=5.0,
                    target_pts=3.0,
                    entry_reason="Secondary boosters triggered without primary driver initiation",
                    rejection_reasons=["NO_PRIMARY_DRIVER_INITIATED"]
                )
            else:
                primary_sigs = booster_sigs

        # 3. Categorize Primary Signals by Direction
        ce_primaries = [s for s in primary_sigs if s.direction == "CE"]
        pe_primaries = [s for s in primary_sigs if s.direction == "PE"]

        conflict_detected = False
        selected_primaries: List[OpportunitySignal] = []
        selected_direction: Optional[str] = None

        # 4. Conflict Resolution (CE vs PE simultaneously in primary drivers)
        if ce_primaries and pe_primaries:
            conflict_detected = True
            ce_max_conf = max(s.confidence for s in ce_primaries)
            pe_max_conf = max(s.confidence for s in pe_primaries)

            vwap = float(indicators.get("vwap", 0.0))
            spot = primary_sigs[0].reference_price
            price_above_vwap = spot > vwap
            ema_bullish = bool(indicators.get("ema_bullish", False))
            ema_bearish = bool(indicators.get("ema_bearish", False))

            if ce_max_conf >= pe_max_conf + 5.0 and (price_above_vwap or ema_bullish):
                selected_primaries = ce_primaries
                selected_direction = "CE"
                rejection_reasons.append("CONFLICT_RESOLVED_CE_DOMINANT")
            elif pe_max_conf >= ce_max_conf + 5.0 and (not price_above_vwap or ema_bearish):
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
                    reference_spot=spot,
                    stop_loss_pts=5.0,
                    target_pts=3.0,
                    entry_reason="Conflicting simultaneous CE & PE primary signals without clear resolution",
                    rejection_reasons=["REJECTED_EQUAL_OPPOSING_SIGNALS"],
                    conflict_detected=True
                )
        elif ce_primaries:
            selected_primaries = ce_primaries
            selected_direction = "CE"
        else:
            selected_primaries = pe_primaries
            selected_direction = "PE"

        # 5. Rank Primary Signals & Merge Duplicates
        selected_primaries.sort(key=lambda s: s.confidence, reverse=True)
        best_primary = selected_primaries[0]
        base_confidence = best_primary.confidence

        # 6. Apply Secondary Boosters
        aligned_boosters = [b for b in booster_sigs if b.direction == selected_direction]
        opposing_boosters = [b for b in booster_sigs if b.direction != selected_direction]

        final_score = base_confidence
        # Add boost for each aligned booster
        if aligned_boosters:
            final_score += (len(aligned_boosters) * self.booster_boost_pts)
        # Deduct penalty if an opposing booster is firing
        if opposing_boosters:
            final_score -= (len(opposing_boosters) * self.opposing_penalty_pts)

        # 6B. Apply Heavyweight Alignment Booster & Chop Filter (Big 3: HDFC, Reliance, ICICI)
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

            # Divergence Trap (Reliance vs HDFC Tug-of-War chop)
            if getattr(heavyweight_eval, "is_divergence_trap", False):
                pen_trap = getattr(heavyweight_eval, "divergence_trap_penalty", 10.0)
                final_score -= pen_trap
                rejection_reasons.append("HEAVYWEIGHT_DIVERGENCE_CHOP_WARNING")

        # Cap between 0 and 99
        final_score = min(99.0, max(0.0, final_score))

        # Dynamic Target Expansion for Super Trend / Fast Heavyweight Movers
        target_pts = 3.0
        if heavyweight_eval is not None and getattr(heavyweight_eval, "is_fast_mover", False):
            if getattr(heavyweight_eval, "fast_move_direction", None) == selected_direction:
                target_pts = float(getattr(heavyweight_eval, "expanded_target_pts", 15.0))
                heavyweight_factors.append(f"SUPER_TREND_TARGET_EXPANSION (+{target_pts:.0f} pts)")

        # 7. Minimum Confidence Gate (Default >= 80.0)
        if final_score < self.min_confidence_threshold:
            return ArbitratedDecision(
                should_execute=False,
                direction=None,
                primary_strategy=best_primary.strategy_name,
                contributing_strategies=[best_primary.strategy_name] + [b.strategy_name for b in aligned_boosters],
                combined_confidence=round(final_score, 1),
                reference_spot=best_primary.reference_price,
                stop_loss_pts=best_primary.stop_loss_pts,
                target_pts=target_pts,
                entry_reason=f"Arbitrated confidence {final_score:.1f} below minimum threshold {self.min_confidence_threshold:.1f}",
                rejection_reasons=rejection_reasons + [f"CONFIDENCE_BELOW_{int(self.min_confidence_threshold)}"]
            )

        # Compile Contributing Factors and Description
        contributing_names = [best_primary.strategy_name]
        for p in selected_primaries[1:]:
            if p.strategy_name not in contributing_names:
                contributing_names.append(p.strategy_name)
        for b in aligned_boosters:
            if b.strategy_name not in contributing_names:
                contributing_names.append(f"{b.strategy_name} [BOOSTER]")
        for h in heavyweight_factors:
            if h not in contributing_names:
                contributing_names.append(h)

        entry_description = f"[{best_primary.strategy_name}] {best_primary.entry_condition}"
        boost_parts = [b.strategy_name for b in aligned_boosters] + heavyweight_factors
        if boost_parts:
            entry_description += f" (Boosted by: {', '.join(boost_parts)})"

        duplicate_merged = (len(selected_primaries) > 1 or len(aligned_boosters) > 0)

        return ArbitratedDecision(
            should_execute=True,
            direction=selected_direction,
            primary_strategy=best_primary.strategy_name,
            contributing_strategies=contributing_names,
            combined_confidence=round(final_score, 1),
            reference_spot=best_primary.reference_price,
            stop_loss_pts=best_primary.stop_loss_pts,
            target_pts=target_pts,
            entry_reason=entry_description,
            rejection_reasons=rejection_reasons,
            duplicate_merged=duplicate_merged,
            conflict_detected=conflict_detected
        )
