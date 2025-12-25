"""Tests for market data API endpoints and FakeBrokerAdapter."""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
from packages.broker_ibkr.fake import FakeBrokerAdapter


class TestFakeBrokerAdapterMarketData:
    """Test market data methods in FakeBrokerAdapter."""
    
    def test_get_market_snapshot_v2(self):
        """Test getting market snapshot with v2 schema."""
        adapter = FakeBrokerAdapter()
        
        snapshot = adapter.get_market_snapshot_v2("AAPL")
        
        assert snapshot.instrument == "AAPL"
        assert snapshot.bid is not None
        assert snapshot.ask is not None
        assert snapshot.bid < snapshot.ask
        assert snapshot.mid is not None
        assert snapshot.volume > 0
    
    def test_get_market_snapshot_v2_multiple_instruments(self):
        """Test snapshots for different instruments."""
        adapter = FakeBrokerAdapter()
        
        aapl = adapter.get_market_snapshot_v2("AAPL")
        spy = adapter.get_market_snapshot_v2("SPY")
        msft = adapter.get_market_snapshot_v2("MSFT")
        
        # Different instruments should have different base prices
        assert aapl.last != spy.last
        assert spy.last != msft.last
    
    def test_get_market_bars(self):
        """Test getting historical bars."""
        adapter = FakeBrokerAdapter()
        
        bars = adapter.get_market_bars(
            instrument="AAPL",
            timeframe="1h",
            limit=10,
        )
        
        assert len(bars) == 10
        for bar in bars:
            assert bar.instrument == "AAPL"
            assert bar.timeframe == "1h"
            assert bar.high >= bar.open
            assert bar.high >= bar.close
            assert bar.low <= bar.open
            assert bar.low <= bar.close
            assert bar.volume > 0
    
    def test_get_market_bars_date_range(self):
        """Test bars with specific date range."""
        adapter = FakeBrokerAdapter()
        
        end = datetime.utcnow()
        start = end - timedelta(hours=5)
        
        bars = adapter.get_market_bars(
            instrument="SPY",
            timeframe="1h",
            start=start,
            end=end,
        )
        
        assert len(bars) > 0
        assert all(start <= bar.timestamp <= end for bar in bars)
    
    def test_get_market_bars_limit(self):
        """Test bars limit parameter."""
        adapter = FakeBrokerAdapter()
        
        bars = adapter.get_market_bars(
            instrument="AAPL",
            timeframe="5m",
            limit=50,
        )
        
        assert len(bars) <= 50
    
    def test_get_market_bars_timeframes(self):
        """Test different timeframes."""
        adapter = FakeBrokerAdapter()
        
        # Use appropriate date ranges for each timeframe
        test_cases = [
            ("1m", timedelta(minutes=10), 5),
            ("5m", timedelta(minutes=30), 5),
            ("15m", timedelta(hours=2), 5),
            ("1h", timedelta(hours=10), 5),
            ("1d", timedelta(days=10), 5),
        ]
        
        for timeframe, time_range, expected_count in test_cases:
            end = datetime.utcnow()
            start = end - time_range
            
            bars = adapter.get_market_bars(
                instrument="AAPL",
                timeframe=timeframe,
                start=start,
                end=end,
                limit=expected_count,
            )
            
            assert len(bars) == expected_count, f"Expected {expected_count} bars for {timeframe}, got {len(bars)}"
            assert all(bar.timeframe == timeframe for bar in bars)


class TestMarketDataAPIEndpoints:
    """Test market data API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from apps.assistant_api.main import app
        return TestClient(app)
    
    def test_get_market_snapshot_success(self, client):
        """Test getting market snapshot."""
        response = client.get("/api/v1/market/snapshot?instrument=AAPL")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["instrument"] == "AAPL"
        assert "bid" in data
        assert "ask" in data
        assert "last" in data
        assert "mid" in data
        assert "volume" in data
    
    def test_get_market_snapshot_missing_instrument(self, client):
        """Test snapshot with missing instrument."""
        response = client.get("/api/v1/market/snapshot")
        
        assert response.status_code == 422  # Validation error
    
    def test_get_market_snapshot_with_fields(self, client):
        """Test snapshot with specific fields."""
        response = client.get("/api/v1/market/snapshot?instrument=AAPL&fields=bid,ask,last")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["instrument"] == "AAPL"
        assert "bid" in data
        assert "ask" in data
    
    def test_get_market_bars_success(self, client):
        """Test getting market bars."""
        response = client.get("/api/v1/market/bars?instrument=AAPL&timeframe=1h&limit=10")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["instrument"] == "AAPL"
        assert data["timeframe"] == "1h"
        assert data["bar_count"] > 0
        assert len(data["bars"]) > 0
        
        # Check bar structure
        bar = data["bars"][0]
        assert "timestamp" in bar
        assert "open" in bar
        assert "high" in bar
        assert "low" in bar
        assert "close" in bar
        assert "volume" in bar
    
    def test_get_market_bars_missing_instrument(self, client):
        """Test bars with missing instrument."""
        response = client.get("/api/v1/market/bars?timeframe=1h")
        
        assert response.status_code == 422  # Validation error
    
    def test_get_market_bars_missing_timeframe(self, client):
        """Test bars with missing timeframe."""
        response = client.get("/api/v1/market/bars?instrument=AAPL")
        
        assert response.status_code == 422  # Validation error
    
    def test_get_market_bars_invalid_limit(self, client):
        """Test bars with invalid limit."""
        response = client.get("/api/v1/market/bars?instrument=AAPL&timeframe=1h&limit=10000")
        
        assert response.status_code == 400  # Bad request
    
    def test_get_market_bars_with_date_range(self, client):
        """Test bars with date range."""
        end = datetime.utcnow()
        start = end - timedelta(hours=5)
        
        response = client.get(
            f"/api/v1/market/bars?instrument=SPY&timeframe=1h"
            f"&start={start.isoformat()}&end={end.isoformat()}"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["bar_count"] > 0
    
    def test_get_market_bars_rth_only(self, client):
        """Test bars with regular trading hours only."""
        response = client.get(
            "/api/v1/market/bars?instrument=AAPL&timeframe=1h&rth_only=true"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["bar_count"] > 0
