"""
Market data provider with caching and staleness detection.

Provides:
- Real-time market snapshots (bid/ask/last/mid/volume)
- Historical OHLCV bars with multiple timeframes
- In-memory caching with TTL (time-to-live)
- Staleness detection and automatic refresh
- Thread-safe cache management
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Protocol, Dict, List
from threading import Lock
from collections import deque

from packages.schemas.market_data import (
    MarketSnapshot,
    MarketBar,
    TimeframeType,
)


class MarketDataProvider(Protocol):
    """
    Protocol for market data retrieval.
    
    Implementations should provide real-time snapshots and historical bars.
    Used by BrokerAdapter implementations to separate market data concerns.
    """
    
    def get_snapshot(
        self,
        instrument: str,
        fields: Optional[List[str]] = None
    ) -> MarketSnapshot:
        """
        Get current market snapshot for an instrument.
        
        Args:
            instrument: Instrument identifier (symbol)
            fields: Optional list of specific fields to retrieve
                   (e.g., ["bid", "ask", "last"])
        
        Returns:
            MarketSnapshot with current market data
        
        Raises:
            ValueError: If instrument is invalid or not found
        """
        ...
    
    def get_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        rth_only: bool = True
    ) -> List[MarketBar]:
        """
        Get historical OHLCV bars for an instrument.
        
        Args:
            instrument: Instrument identifier (symbol)
            timeframe: Bar timeframe (e.g., "1m", "1h", "1d")
            start: Start time (UTC), default: 24 hours ago
            end: End time (UTC), default: now
            limit: Maximum number of bars to return (1-5000)
            rth_only: Regular trading hours only
        
        Returns:
            List of MarketBar sorted by timestamp (oldest first)
        
        Raises:
            ValueError: If parameters are invalid
        """
        ...


class CachedMarketData:
    """
    Cached market data with timestamp and TTL.
    """
    
    def __init__(self, data: MarketSnapshot | List[MarketBar], ttl_seconds: int):
        self.data = data
        self.cached_at = time.time()
        self.ttl_seconds = ttl_seconds
    
    def is_stale(self) -> bool:
        """Check if cached data has exceeded TTL."""
        return time.time() - self.cached_at > self.ttl_seconds
    
    def age_seconds(self) -> float:
        """Get age of cached data in seconds."""
        return time.time() - self.cached_at


class MarketDataCache:
    """
    Thread-safe market data cache with TTL and staleness detection.
    
    Separate TTLs for snapshots (short) and bars (longer).
    Automatic cleanup of expired entries.
    """
    
    def __init__(
        self,
        snapshot_ttl_seconds: int = 5,
        bars_ttl_seconds: int = 300,
        max_cache_size: int = 1000
    ):
        """
        Initialize market data cache.
        
        Args:
            snapshot_ttl_seconds: TTL for snapshot data (default: 5s)
            bars_ttl_seconds: TTL for bar data (default: 300s = 5 min)
            max_cache_size: Maximum number of cached entries
        """
        self.snapshot_ttl = snapshot_ttl_seconds
        self.bars_ttl = bars_ttl_seconds
        self.max_cache_size = max_cache_size
        
        self._snapshot_cache: Dict[str, CachedMarketData] = {}
        self._bars_cache: Dict[str, CachedMarketData] = {}
        self._access_order: deque = deque(maxlen=max_cache_size)
        self._lock = Lock()
    
    def get_snapshot(self, instrument: str) -> Optional[MarketSnapshot]:
        """
        Get cached snapshot if available and not stale.
        
        Args:
            instrument: Instrument identifier
        
        Returns:
            MarketSnapshot if cached and fresh, None otherwise
        """
        with self._lock:
            cached = self._snapshot_cache.get(instrument)
            if cached and not cached.is_stale():
                self._access_order.append(("snapshot", instrument))
                return cached.data
            elif cached:
                # Remove stale entry
                del self._snapshot_cache[instrument]
            return None
    
    def set_snapshot(self, instrument: str, snapshot: MarketSnapshot) -> None:
        """
        Cache snapshot data.
        
        Args:
            instrument: Instrument identifier
            snapshot: MarketSnapshot to cache
        """
        with self._lock:
            self._snapshot_cache[instrument] = CachedMarketData(
                snapshot, self.snapshot_ttl
            )
            self._access_order.append(("snapshot", instrument))
            self._evict_if_needed()
    
    def get_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime],
        end: Optional[datetime]
    ) -> Optional[List[MarketBar]]:
        """
        Get cached bars if available and not stale.
        
        Args:
            instrument: Instrument identifier
            timeframe: Bar timeframe
            start: Start time
            end: End time
        
        Returns:
            List of MarketBar if cached and fresh, None otherwise
        """
        cache_key = self._make_bars_key(instrument, timeframe, start, end)
        
        with self._lock:
            cached = self._bars_cache.get(cache_key)
            if cached and not cached.is_stale():
                self._access_order.append(("bars", cache_key))
                return cached.data
            elif cached:
                # Remove stale entry
                del self._bars_cache[cache_key]
            return None
    
    def set_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime],
        end: Optional[datetime],
        bars: List[MarketBar]
    ) -> None:
        """
        Cache bar data.
        
        Args:
            instrument: Instrument identifier
            timeframe: Bar timeframe
            start: Start time
            end: End time
            bars: List of MarketBar to cache
        """
        cache_key = self._make_bars_key(instrument, timeframe, start, end)
        
        with self._lock:
            self._bars_cache[cache_key] = CachedMarketData(
                bars, self.bars_ttl
            )
            self._access_order.append(("bars", cache_key))
            self._evict_if_needed()
    
    def _make_bars_key(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime],
        end: Optional[datetime]
    ) -> str:
        """Create cache key for bars request."""
        start_str = start.isoformat() if start else "None"
        end_str = end.isoformat() if end else "None"
        return f"{instrument}:{timeframe}:{start_str}:{end_str}"
    
    def _evict_if_needed(self) -> None:
        """Evict least recently used entries if cache is full."""
        total_size = len(self._snapshot_cache) + len(self._bars_cache)
        
        while total_size > self.max_cache_size and self._access_order:
            cache_type, key = self._access_order.popleft()
            
            if cache_type == "snapshot" and key in self._snapshot_cache:
                del self._snapshot_cache[key]
                total_size -= 1
            elif cache_type == "bars" and key in self._bars_cache:
                del self._bars_cache[key]
                total_size -= 1
    
    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._snapshot_cache.clear()
            self._bars_cache.clear()
            self._access_order.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            return {
                "snapshot_count": len(self._snapshot_cache),
                "bars_count": len(self._bars_cache),
                "total_size": len(self._snapshot_cache) + len(self._bars_cache),
                "max_size": self.max_cache_size
            }


class CachedMarketDataProvider:
    """
    Market data provider with automatic caching.
    
    Wraps any MarketDataProvider implementation and adds transparent caching
    with staleness detection and automatic refresh.
    """
    
    def __init__(
        self,
        provider: MarketDataProvider,
        cache: Optional[MarketDataCache] = None
    ):
        """
        Initialize cached market data provider.
        
        Args:
            provider: Underlying market data provider
            cache: Optional cache instance (creates default if None)
        """
        self.provider = provider
        self.cache = cache or MarketDataCache()
    
    def get_snapshot(
        self,
        instrument: str,
        fields: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> MarketSnapshot:
        """
        Get market snapshot with optional caching.
        
        Args:
            instrument: Instrument identifier
            fields: Optional list of specific fields
            use_cache: Whether to use cache (default: True)
        
        Returns:
            MarketSnapshot from cache or provider
        """
        # Check cache first
        if use_cache:
            cached = self.cache.get_snapshot(instrument)
            if cached is not None:
                return cached
        
        # Fetch from provider
        snapshot = self.provider.get_snapshot(instrument, fields)
        
        # Cache result
        if use_cache:
            self.cache.set_snapshot(instrument, snapshot)
        
        return snapshot
    
    def get_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        rth_only: bool = True,
        use_cache: bool = True
    ) -> List[MarketBar]:
        """
        Get historical bars with optional caching.
        
        Args:
            instrument: Instrument identifier
            timeframe: Bar timeframe
            start: Start time (UTC)
            end: End time (UTC)
            limit: Maximum number of bars
            rth_only: Regular trading hours only
            use_cache: Whether to use cache (default: True)
        
        Returns:
            List of MarketBar from cache or provider
        """
        # Check cache first
        if use_cache:
            cached = self.cache.get_bars(instrument, timeframe, start, end)
            if cached is not None:
                return cached
        
        # Fetch from provider
        bars = self.provider.get_bars(
            instrument, timeframe, start, end, limit, rth_only
        )
        
        # Cache result
        if use_cache:
            self.cache.set_bars(instrument, timeframe, start, end, bars)
        
        return bars
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache.clear()
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return self.cache.get_stats()


# Singleton cache instance
_global_cache: Optional[MarketDataCache] = None


def get_global_cache() -> MarketDataCache:
    """Get or create global market data cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = MarketDataCache()
    return _global_cache
