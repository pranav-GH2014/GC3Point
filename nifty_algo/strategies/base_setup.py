from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class SetupSignal:
    setup_id: str
    setup_name: str
    triggered: bool
    direction: Optional[str]  # 'BULLISH' (Buy CE) or 'BEARISH' (Buy PE)
    confidence: float          # 0.0 to 100.0
    timeframe: str
    entry_level: float
    invalidation_level: float
    reason: str
    supporting_factors: Dict[str, Any]

@dataclass
class OpportunitySignal:
    """
    Standardized independent opportunity signal for the 6 detection engines (Section 6).
    """
    strategy_id: str               # "ENGINE_1_MOMENTUM", etc.
    strategy_name: str             # Human-readable name
    triggered: bool
    direction: Optional[str]       # 'CE' or 'PE'
    timestamp: str                 # Entry timestamp (ISO or HH:MM)
    reference_price: float         # Underlying reference spot price
    entry_condition: str           # Specific trigger rule description
    confidence: float              # 0.0 to 100.0
    stop_loss_pts: float           # Underlying structural SL distance (pts)
    target_pts: float = 3.0        # Fixed +3.0 option premium target
    signal_expiry_seconds: int = 60 # Signal freshness window
    rejection_reason: Optional[str] = None
    supporting_metadata: Dict[str, Any] = field(default_factory=dict)

class BaseSetup(ABC):
    """Abstract base class for all 9 modular trading setups."""

    def __init__(self, setup_id: str, name: str, timeframe: str):
        self.setup_id = setup_id
        self.name = name
        self.timeframe = timeframe

    @abstractmethod
    def evaluate(
        self,
        candles_1m: list,
        candles_3m: list,
        structure: Dict[str, Any],
        indicators: Dict[str, Any]
    ) -> SetupSignal:
        pass
