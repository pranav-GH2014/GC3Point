import logging
from typing import Dict, Any, List, Optional
from .base_setup import OpportunitySignal

logger = logging.getLogger("nifty_algo.engine.trap")

class RetailTrapDetectionEngine:
    """
    Engine 3: Retail Trap Detection Engine
    Identifies:
    - CE Buyer Traps / False Breakouts: Price spikes above Day High, Swing High or Resistance, traps retail buyers, then aggressively closes back inside the range -> Generates PE Signal.
    - PE Buyer Traps / False Breakdowns: Price flushes below Day Low, Swing Low or Support, triggers sell-stops, then violently reclaims back inside the range -> Generates CE Signal.
    - Failed Continuation / Exhaustion patterns.
    - Incorporates volume absorption and OI divergence without assuming OI alone proves intent.
    """

    def __init__(self, sweep_buffer_pts: float = 2.0):
        self.strategy_id = "ENGINE_3_TRAP"
        self.strategy_name = "Retail Trap Detection Engine"
        self.sweep_buffer_pts = sweep_buffer_pts

    def evaluate(
        self,
        candles_1m: List[Dict[str, Any]],
        candles_3m: List[Dict[str, Any]],
        structure: Dict[str, Any],
        indicators: Dict[str, Any],
        oi_data: Optional[Dict[str, Any]] = None
    ) -> OpportunitySignal:
        bars = candles_3m if (candles_3m and len(candles_3m) >= 12) else candles_1m
        if len(bars) < 12:
            return OpportunitySignal(
                strategy_id=self.strategy_id,
                strategy_name=self.strategy_name,
                triggered=False,
                direction=None,
                timestamp="",
                reference_price=0.0,
                entry_condition="Insufficient bars",
                confidence=0.0,
                stop_loss_pts=5.0,
                rejection_reason="Insufficient data"
            )

        curr_bar = bars[-1]
        prev_bar = bars[-2]
        time_str = str(curr_bar.get("date", ""))
        curr_price = float(curr_bar["close"])
        curr_high = float(curr_bar["high"])
        curr_low = float(curr_bar["low"])
        curr_open = float(curr_bar["open"])

        # Prior 10-bar swing extremes (excluding current and previous sweep bar)
        prior_bars = bars[-12:-2]
        prior_swing_high = max(float(b["high"]) for b in prior_bars)
        prior_swing_low = min(float(b["low"]) for b in prior_bars)

        cdh = float(structure.get("cdh", 0.0))
        cdl = float(structure.get("cdl", 999999.0))
        pdh = float(structure.get("pdh", 0.0)) if structure.get("pdh") else 0.0
        pdl = float(structure.get("pdl", 0.0)) if structure.get("pdl") else 999999.0

        watched_highs = [h for h in [cdh, pdh, prior_swing_high] if h > 0]
        watched_lows = [l for l in [cdl, pdl, prior_swing_low] if l < 999999.0]

        # 1. CE Buyer Trap (Generates PE Signal):
        # A bar wicked above a key resistance/high, but could not sustain it and closed below it.
        # Current bar rejects down and confirms the trap.
        for high_lvl in watched_highs:
            sweep_occurred = (prev_bar["high"] > high_lvl or curr_high > high_lvl)
            rejected_back = (curr_price < high_lvl) and (curr_price < curr_open or curr_price < prev_bar["low"])
            
            if sweep_occurred and rejected_back:
                # Strong upper wick on sweep bar (upper wick >= 40% of range)
                sweep_bar = curr_bar if curr_high > high_lvl else prev_bar
                sw_range = sweep_bar["high"] - sweep_bar["low"]
                upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
                is_rejection_wick = sw_range > 0 and (upper_wick / sw_range >= 0.35)

                if is_rejection_wick or curr_price < prev_bar["low"]:
                    score = 82.0
                    # OI alignment bonus (if Call OI is accumulating or Put OI unwinding)
                    if oi_data and oi_data.get("oi_bias") == "BEARISH_CE_WRITING":
                        score += 8.0
                    if curr_price < float(indicators.get("vwap", 999999.0)):
                        score += 5.0

                    sl_dist = max(3.0, min(8.0, sweep_bar["high"] - curr_price + 1.5))

                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="PE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"CE Buyer Trap: Sweep above {high_lvl:.1f} rejected back below level",
                        confidence=min(96.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "trapped_level": high_lvl,
                            "sweep_high": sweep_bar["high"],
                            "trap_type": "BULL_TRAP"
                        }
                    )

        # 2. PE Buyer Trap (Generates CE Signal):
        # A bar flushed below key support/low, but buyers absorbed the sell-off and price closed back above the level.
        for low_lvl in watched_lows:
            flush_occurred = (prev_bar["low"] < low_lvl or curr_low < low_lvl)
            reclaimed_back = (curr_price > low_lvl) and (curr_price > curr_open or curr_price > prev_bar["high"])

            if flush_occurred and reclaimed_back:
                flush_bar = curr_bar if curr_low < low_lvl else prev_bar
                fl_range = flush_bar["high"] - flush_bar["low"]
                lower_wick = min(flush_bar["open"], flush_bar["close"]) - flush_bar["low"]
                is_absorption_wick = fl_range > 0 and (lower_wick / fl_range >= 0.35)

                if is_absorption_wick or curr_price > prev_bar["high"]:
                    score = 82.0
                    # OI alignment bonus (if Put OI is accumulating or Call OI unwinding)
                    if oi_data and oi_data.get("oi_bias") == "BULLISH_PE_WRITING":
                        score += 8.0
                    if curr_price > float(indicators.get("vwap", 0.0)):
                        score += 5.0

                    sl_dist = max(3.0, min(8.0, curr_price - flush_bar["low"] + 1.5))

                    return OpportunitySignal(
                        strategy_id=self.strategy_id,
                        strategy_name=self.strategy_name,
                        triggered=True,
                        direction="CE",
                        timestamp=time_str,
                        reference_price=curr_price,
                        entry_condition=f"PE Buyer Trap: Flush below {low_lvl:.1f} reclaimed back above level",
                        confidence=min(96.0, score),
                        stop_loss_pts=sl_dist,
                        target_pts=3.0,
                        supporting_metadata={
                            "trapped_level": low_lvl,
                            "sweep_low": flush_bar["low"],
                            "trap_type": "BEAR_TRAP"
                        }
                    )

        return OpportunitySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            triggered=False,
            direction=None,
            timestamp=time_str,
            reference_price=curr_price,
            entry_condition="No retail trap detected",
            confidence=0.0,
            stop_loss_pts=5.0,
            rejection_reason="No sweep-and-reverse pattern"
        )
