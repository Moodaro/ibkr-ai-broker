"""Trade simulator package.

Provides deterministic order simulation for pre-execution validation.
"""

from packages.trade_sim.models import (
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
)
from packages.trade_sim.simulator import TradeSimulator

__all__ = [
    "SimulationConfig",
    "SimulationResult",
    "SimulationStatus",
    "TradeSimulator",
]
