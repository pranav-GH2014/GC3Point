import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("nifty_algo.heavyweights")

# Standard NSE Instrument Tokens for Big 3 NIFTY Movers
DEFAULT_HDFCBANK_TOKEN = 341249   # ~11.5% Weight
DEFAULT_RELIANCE_TOKEN = 738561   # ~9.2% Weight
DEFAULT_ICICIBANK_TOKEN = 1270529  # ~7.8% Weight

@dataclass
class StockSnapshot:
    symbol: str
    token: int
    weight_pct: float
    ltp: float = 0.0
    open: float = 0.0
    vwap: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    change_pct: float = 0.0
    bias: str = "NEUTRAL"  # 'BULLISH', 'BEARISH', 'NEUTRAL'

@dataclass
class HeavyweightEvaluationResult:
    is_bullish_aligned: bool = False       # All 3 Bullish (LTP > VWAP & Open)
    is_bearish_aligned: bool = False       # All 3 Bearish (LTP < VWAP & Open)
    is_partial_bullish: bool = False       # 2 of 3 Bullish, 0 Bearish
    is_partial_bearish: bool = False       # 2 of 3 Bearish, 0 Bullish
    is_divergence_trap: bool = False       # Reliance opposing HDFCBANK (Sideways Chop Trap)
    is_fast_mover: bool = False            # All 3 surging/dumping with high velocity
    expanded_target_pts: float = 15.0      # Option target expanded to +15.0 pts
    fast_move_direction: Optional[str] = None  # 'CE' or 'PE'
    alignment_boost: float = 10.0          # Confidence boost for full alignment
    partial_boost: float = 5.0             # Confidence boost for partial alignment
    divergence_trap_penalty: float = 10.0  # Penalty deducted during chop trap
    opposing_penalty: float = 15.0         # Penalty deducted when entering against Big 3
    summary: str = "NEUTRAL"
    details: Dict[str, Any] = field(default_factory=dict)

