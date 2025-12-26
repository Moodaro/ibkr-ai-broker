"""
Historical volatility provider using market data.

Calculates realized volatility from historical price data.
"""

import math
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from packages.broker_ibkr import BrokerAdapter

from .provider import VolatilityData, VolatilityProvider


class HistoricalVolatilityProvider:
    """
    Calculate realized volatility from historical prices.
    
    Uses log returns and standard deviation with 252 trading days
    annualization factor.
    """
    
    def __init__(
        self,
        broker_adapter: "BrokerAdapter",
        annualization_factor: int = 252,
    ):
        """
        Initialize historical volatility provider.
        
        Args:
            broker_adapter: Broker adapter for fetching market bars
            annualization_factor: Trading days per year (default: 252)
        """
        self.broker_adapter = broker_adapter
        self.annualization_factor = annualization_factor
    
    def get_volatility(
        self,
        symbol: str,
        lookback_days: int = 30,
    ) -> Optional[VolatilityData]:
        """
        Calculate realized volatility from historical prices.
        
        Args:
            symbol: Instrument symbol (e.g., "AAPL")
            lookback_days: Number of days for calculation (default: 30)
        
        Returns:
            VolatilityData with realized volatility or None if insufficient data
        
        Raises:
            ValueError: If broker adapter fails or symbol invalid
        """
        try:
            # Fetch historical bars (daily)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=lookback_days + 5)  # Extra buffer
            
            bars = self.broker_adapter.get_market_bars(
                instrument=symbol,
                timeframe="1d",
                start=start_date,
                end=end_date,
                limit=lookback_days + 5,
                rth_only=True,
            )
            
            if not bars or len(bars) < 2:
                return None
            
            # Calculate log returns
            log_returns = []
            for i in range(1, len(bars)):
                prev_close = float(bars[i - 1].close)
                curr_close = float(bars[i].close)
                
                if prev_close > 0 and curr_close > 0:
                    log_return = math.log(curr_close / prev_close)
                    log_returns.append(log_return)
            
            if len(log_returns) < 2:
                return None
            
            # Calculate standard deviation (sample)
            mean_return = sum(log_returns) / len(log_returns)
            variance = sum((r - mean_return) ** 2 for r in log_returns) / (len(log_returns) - 1)
            std_dev = math.sqrt(variance)
            
            # Annualize volatility
            realized_vol = std_dev * math.sqrt(self.annualization_factor)
            
            return VolatilityData(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                realized_volatility=realized_vol,
                implied_volatility=None,
                beta=None,
                market_volatility=None,
                lookback_days=len(log_returns),
                source="historical",
            )
        
        except Exception:
            # Failed to fetch or calculate volatility
            return None
    
    def get_market_volatility(self) -> Optional[float]:
        """
        Get market volatility (VIX equivalent).
        
        Note: Not implemented for historical provider.
        Real implementation would fetch VIX or calculate SPY volatility.
        
        Returns:
            None (not available from historical data alone)
        """
        # TODO: Implement by fetching VIX or calculating SPY/SPX volatility
        return None
