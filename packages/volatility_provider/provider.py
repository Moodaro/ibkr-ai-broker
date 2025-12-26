"""
Volatility provider protocol and data models.

Defines interface for volatility data sources.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol


@dataclass
class VolatilityData:
    """
    Volatility metrics for an instrument.
    
    Contains realized (historical) and/or implied volatility,
    along with beta for beta-adjusted calculations.
    """
    
    symbol: str
    timestamp: datetime
    
    # Realized volatility (annualized, from historical returns)
    realized_volatility: Optional[float] = None  # e.g., 0.25 = 25%
    
    # Implied volatility (from options market)
    implied_volatility: Optional[float] = None  # e.g., 0.30 = 30%
    
    # Beta vs market (for beta-adjusted volatility)
    beta: Optional[float] = None  # e.g., 1.2
    
    # Market volatility (e.g., VIX/100)
    market_volatility: Optional[float] = None  # e.g., 0.20 = 20%
    
    # Number of days used for calculation (for realized vol)
    lookback_days: Optional[int] = None
    
    # Data source metadata
    source: Optional[str] = None  # e.g., "historical", "yfinance", "ibkr"
    
    def get_effective_volatility(self) -> Optional[float]:
        """
        Get best available volatility estimate.
        
        Priority:
        1. Realized volatility (most reliable for liquid stocks)
        2. Implied volatility (if available)
        3. Beta-adjusted market volatility
        
        Returns:
            Annualized volatility or None if no data available
        """
        if self.realized_volatility is not None:
            return self.realized_volatility
        
        if self.implied_volatility is not None:
            return self.implied_volatility
        
        if self.beta is not None and self.market_volatility is not None:
            return self.beta * self.market_volatility
        
        return None


class VolatilityProvider(Protocol):
    """
    Protocol for volatility data retrieval.
    
    Implementations provide volatility metrics from various sources:
    - Historical: Calculate from price history
    - Implied: Extract from options market
    - Mock: Fixed values for testing
    """
    
    def get_volatility(
        self,
        symbol: str,
        lookback_days: int = 30,
    ) -> Optional[VolatilityData]:
        """
        Get volatility data for a symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "AAPL")
            lookback_days: Number of days for historical calculation
        
        Returns:
            VolatilityData or None if unavailable
        
        Raises:
            ValueError: If symbol is invalid
        """
        ...
    
    def get_market_volatility(self) -> Optional[float]:
        """
        Get current market volatility (e.g., VIX/100).
        
        Returns:
            Market volatility (annualized) or None if unavailable
        """
        ...
