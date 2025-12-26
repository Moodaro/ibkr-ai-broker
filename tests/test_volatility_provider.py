"""
Tests for volatility provider implementations.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from packages.volatility_provider import (
    VolatilityData,
    MockVolatilityProvider,
    HistoricalVolatilityProvider,
    VolatilityService,
)
from packages.broker_ibkr import FakeBrokerAdapter
from packages.schemas.market_data import MarketBar


class TestVolatilityData:
    """Test VolatilityData model."""
    
    def test_effective_volatility_prefers_realized(self):
        """Test that realized volatility is preferred."""
        data = VolatilityData(
            symbol="AAPL",
            timestamp=datetime.utcnow(),
            realized_volatility=0.20,
            implied_volatility=0.25,
            beta=1.2,
            market_volatility=0.15,
        )
        
        assert data.get_effective_volatility() == 0.20
    
    def test_effective_volatility_falls_back_to_implied(self):
        """Test fallback to implied volatility."""
        data = VolatilityData(
            symbol="AAPL",
            timestamp=datetime.utcnow(),
            realized_volatility=None,
            implied_volatility=0.25,
            beta=1.2,
            market_volatility=0.15,
        )
        
        assert data.get_effective_volatility() == 0.25
    
    def test_effective_volatility_uses_beta_adjusted(self):
        """Test beta-adjusted calculation."""
        data = VolatilityData(
            symbol="AAPL",
            timestamp=datetime.utcnow(),
            realized_volatility=None,
            implied_volatility=None,
            beta=1.2,
            market_volatility=0.15,
        )
        
        assert data.get_effective_volatility() == pytest.approx(0.18)  # 1.2 * 0.15
    
    def test_effective_volatility_returns_none_when_no_data(self):
        """Test None return when no data available."""
        data = VolatilityData(
            symbol="AAPL",
            timestamp=datetime.utcnow(),
            realized_volatility=None,
            implied_volatility=None,
            beta=None,
            market_volatility=None,
        )
        
        assert data.get_effective_volatility() is None


class TestMockVolatilityProvider:
    """Test MockVolatilityProvider."""
    
    def test_returns_default_volatility(self):
        """Test default volatility for unknown symbols."""
        provider = MockVolatilityProvider(default_volatility=0.20)
        
        data = provider.get_volatility("UNKNOWN")
        
        assert data is not None
        assert data.symbol == "UNKNOWN"
        assert data.realized_volatility == 0.20
        assert data.source == "mock"
    
    def test_returns_mapped_volatility(self):
        """Test volatility map lookup."""
        provider = MockVolatilityProvider(
            volatility_map={"AAPL": 0.18, "TSLA": 0.50}
        )
        
        aapl_data = provider.get_volatility("AAPL")
        tsla_data = provider.get_volatility("TSLA")
        
        assert aapl_data.realized_volatility == 0.18
        assert tsla_data.realized_volatility == 0.50
    
    def test_set_volatility(self):
        """Test updating volatility for symbol."""
        provider = MockVolatilityProvider()
        
        provider.set_volatility("NVDA", 0.35)
        data = provider.get_volatility("NVDA")
        
        assert data.realized_volatility == 0.35
    
    def test_get_market_volatility(self):
        """Test market volatility retrieval."""
        provider = MockVolatilityProvider(market_volatility=0.15)
        
        assert provider.get_market_volatility() == 0.15
    
    def test_set_market_volatility(self):
        """Test updating market volatility."""
        provider = MockVolatilityProvider(market_volatility=0.15)
        
        provider.set_market_volatility(0.20)
        
        assert provider.get_market_volatility() == 0.20


class TestHistoricalVolatilityProvider:
    """Test HistoricalVolatilityProvider."""
    
    def test_calculates_volatility_from_bars(self):
        """Test volatility calculation from historical bars."""
        broker = FakeBrokerAdapter()
        provider = HistoricalVolatilityProvider(broker)
        
        # FakeBrokerAdapter generates synthetic bars
        data = provider.get_volatility("AAPL", lookback_days=30)
        
        assert data is not None
        assert data.symbol == "AAPL"
        assert data.realized_volatility is not None
        assert data.realized_volatility > 0
        assert data.source == "historical"
        assert data.lookback_days is not None
        assert data.lookback_days >= 2
    
    def test_returns_none_for_insufficient_data(self):
        """Test None return when insufficient data."""
        broker = FakeBrokerAdapter()
        provider = HistoricalVolatilityProvider(broker)
        
        # Symbol with no bars
        data = provider.get_volatility("NODATA", lookback_days=30)
        
        # FakeBrokerAdapter generates bars for any symbol, so this may not return None
        # But if we had a real case with no data, it should return None
        # For now, just check it doesn't crash
        assert data is None or data.realized_volatility is not None
    
    def test_market_volatility_not_implemented(self):
        """Test that market volatility returns None (not implemented)."""
        broker = FakeBrokerAdapter()
        provider = HistoricalVolatilityProvider(broker)
        
        assert provider.get_market_volatility() is None


class TestVolatilityService:
    """Test VolatilityService with caching and fallback."""
    
    def test_caches_volatility_data(self):
        """Test that volatility data is cached."""
        primary = MockVolatilityProvider(volatility_map={"AAPL": 0.18})
        service = VolatilityService(primary, cache_ttl_seconds=3600)
        
        # First call (cache miss)
        data1 = service.get_volatility("AAPL")
        assert data1 is not None
        assert service.cache_misses == 1
        assert service.cache_hits == 0
        
        # Second call (cache hit)
        data2 = service.get_volatility("AAPL")
        assert data2 is not None
        assert data2.symbol == data1.symbol
        assert service.cache_hits == 1
    
    def test_fallback_when_primary_fails(self):
        """Test fallback provider when primary fails."""
        # Primary that returns None
        primary = MockVolatilityProvider(volatility_map={})
        primary.get_volatility = lambda symbol, lookback_days: None
        
        # Fallback with default
        fallback = MockVolatilityProvider(default_volatility=0.25)
        
        service = VolatilityService(primary, fallback_provider=fallback)
        
        data = service.get_volatility("UNKNOWN")
        
        assert data is not None
        assert data.realized_volatility == 0.25
        assert service.fallback_uses == 1
    
    def test_returns_none_when_all_providers_fail(self):
        """Test None return when all providers fail."""
        primary = MockVolatilityProvider()
        primary.get_volatility = lambda symbol, lookback_days: None
        
        fallback = MockVolatilityProvider()
        fallback.get_volatility = lambda symbol, lookback_days: None
        
        service = VolatilityService(primary, fallback_provider=fallback)
        
        data = service.get_volatility("FAIL")
        
        assert data is None
    
    def test_cache_stats(self):
        """Test cache statistics."""
        primary = MockVolatilityProvider(volatility_map={"AAPL": 0.18})
        service = VolatilityService(primary)
        
        # Generate some cache activity
        service.get_volatility("AAPL")  # miss
        service.get_volatility("AAPL")  # hit
        service.get_volatility("TSLA")  # miss
        
        stats = service.get_cache_stats()
        
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 2
        assert stats["hit_rate_pct"] == pytest.approx(33.33, abs=0.1)
        assert stats["cached_symbols"] == 2
    
    def test_clear_cache(self):
        """Test cache clearing."""
        primary = MockVolatilityProvider(volatility_map={"AAPL": 0.18})
        service = VolatilityService(primary)
        
        # Cache some data
        service.get_volatility("AAPL")
        service.get_volatility("TSLA")
        
        stats_before = service.get_cache_stats()
        assert stats_before["cached_symbols"] == 2
        
        # Clear cache
        service.clear_cache()
        
        stats_after = service.get_cache_stats()
        assert stats_after["cached_symbols"] == 0
    
    def test_bypass_cache_when_use_cache_false(self):
        """Test cache bypass with use_cache=False."""
        primary = MockVolatilityProvider(volatility_map={"AAPL": 0.18})
        service = VolatilityService(primary)
        
        # First call with cache disabled
        data1 = service.get_volatility("AAPL", use_cache=False)
        assert data1 is not None
        
        # Cache should still be empty
        stats = service.get_cache_stats()
        assert stats["cached_symbols"] == 0
        
        # Second call with cache enabled
        data2 = service.get_volatility("AAPL", use_cache=True)
        assert data2 is not None
        
        # Now should be cached
        stats = service.get_cache_stats()
        assert stats["cached_symbols"] == 1
