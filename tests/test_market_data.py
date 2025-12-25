"""Tests for market data module."""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from packages.schemas.market_data import (
    MarketSnapshot,
    MarketBar,
    MarketDataRequest,
    BarDataRequest,
)
from packages.market_data import (
    MarketDataCache,
    CachedMarketDataProvider,
)


class TestMarketSnapshot:
    """Test MarketSnapshot schema."""
    
    def test_create_snapshot(self):
        """Test creating market snapshot."""
        snapshot = MarketSnapshot(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            bid=Decimal("175.50"),
            ask=Decimal("175.55"),
            last=Decimal("175.52"),
            volume=1500000,
        )
        
        assert snapshot.instrument == "AAPL"
        assert snapshot.bid == Decimal("175.50")
        assert snapshot.ask == Decimal("175.55")
        assert snapshot.mid == Decimal("175.525")  # Auto-calculated
    
    def test_snapshot_mid_calculation(self):
        """Test mid-price auto-calculation."""
        snapshot = MarketSnapshot(
            instrument="SPY",
            timestamp=datetime.utcnow(),
            bid=Decimal("460.00"),
            ask=Decimal("460.10"),
            last=Decimal("460.05"),
            volume=1000000,
        )
        
        assert snapshot.mid == Decimal("460.05")
    
    def test_snapshot_validation_positive_price(self):
        """Test validation of positive prices."""
        with pytest.raises(ValueError, match="Price must be positive"):
            MarketSnapshot(
                instrument="TEST",
                timestamp=datetime.utcnow(),
                bid=Decimal("-10"),
                ask=Decimal("10"),
                last=Decimal("10"),
                volume=100,
            )
    
    def test_snapshot_validation_non_negative_volume(self):
        """Test validation of non-negative volume."""
        with pytest.raises(ValueError, match="Size/volume must be non-negative"):
            MarketSnapshot(
                instrument="TEST",
                timestamp=datetime.utcnow(),
                bid=Decimal("10"),
                ask=Decimal("11"),
                last=Decimal("10.5"),
                volume=-1000,
            )


class TestMarketBar:
    """Test MarketBar schema."""
    
    def test_create_bar(self):
        """Test creating market bar."""
        bar = MarketBar(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            timeframe="1h",
            open=Decimal("175.00"),
            high=Decimal("176.50"),
            low=Decimal("174.80"),
            close=Decimal("176.20"),
            volume=250000,
        )
        
        assert bar.instrument == "AAPL"
        assert bar.timeframe == "1h"
        assert bar.open == Decimal("175.00")
        assert bar.high == Decimal("176.50")
        assert bar.low == Decimal("174.80")
        assert bar.close == Decimal("176.20")
    
    def test_bar_ohlc_validation_high(self):
        """Test OHLC validation for high price."""
        with pytest.raises(ValueError, match="High must be >= open"):
            MarketBar(
                instrument="TEST",
                timestamp=datetime.utcnow(),
                timeframe="1h",
                open=Decimal("100"),
                high=Decimal("95"),  # Invalid: high < open
                low=Decimal("90"),
                close=Decimal("98"),
                volume=1000,
            )
    
    def test_bar_ohlc_validation_low(self):
        """Test OHLC validation for low price."""
        with pytest.raises(ValueError, match="Low must be <= open"):
            MarketBar(
                instrument="TEST",
                timestamp=datetime.utcnow(),
                timeframe="1h",
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("105"),  # Invalid: low > open
                close=Decimal("108"),
                volume=1000,
            )


class TestBarDataRequest:
    """Test BarDataRequest schema."""
    
    def test_create_request(self):
        """Test creating bar data request."""
        request = BarDataRequest(
            instrument="AAPL",
            timeframe="1h",
            limit=100,
        )
        
        assert request.instrument == "AAPL"
        assert request.timeframe == "1h"
        assert request.limit == 100
        assert request.rth_only is True
    
    def test_date_range_validation(self):
        """Test date range validation."""
        start = datetime.utcnow()
        end = start - timedelta(hours=1)  # End before start
        
        with pytest.raises(ValueError, match="End time must be >= start time"):
            BarDataRequest(
                instrument="TEST",
                timeframe="1h",
                start=start,
                end=end,
            )