class HeavyweightAlignmentEngine:
    """
    Monitors the Top 3 NIFTY 50 Heavyweights (HDFCBANK, RELIANCE, ICICIBANK)
    which collectively represent ~28.5% of index weight.

    Core Quantitative Rules:
    1. Full Alignment (+10 pts Boost):
       - If all 3 are above VWAP & Open -> CE Scalps receive +10 pt boost, PE penalized -15 pts.
       - If all 3 are below VWAP & Open -> PE Scalps receive +10 pt boost, CE penalized -15 pts.
    2. Divergence Trap (-10 pts Chop Penalty):
       - If Reliance is Bullish and HDFCBANK is Bearish (or vice-versa), they cancel each other out.
       - Index enters sideways chop -> -10 pt penalty prevents false breakout entries.
    3. Safe Fallback:
       - If live stock data is unavailable, engine returns neutral without blocking execution.
    """

    def __init__(
        self,
        hdfc_token: int = DEFAULT_HDFCBANK_TOKEN,
        reliance_token: int = DEFAULT_RELIANCE_TOKEN,
        icici_token: int = DEFAULT_ICICIBANK_TOKEN,
        alignment_boost_pts: float = 10.0,
        partial_boost_pts: float = 5.0,
        divergence_trap_penalty_pts: float = 10.0,
        opposing_penalty_pts: float = 15.0,
        fast_move_target_pts: float = 15.0,
    ):
        self.hdfc_token = hdfc_token
        self.reliance_token = reliance_token
        self.icici_token = icici_token

        self.alignment_boost_pts = alignment_boost_pts
        self.partial_boost_pts = partial_boost_pts
        self.divergence_trap_penalty_pts = divergence_trap_penalty_pts
        self.opposing_penalty_pts = opposing_penalty_pts
        self.fast_move_target_pts = fast_move_target_pts

        self.token_to_symbol = {
            self.hdfc_token: "HDFCBANK",
            self.reliance_token: "RELIANCE",
            self.icici_token: "ICICIBANK",
        }

        self.stocks: Dict[str, StockSnapshot] = {
            "HDFCBANK": StockSnapshot("HDFCBANK", self.hdfc_token, weight_pct=11.5),
            "RELIANCE": StockSnapshot("RELIANCE", self.reliance_token, weight_pct=9.2),
            "ICICIBANK": StockSnapshot("ICICIBANK", self.icici_token, weight_pct=7.8),
        }

    def get_tracked_tokens(self) -> List[int]:
        """Returns the list of instrument tokens to subscribe to in KiteTicker."""
        return [self.hdfc_token, self.reliance_token, self.icici_token]

    def on_tick(self, tick: Dict[str, Any]):
        """Processes an incoming tick from Kite WebSocket for tracked heavyweights."""
        token = tick.get("instrument_token")
        if token not in self.token_to_symbol:
            return

        symbol = self.token_to_symbol[token]
        stock = self.stocks[symbol]

        ltp = tick.get("last_price", stock.ltp)
        ohlc = tick.get("ohlc", {})
        open_price = ohlc.get("open", stock.open)
        day_high = ohlc.get("high", stock.day_high)
        day_low = ohlc.get("low", stock.day_low)

        # Kite provides average_price (VWAP) directly in full/quote mode ticks
        avg_price = tick.get("average_price", stock.vwap)
        if avg_price <= 0:
            avg_price = open_price if open_price > 0 else ltp

        stock.ltp = ltp
        stock.open = open_price if open_price > 0 else ltp
        stock.vwap = avg_price if avg_price > 0 else ltp
        stock.day_high = max(day_high, ltp) if day_high > 0 else ltp
        stock.day_low = min(day_low, ltp) if day_low > 0 else ltp

        if stock.open > 0:
            stock.change_pct = round(((stock.ltp - stock.open) / stock.open) * 100.0, 2)

        # Calculate individual bias
        is_above_vwap = stock.ltp > stock.vwap
        is_above_open = stock.ltp >= stock.open

        if is_above_vwap and is_above_open:
            stock.bias = "BULLISH"
        elif not is_above_vwap and not is_above_open:
            stock.bias = "BEARISH"
        else:
            stock.bias = "NEUTRAL"

    def update_snapshot(
        self,
        symbol: str,
        ltp: float,
        vwap: float,
        open_price: float,
        day_high: Optional[float] = None,
        day_low: Optional[float] = None
    ):
        """Allows direct programmatic update for backtesting or REST quote polling."""
        if symbol not in self.stocks:
            return
        stock = self.stocks[symbol]
        stock.ltp = ltp
        stock.vwap = vwap if vwap > 0 else ltp
        stock.open = open_price if open_price > 0 else ltp
        stock.day_high = day_high if day_high is not None else ltp
        stock.day_low = day_low if day_low is not None else ltp

        if stock.open > 0:
            stock.change_pct = round(((stock.ltp - stock.open) / stock.open) * 100.0, 2)

        is_above_vwap = stock.ltp > stock.vwap
        is_above_open = stock.ltp >= stock.open

        if is_above_vwap and is_above_open:
            stock.bias = "BULLISH"
        elif not is_above_vwap and not is_above_open:
            stock.bias = "BEARISH"
        else:
            stock.bias = "NEUTRAL"

    def evaluate(self) -> HeavyweightEvaluationResult:
        """
        Evaluates the aggregate alignment across HDFCBANK, RELIANCE, and ICICIBANK.
        """
        # Ensure we have active data for at least 2 of the 3 stocks
        active_stocks = [s for s in self.stocks.values() if s.ltp > 0]
        if len(active_stocks) < 2:
            return HeavyweightEvaluationResult(
                summary="INSUFFICIENT_HEAVYWEIGHT_DATA",
                details={s.symbol: {"ltp": s.ltp, "bias": s.bias} for s in self.stocks.values()}
            )

        hdfc = self.stocks["HDFCBANK"]
        reliance = self.stocks["RELIANCE"]
        icici = self.stocks["ICICIBANK"]

        bullish_stocks = [s.symbol for s in self.stocks.values() if s.bias == "BULLISH"]
        bearish_stocks = [s.symbol for s in self.stocks.values() if s.bias == "BEARISH"]

        bull_count = len(bullish_stocks)
        bear_count = len(bearish_stocks)

        # Check Divergence Trap: Reliance strongly opposing HDFCBANK (The Midday Tug-of-War)
        is_divergence_trap = False
        if (hdfc.bias == "BULLISH" and reliance.bias == "BEARISH") or \
           (hdfc.bias == "BEARISH" and reliance.bias == "BULLISH"):
            is_divergence_trap = True

        is_bullish_aligned = (bull_count == 3)
        is_bearish_aligned = (bear_count == 3)
        is_partial_bullish = (bull_count == 2 and bear_count == 0)
        is_partial_bearish = (bear_count == 2 and bull_count == 0)

        details = {
            s.symbol: {
                "ltp": s.ltp,
                "vwap": s.vwap,
                "open": s.open,
                "change_pct": s.change_pct,
                "bias": s.bias,
                "weight": s.weight_pct
            }
            for s in self.stocks.values()
        }

        if is_bullish_aligned:
            summary = f"FULL_BULLISH_ALIGNMENT (All 3 > VWAP: HDFC {hdfc.change_pct}%, REL {reliance.change_pct}%, ICICI {icici.change_pct}%)"
        elif is_bearish_aligned:
            summary = f"FULL_BEARISH_ALIGNMENT (All 3 < VWAP: HDFC {hdfc.change_pct}%, REL {reliance.change_pct}%, ICICI {icici.change_pct}%)"
        elif is_divergence_trap:
            summary = f"DIVERGENCE_CHOP_TRAP (Reliance {reliance.bias} vs HDFC {hdfc.bias})"
        elif is_partial_bullish:
            summary = f"PARTIAL_BULLISH (2/3 Bullish: {', '.join(bullish_stocks)})"
        elif is_partial_bearish:
            summary = f"PARTIAL_BEARISH (2/3 Bearish: {', '.join(bearish_stocks)})"
        else:
            summary = "MIXED_NEUTRAL"

        # Check Fast Mover / High Velocity Super Trend
        is_fast_mover = False
        fast_move_dir = None
        if is_bullish_aligned:
            avg_change = (hdfc.change_pct + reliance.change_pct + icici.change_pct) / 3.0
            all_at_highs = all(s.ltp >= (s.day_high * 0.998) for s in self.stocks.values() if s.day_high > 0)
            if avg_change >= 0.4 or all_at_highs:
                is_fast_mover = True
                fast_move_dir = "CE"
        elif is_bearish_aligned:
            avg_change = (hdfc.change_pct + reliance.change_pct + icici.change_pct) / 3.0
            all_at_lows = all(s.ltp <= (s.day_low * 1.002) for s in self.stocks.values() if s.day_low > 0)
            if avg_change <= -0.4 or all_at_lows:
                is_fast_mover = True
                fast_move_dir = "PE"

        if is_fast_mover:
            summary = f"SUPER_TREND_FAST_MOVE (+{self.fast_move_target_pts:.0f} PT RUNNER) | {summary}"

        return HeavyweightEvaluationResult(
            is_bullish_aligned=is_bullish_aligned,
            is_bearish_aligned=is_bearish_aligned,
            is_partial_bullish=is_partial_bullish,
            is_partial_bearish=is_partial_bearish,
            is_divergence_trap=is_divergence_trap,
            is_fast_mover=is_fast_mover,
            expanded_target_pts=self.fast_move_target_pts,
            fast_move_direction=fast_move_dir,
            alignment_boost=self.alignment_boost_pts,
            partial_boost=self.partial_boost_pts,
            divergence_trap_penalty=self.divergence_trap_penalty_pts,
            opposing_penalty=self.opposing_penalty_pts,
            summary=summary,
            details=details
        )
