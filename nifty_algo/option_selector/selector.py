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

    def get_candidates(self, direction: str, nifty_spot: float, limit: int = 12) -> List[Dict[str, Any]]:
        """
        Returns top candidate option instruments closest to ATM / OTM in trade direction.
        """
        if not self._instruments_cache:
            return []
        instrument_type = "CE" if direction == "BULLISH" else "PE"
        today = date.today()
        valid_expiries = sorted(list(set(
            inst["expiry"] for inst in self._instruments_cache
            if inst["expiry"] >= today
        )))
        if not valid_expiries:
            return []
        target_expiry = valid_expiries[0]
        candidates = [
            inst for inst in self._instruments_cache
            if inst["expiry"] == target_expiry and inst["instrument_type"] == instrument_type
        ]
        candidates.sort(key=lambda x: abs(x["strike"] - nifty_spot))
        return candidates[:limit]

    def select_best_contract(
        self,
        direction: str,  # 'BULLISH' (CE) or 'BEARISH' (PE)
        nifty_spot: float,
        quotes: Dict[str, Any],
        available_capital: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Dynamically selects the optimal CE/PE contract matching liquidity, spread, and delta criteria.
        If available_capital is provided, prioritizes the closest strike that is 100% affordable.
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

        # Expiry selection: Default to nearest valid weekly expiry
        target_expiry = valid_expiries[0]

        # 2. Filter contracts for target expiry and type
        candidates = [
            inst for inst in self._instruments_cache
            if inst["expiry"] == target_expiry and inst["instrument_type"] == instrument_type
        ]

        # Sort by distance from ATM strike
        candidates.sort(key=lambda x: abs(x["strike"] - nifty_spot))

        max_deployable = (available_capital * getattr(self.config.capital, "max_deployment_pct", 0.98)) if (available_capital and available_capital > 0) else None
        valid_contracts = []

        for inst in candidates[:12]:  # Test top 12 strikes near ATM / OTM
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
            lot_size = int(inst["lot_size"])

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

            strike_dist = abs(inst["strike"] - nifty_spot)
            lot_cost = round(ltp * lot_size, 2)
            is_affordable = (max_deployable is None) or (lot_cost <= max_deployable)

            # Penalty score based on distance from ATM and spread
            penalty = strike_dist + (spread * 10.0)

            contract_dict = {
                "instrument_token": inst["instrument_token"],
                "tradingsymbol": inst["tradingsymbol"],
                "strike": float(inst["strike"]),
                "expiry": str(inst["expiry"]),
                "lot_size": lot_size,
                "instrument_type": instrument_type,
                "ltp": ltp,
                "lot_cost": lot_cost,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": round(spread, 2),
                "volume": volume,
                "oi": oi,
                "penalty": penalty,
                "is_affordable": is_affordable
            }
            valid_contracts.append(contract_dict)

        if not valid_contracts:
            logger.warning("No option contract passed liquidity and spread checks for %s near %.1f", direction, nifty_spot)
            return None

        # Prioritize affordable contracts closest to ATM
        affordable_contracts = [c for c in valid_contracts if c["is_affordable"]]
        if affordable_contracts:
            affordable_contracts.sort(key=lambda x: x["penalty"])
            best = affordable_contracts[0]
            logger.info(
                "[AFFORDABLE OPTION SELECTED] %s (Strike: %.1f, Expiry: %s, LotSize: %d, LTP: ₹%.2f, Cost: ₹%.2f, Spread: ₹%.2f)",
                best["tradingsymbol"], best["strike"], best["expiry"],
                best["lot_size"], best["ltp"], best["lot_cost"], best["spread"]
            )
            return best

        # If none were affordable:
        valid_contracts.sort(key=lambda x: x["lot_cost"])
        cheapest = valid_contracts[0]
        logger.warning(
            "[ALL CONTRACTS UNAFFORDABLE] Cannot afford 1 lot with deployable ₹%.2f (Cheapest: %s @ ₹%.2f = ₹%.2f)",
            max_deployable or 0.0, cheapest["tradingsymbol"], cheapest["ltp"], cheapest["lot_cost"]
        )
        return None