class TestMarketDataCache:
    """Test MarketDataCache."""
    
    def test_cache_snapshot(self):
        """Test caching snapshot data."""
        cache = MarketDataCache(snapshot_ttl_seconds=10)
        
        snapshot = MarketSnapshot(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            bid=Decimal("175.50"),
            ask=Decimal("175.55"),
            last=Decimal("175.52"),
            volume=1000000,
        )
        
        # Cache snapshot
        cache.set_snapshot("AAPL", snapshot)
        
        # Retrieve from cache
        cached = cache.get_snapshot("AAPL")
        assert cached is not None
        assert cached.instrument == "AAPL"
        assert cached.bid == Decimal("175.50")
    
    def test_cache_miss(self):
        """Test cache miss."""
        cache = MarketDataCache()
        
        cached = cache.get_snapshot("NONEXISTENT")
        assert cached is None
    
    def test_cache_expiration(self):
        """Test cache expiration."""
        import time
        
        cache = MarketDataCache(snapshot_ttl_seconds=1)
        
        snapshot = MarketSnapshot(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            bid=Decimal("175.50"),
            ask=Decimal("175.55"),
            last=Decimal("175.52"),
            volume=1000000,
        )
        
        cache.set_snapshot("AAPL", snapshot)
        
        # Should be cached
        cached = cache.get_snapshot("AAPL")
        assert cached is not None
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should be expired
        cached = cache.get_snapshot("AAPL")
        assert cached is None
    
    def test_cache_bars(self):
        """Test caching bar data."""
        cache = MarketDataCache(bars_ttl_seconds=300)
        
        bars = [
            MarketBar(
                instrument="AAPL",
                timestamp=datetime.utcnow() - timedelta(hours=i),
                timeframe="1h",
                open=Decimal("175.00"),
                high=Decimal("176.00"),
                low=Decimal("174.00"),
                close=Decimal("175.50"),
                volume=100000,
            )
            for i in range(5)
        ]
        
        start = datetime.utcnow() - timedelta(hours=6)
        end = datetime.utcnow()
        
        cache.set_bars("AAPL", "1h", start, end, bars)
        
        cached = cache.get_bars("AAPL", "1h", start, end)
        assert cached is not None
        assert len(cached) == 5
    
    def test_cache_clear(self):
        """Test cache clearing."""
        cache = MarketDataCache()
        
        snapshot = MarketSnapshot(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            bid=Decimal("175.50"),
            ask=Decimal("175.55"),
            last=Decimal("175.52"),
            volume=1000000,
        )
        
        cache.set_snapshot("AAPL", snapshot)
        assert cache.get_snapshot("AAPL") is not None
        
        cache.clear()
        assert cache.get_snapshot("AAPL") is None
    
    def test_cache_stats(self):
        """Test cache statistics."""
        cache = MarketDataCache()
        
        snapshot = MarketSnapshot(
            instrument="AAPL",
            timestamp=datetime.utcnow(),
            bid=Decimal("175.50"),
            ask=Decimal("175.55"),
            last=Decimal("175.52"),
            volume=1000000,
        )
        
        cache.set_snapshot("AAPL", snapshot)
        cache.set_snapshot("SPY", snapshot)
        
        stats = cache.get_stats()
        assert stats["snapshot_count"] == 2
        assert stats["bars_count"] == 0
        assert stats["total_size"] == 2


class MockMarketDataProvider:
    """Mock market data provider for testing."""
    
    def __init__(self):
        self.snapshot_calls = 0
        self.bars_calls = 0
    
    def get_snapshot(self, instrument, fields=None):
        self.snapshot_calls += 1
        return MarketSnapshot(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=Decimal("100.00"),
            ask=Decimal("100.10"),
            last=Decimal("100.05"),
            volume=1000000,
        )
    
    def get_bars(self, instrument, timeframe, start=None, end=None, limit=100, rth_only=True):
        self.bars_calls += 1
        return [
            MarketBar(
                instrument=instrument,
                timestamp=datetime.utcnow() - timedelta(hours=i),
                timeframe=timeframe,
                open=Decimal("100.00"),
                high=Decimal("101.00"),
                low=Decimal("99.00"),
                close=Decimal("100.50"),
                volume=100000,
            )
            for i in range(min(limit, 10))
        ]


class TestCachedMarketDataProvider:
    """Test CachedMarketDataProvider."""
    
    def test_cache_hit_snapshot(self):
        """Test cache hit for snapshot."""
        mock_provider = MockMarketDataProvider()
        cached_provider = CachedMarketDataProvider(mock_provider)
        
        # First call - should hit provider
        snapshot1 = cached_provider.get_snapshot("AAPL")
        assert mock_provider.snapshot_calls == 1
        
        # Second call - should hit cache
        snapshot2 = cached_provider.get_snapshot("AAPL")
        assert mock_provider.snapshot_calls == 1  # No additional call
        
        assert snapshot1.instrument == snapshot2.instrument
    
    def test_cache_bypass(self):
        """Test bypassing cache."""
        mock_provider = MockMarketDataProvider()
        cached_provider = CachedMarketDataProvider(mock_provider)
        
        # Bypass cache
        snapshot1 = cached_provider.get_snapshot("AAPL", use_cache=False)
        snapshot2 = cached_provider.get_snapshot("AAPL", use_cache=False)
        
        assert mock_provider.snapshot_calls == 2  # Both calls hit provider
    
    def test_cache_hit_bars(self):
        """Test cache hit for bars."""
        mock_provider = MockMarketDataProvider()
        cached_provider = CachedMarketDataProvider(mock_provider)
        
        start = datetime.utcnow() - timedelta(hours=24)
        end = datetime.utcnow()
        
        # First call - should hit provider
        bars1 = cached_provider.get_bars("AAPL", "1h", start, end)
        assert mock_provider.bars_calls == 1
        
        # Second call - should hit cache
        bars2 = cached_provider.get_bars("AAPL", "1h", start, end)
        assert mock_provider.bars_calls == 1  # No additional call
        
        assert len(bars1) == len(bars2)
    
    def test_clear_cache(self):
        """Test clearing cache."""
        mock_provider = MockMarketDataProvider()
        cached_provider = CachedMarketDataProvider(mock_provider)
        
        # Cache snapshot
        cached_provider.get_snapshot("AAPL")
        assert mock_provider.snapshot_calls == 1
        
        # Hit cache
        cached_provider.get_snapshot("AAPL")
        assert mock_provider.snapshot_calls == 1
        
        # Clear cache
        cached_provider.clear_cache()
        
        # Should hit provider again
        cached_provider.get_snapshot("AAPL")
        assert mock_provider.snapshot_calls == 2
