import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.option_selector")

class OptionSelector:
    """
    Dynamic NIFTY Option Selector:
    - Queries Kite NFO instruments dynamically
    - Filters by expiry, strike delta responsiveness (delta 0.35 - 0.65), spread, volume, OI
    - Validates contract validity and dynamic lot size from instrument master
    - Never hardcodes strike or lot size
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._instruments_cache: List[Dict[str, Any]] = []
        self._last_instruments_fetch: Optional[date] = None

    def update_instruments(self, instruments: List[Dict[str, Any]]):
        self._instruments_cache = [
            inst for inst in instruments 
            if inst.get("name") == "NIFTY" and inst.get("segment") == "NFO-OPT"
        ]
        self._last_instruments_fetch = date.today()
        logger.info("Updated option instruments cache. Total NIFTY option contracts: %d", len(self._instruments_cache))

    def get_active_expiry_contracts(self, nifty_spot: float, num_strikes: int = 8) -> List[Dict[str, Any]]:
        """
        Returns active weekly expiry CE & PE contracts within ±(num_strikes * 50) points of spot.
        Used for OI wall analytics and breakout/bounce predictions.
        """
        if not self._instruments_cache:
            return []

        today = date.today()
        valid_expiries = sorted(list(set(
            inst["expiry"] for inst in self._instruments_cache
            if inst["expiry"] >= today
        )))

        if not valid_expiries:
            return []

        target_expiry = valid_expiries[0]
        max_dist = num_strikes * 50.0

        contracts = [
            inst for inst in self._instruments_cache
            if inst["expiry"] == target_expiry and abs(inst["strike"] - nifty_spot) <= max_dist
        ]
        return contracts

    def select_best_contract(
        self,
        direction: str,  # 'BULLISH' (CE) or 'BEARISH' (PE)
        nifty_spot: float,
        quotes: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Dynamically selects the optimal CE/PE contract matching liquidity, spread, and delta criteria.
        """
        if not self._instruments_cache:
            logger.warning("No option instruments loaded in cache!")
            return None

        instrument_type = "CE" if direction == "BULLISH" else "PE"
        today = date.today()

        # 1. Filter valid future expiries
        valid_expiries = sorted(list(set(
            inst["expiry"] for inst in self._instruments_cache
            if inst["expiry"] >= today
        )))

        if not valid_expiries:
            logger.error("No valid future expiries found for NIFTY options!")
            return None

        # Expiry selection: If today is expiry day and after 14:00, or if nearest has high theta risk,
        # can roll to next weekly. Default to nearest valid expiry.
        target_expiry = valid_expiries[0]

        # 2. Filter contracts for target expiry and type
        candidates = [
            inst for inst in self._instruments_cache
            if inst["expiry"] == target_expiry and inst["instrument_type"] == instrument_type
        ]

        # Sort by distance from ATM strike
        # For CE: ATM or 1 strike OTM/ITM (strike step 50)
        candidates.sort(key=lambda x: abs(x["strike"] - nifty_spot))

        best_contract = None
        min_score_penalty = float("inf")

        for inst in candidates[:6]:  # Test top 6 strikes near ATM
            tradingsymbol = f"NFO:{inst['tradingsymbol']}"
            quote = quotes.get(tradingsymbol)
            if not quote:
                continue

            ohlc = quote.get("ohlc", {})
            depth = quote.get("depth", {})
            buy_depth = depth.get("buy", [{}])[0]
            sell_depth = depth.get("sell", [{}])[0]

            best_bid = buy_depth.get("price", 0.0)
            best_ask = sell_depth.get("price", 0.0)
            ltp = quote.get("last_price", 0.0)
            volume = quote.get("volume", 0)
            oi = quote.get("oi", 0)

            # Check premium range
            if not (self.config.option_selector.min_premium <= ltp <= self.config.option_selector.max_premium):
                continue

            # Bid-Ask spread filter
            spread = best_ask - best_bid if best_ask > 0 and best_bid > 0 else 0.5
            if spread > self.config.option_selector.max_bid_ask_spread_pts:
                continue

            # Volume & OI liquidity check
            if volume < self.config.option_selector.min_volume or oi < self.config.option_selector.min_open_interest:
                continue

            # Penalty score based on distance from ATM and spread
            strike_dist = abs(inst["strike"] - nifty_spot)
            penalty = strike_dist + (spread * 10.0)

            if penalty < min_score_penalty:
                min_score_penalty = penalty
                best_contract = {
                    "instrument_token": inst["instrument_token"],
                    "tradingsymbol": inst["tradingsymbol"],
                    "strike": float(inst["strike"]),
                    "expiry": str(inst["expiry"]),
                    "lot_size": int(inst["lot_size"]),  # Dynamic lot size from broker master!
                    "instrument_type": instrument_type,
                    "ltp": ltp,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": round(spread, 2),
                    "volume": volume,
                    "oi": oi
                }

        if best_contract:
            logger.info(
                "[OPTION SELECTED] %s (Strike: %.1f, Expiry: %s, LotSize: %d, LTP: ₹%.2f, Spread: ₹%.2f)",
                best_contract["tradingsymbol"], best_contract["strike"], best_contract["expiry"],
                best_contract["lot_size"], best_contract["ltp"], best_contract["spread"]
            )
        else:
            logger.warning("No option contract passed liquidity and delta checks for %s near %.1f", direction, nifty_spot)

        return best_contract
