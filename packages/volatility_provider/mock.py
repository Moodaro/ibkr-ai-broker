"""
Mock volatility provider for testing.

Returns fixed volatility values for symbols.
"""

from datetime import datetime
from typing import Dict, Optional

from .provider import VolatilityData, VolatilityProvider


class MockVolatilityProvider:
    """
    Mock volatility provider with fixed values.
    
    Useful for testing risk engine without external dependencies.
    """
    
    def __init__(
        self,
        volatility_map: Optional[Dict[str, float]] = None,
        default_volatility: float = 0.20,  # 20% default
        market_volatility: float = 0.15,  # 15% VIX equivalent
    ):
        """
        Initialize mock volatility provider.
        
        Args:
            volatility_map: Dict mapping symbol -> annualized volatility
            default_volatility: Default volatility for unknown symbols
            market_volatility: Market volatility (VIX/100 equivalent)
        """
        self.volatility_map = volatility_map or {}
        self.default_volatility = default_volatility
        self.market_volatility_value = market_volatility
    
    def get_volatility(
        self,
        symbol: str,
        lookback_days: int = 30,
    ) -> Optional[VolatilityData]:
        """
        Get mock volatility data for symbol.
        
        Args:
            symbol: Instrument symbol
            lookback_days: Ignored (mock data)
        
        Returns:
            VolatilityData with fixed values
        """
        # Get volatility from map or use default
        realized_vol = self.volatility_map.get(symbol, self.default_volatility)
        
        return VolatilityData(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            realized_volatility=realized_vol,
            implied_volatility=None,  # Not provided by mock
            beta=None,
            market_volatility=self.market_volatility_value,
            lookback_days=lookback_days,
            source="mock",
        )
    
    def get_market_volatility(self) -> Optional[float]:
        """
        Get mock market volatility.
        
        Returns:
            Fixed market volatility
        """
        return self.market_volatility_value
    
    def set_volatility(self, symbol: str, volatility: float) -> None:
        """
        Update volatility for a symbol.
        
        Args:
            symbol: Instrument symbol
            volatility: Annualized volatility (e.g., 0.25 = 25%)
        """
        self.volatility_map[symbol] = volatility
    
    def set_market_volatility(self, volatility: float) -> None:
        """
        Update market volatility.
        
        Args:
            volatility: Market volatility (e.g., 0.15 = 15%)
        """
        self.market_volatility_value = volatility
