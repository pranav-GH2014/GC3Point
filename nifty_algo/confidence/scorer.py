from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
from ..strategies.base_setup import SetupSignal
from ..config.config_loader import AppConfig

@dataclass
class ConfidenceEvaluation:
    total_score: float
    is_eligible: bool
    status: str  # 'ELIGIBLE' (>=80), 'WAIT_CONFIRMATION' (70-79), 'NO_TRADE' (<70)
    direction: Optional[str]  # 'BULLISH' or 'BEARISH'
    breakdown: Dict[str, float]
    vetoes: List[str]
    momentum_override_active: bool

class ConfidenceScorer:
    """
    100-Point Confidence Engine:
    Evaluates multi-timeframe structure, setups, indicators, liquidity, and volume.
    Integrates Section 14 Momentum Override for rapid moves > 50 points.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.weights = config.confidence.weights
        self.min_entry_score = config.confidence.min_entry_score
        self.wait_zone_score = config.confidence.wait_zone_min_score

    def check_momentum_override(self, df_1m: pd.DataFrame) -> Tuple[bool, Optional[str], float]:
        """
        Detects rapid move > 50 points in <= 5 minutes window (configurable).
        Returns (is_override, direction, points_moved).
        """
        if not self.config.momentum_override.enabled or len(df_1m) < self.config.momentum_override.rapid_move_window_minutes:
            return False, None, 0.0

        window = self.config.momentum_override.rapid_move_window_minutes
        recent = df_1m.iloc[-window:]
        net_move = recent["close"].iloc[-1] - recent["open"].iloc[0]
        abs_move = abs(net_move)

        if abs_move >= self.config.momentum_override.rapid_move_points:
            # Check for move exhaustion (if current bar is an opposite reversal wick, do not chase)
            curr = recent.iloc[-1]
            if net_move > 0 and (curr["high"] - curr["close"]) > 0.6 * (curr["high"] - curr["low"]):
                return False, None, abs_move  # Exhaustion wick at top
            if net_move < 0 and (curr["close"] - curr["low"]) > 0.6 * (curr["high"] - curr["low"]):
                return False, None, abs_move  # Exhaustion wick at bottom

            direction = "BULLISH" if net_move > 0 else "BEARISH"
            return True, direction, abs_move

        return False, None, abs_move

    def score(
        self,
        signals: List[SetupSignal],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        volume_profile: Dict[str, Any],
        oi_data: Dict[str, Any],
        df_1m: pd.DataFrame
    ) -> ConfidenceEvaluation:
        breakdown: Dict[str, float] = {}
        vetoes: List[str] = []

        # Find triggered setups
        triggered = [s for s in signals if s.triggered]
        if not triggered:
            # Check momentum override
            override, m_dir, m_pts = self.check_momentum_override(df_1m)
            if not override:
                return ConfidenceEvaluation(
                    total_score=0.0,
                    is_eligible=False,
                    status="NO_TRADE",
                    direction=None,
                    breakdown={},
                    vetoes=["No setup triggered and no momentum override"],
                    momentum_override_active=False
                )
            primary_direction = m_dir
            momentum_active = True
        else:
            primary_direction = triggered[0].direction
            momentum_active = False

        # 1. Market Direction and Structure (Weight: 20)
        s_score = 0.0
        if primary_direction == "BULLISH":
            if structure.get("has_sufficient_room_ce"):
                s_score += 12.0
            else:
                vetoes.append("Insufficient room to next resistance (< 15 pts)")
            if indicators.get("current_price", 0) > structure.get("orb_high", 0):
                s_score += 8.0
            elif indicators.get("current_price", 0) > structure.get("cdl", 0):
                s_score += 4.0
        elif primary_direction == "BEARISH":
            if structure.get("has_sufficient_room_pe"):
                s_score += 12.0
            else:
                vetoes.append("Insufficient room to next support (< 15 pts)")
            if indicators.get("current_price", 0) < structure.get("orb_low", 0):
                s_score += 8.0
            elif indicators.get("current_price", 0) < structure.get("cdh", 0):
                s_score += 4.0
        breakdown["market_structure"] = min(s_score, self.weights["market_structure"])

        # 2. Breakout and False Breakout Analysis (Weight: 15)
        b_score = 0.0
        if any(s.setup_id in ("SETUP_1_BREAKOUT_RETEST", "SETUP_6_ORB_BREAKOUT") and s.triggered for s in signals):
            b_score += 15.0
        elif any(s.triggered for s in signals):
            b_score += 10.0
        breakdown["breakout_and_false_breakout"] = min(b_score, self.weights["breakout_and_false_breakout"])

        # 3. Liquidity and FVG (Weight: 10)
        l_score = 0.0
        if any(s.setup_id == "SETUP_2_LIQUIDITY_SWEEP_REVERSAL" and s.triggered for s in signals):
            l_score += 10.0
        # FVG confirmation check
        fvg_signal = next((s for s in signals if s.setup_id == "SETUP_9_FVG_CONFIRMATION"), None)
        if fvg_signal and fvg_signal.direction == primary_direction:
            l_score = min(10.0, l_score + 5.0)
        breakdown["liquidity_and_fvg"] = min(l_score, self.weights["liquidity_and_fvg"])

        # 4. Candle Confirmation (Weight: 10)
        c_score = 8.0 if any(s.setup_id in ("SETUP_7_SUPPORT_REVERSAL", "SETUP_8_RESISTANCE_REJECTION") and s.triggered for s in signals) else 5.0
        breakdown["candle_confirmation"] = min(c_score, self.weights["candle_confirmation"])

        # 5. EMA and VWAP (Weight: 10)
        ev_score = 0.0
        if primary_direction == "BULLISH":
            if indicators.get("ema_bullish"):
                ev_score += 5.0
            if indicators.get("price_above_vwap"):
                ev_score += 5.0
        elif primary_direction == "BEARISH":
            if indicators.get("ema_bearish"):
                ev_score += 5.0
            if indicators.get("price_below_vwap"):
                ev_score += 5.0
        breakdown["ema_and_vwap"] = min(ev_score, self.weights["ema_and_vwap"])

        # 6. ADX and Momentum (Weight: 10)
        adx_score = 0.0
        adx_regime = indicators.get("adx_regime", "WEAK_SIDEWAYS")
        if adx_regime == "STRONG_TREND":
            adx_score = 10.0
        elif adx_regime == "MODERATE_TREND":
            adx_score = 8.0
        elif momentum_active:
            adx_score = 9.0  # Section 14 momentum override
        else:
            adx_score = 2.0
            if indicators.get("adx", 14.0) < 12.0:
                vetoes.append("ADX < 12 (Severe flat market)")
        breakdown["adx_and_momentum"] = min(adx_score, self.weights["adx_and_momentum"])

        # 7. Volume Profile (Weight: 10)
        vp_score = 7.0 if volume_profile.get("poc") else 4.0
        breakdown["volume_profile"] = min(vp_score, self.weights["volume_profile"])

        # 8. Open Interest & Breadth (Weight: 10)
        oi_bias = oi_data.get("oi_bias", "NEUTRAL")
        oi_score = 8.0 if (primary_direction == "BULLISH" and oi_bias == "BULLISH_PE_WRITING") or \
                          (primary_direction == "BEARISH" and oi_bias == "BEARISH_CE_WRITING") else 5.0
        breakdown["open_interest_and_breadth"] = min(oi_score, self.weights["open_interest_and_breadth"])

        # 9. VIX, Time, and News (Weight: 5)
        breakdown["vix_time_and_news"] = 4.0

        total_score = round(sum(breakdown.values()), 1)

        # Status determination per Section 15
        if total_score >= self.min_entry_score and len(vetoes) == 0:
            status = "ELIGIBLE"
            is_eligible = True
        elif total_score >= self.wait_zone_score:
            status = "WAIT_CONFIRMATION"
            is_eligible = False
        else:
            status = "NO_TRADE"
            is_eligible = False

        return ConfidenceEvaluation(
            total_score=total_score,
            is_eligible=is_eligible,
            status=status,
            direction=primary_direction,
            breakdown=breakdown,
            vetoes=vetoes,
            momentum_override_active=momentum_active
        )
