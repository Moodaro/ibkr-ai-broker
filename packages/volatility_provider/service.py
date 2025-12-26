"""
Volatility service with caching and fallback logic.

Wraps volatility providers with error handling, caching, and graceful degradation.
"""

import time
from datetime import datetime
from typing import Dict, Optional
from threading import Lock

from .provider import VolatilityData, VolatilityProvider


class CachedVolatility:
    """Cached volatility data with TTL."""
    
    def __init__(self, data: VolatilityData, ttl_seconds: int = 3600):
        self.data = data
        self.cached_at = time.time()
        self.ttl_seconds = ttl_seconds
    
    def is_stale(self) -> bool:
        """Check if cached data is stale."""
        return (time.time() - self.cached_at) > self.ttl_seconds


class VolatilityService:
    """
    Volatility service with caching, fallback, and error handling.
    
    Features:
    - In-memory cache with TTL
    - Primary + fallback providers
    - Graceful degradation
    - Thread-safe operations
    """
    
    def __init__(
        self,
        primary_provider: VolatilityProvider,
        fallback_provider: Optional[VolatilityProvider] = None,
        cache_ttl_seconds: int = 3600,  # 1 hour default
    ):
        """
        Initialize volatility service.
        
        Args:
            primary_provider: Primary volatility provider (e.g., historical)
            fallback_provider: Fallback provider (e.g., mock with defaults)
            cache_ttl_seconds: Cache TTL in seconds (default: 3600)
        """
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.cache_ttl_seconds = cache_ttl_seconds
        
        # Cache: symbol -> CachedVolatility
        self._cache: Dict[str, CachedVolatility] = {}
        self._lock = Lock()
        
        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.primary_successes = 0
        self.fallback_uses = 0
    
    def get_volatility(
        self,
        symbol: str,
        lookback_days: int = 30,
        use_cache: bool = True,
    ) -> Optional[VolatilityData]:
        """
        Get volatility data with caching and fallback.
        
        Args:
            symbol: Instrument symbol
            lookback_days: Number of days for calculation
            use_cache: Whether to use cache (default: True)
        
        Returns:
            VolatilityData or None if all providers fail
        """
        with self._lock:
            # Check cache first
            if use_cache and symbol in self._cache:
                cached = self._cache[symbol]
                if not cached.is_stale():
                    self.cache_hits += 1
                    return cached.data
            
            self.cache_misses += 1
        
        # Try primary provider
        try:
            data = self.primary_provider.get_volatility(symbol, lookback_days)
            if data is not None:
                with self._lock:
                    self.primary_successes += 1
                    if use_cache:
                        self._cache[symbol] = CachedVolatility(data, self.cache_ttl_seconds)
                return data
        except Exception:
            # Primary provider failed, try fallback
            pass
        
        # Try fallback provider
        if self.fallback_provider is not None:
            try:
                data = self.fallback_provider.get_volatility(symbol, lookback_days)
                if data is not None:
                    with self._lock:
                        self.fallback_uses += 1
                        # Cache fallback data with shorter TTL
                        if use_cache:
                            self._cache[symbol] = CachedVolatility(
                                data, self.cache_ttl_seconds // 2
                            )
                    return data
            except Exception:
                pass
        
        # All providers failed
        return None
    
    def get_market_volatility(self) -> Optional[float]:
        """
        Get market volatility with fallback.
        
        Returns:
            Market volatility or None if unavailable
        """
        # Try primary provider
        try:
            vol = self.primary_provider.get_market_volatility()
            if vol is not None:
                return vol
        except Exception:
            pass
        
        # Try fallback
        if self.fallback_provider is not None:
            try:
                return self.fallback_provider.get_market_volatility()
            except Exception:
                pass
        
        return None
    
    def clear_cache(self) -> None:
        """Clear all cached volatility data."""
        with self._lock:
            self._cache.clear()
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns:
            Dict with hits, misses, hit rate, etc.
        """
        with self._lock:
            total_requests = self.cache_hits + self.cache_misses
            hit_rate = (
                (self.cache_hits / total_requests * 100)
                if total_requests > 0
                else 0.0
            )
            
            return {
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "hit_rate_pct": round(hit_rate, 2),
                "cached_symbols": len(self._cache),
                "primary_successes": self.primary_successes,
                "fallback_uses": self.fallback_uses,
            }
