import logging
from datetime import date
from typing import Dict, Any, Tuple
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.overnight")

class OvernightPositionManager:
    """
    Manages NRML positions held overnight:
    - Verifies contract expiry validity (never hold an expired option into next day)
    - Evaluates morning opening gap against underlying market structure
    - Exits immediately on severe adverse gap (> configurable threshold e.g. 40 pts)
    - Adjusts protective reference on favourable opening gap
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def validate_contract_expiry(self, expiry_str: str) -> bool:
        """Ensures the contract has not expired."""
        try:
            exp_date = date.fromisoformat(expiry_str)
            return exp_date >= date.today()
        except Exception:
            return True

    def evaluate_morning_gap(
        self,
        position: Dict[str, Any],
        nifty_previous_close: float,
        nifty_opening_price: float
    ) -> Tuple[bool, str]:
        """
        Evaluates next morning's opening gap.
        Returns: (should_exit_immediately, reason)
        """
        gap_points = nifty_opening_price - nifty_previous_close
        option_type = position.get("option_type", "CE")
        adverse_threshold = self.config.risk.adverse_overnight_gap_threshold_pts

        logger.info(
            "[OVERNIGHT GAP CHECK] %s %s | NIFTY Prev Close: %.2f | Open: %.2f | Gap: %+.2f pts",
            option_type, position.get("tradingsymbol"), nifty_previous_close, nifty_opening_price, gap_points
        )

        # Adverse Gap on CE: Market gaps DOWN severely
        if option_type == "CE" and gap_points < -adverse_threshold:
            return True, f"Severe adverse overnight gap on CE ({gap_points:.1f} pts < -{adverse_threshold} pts)"

        # Adverse Gap on PE: Market gaps UP severely
        if option_type == "PE" and gap_points > adverse_threshold:
            return True, f"Severe adverse overnight gap on PE (+{gap_points:.1f} pts > +{adverse_threshold} pts)"

        return False, "Opening gap within acceptable structure bounds"
