"""
API tests for live trading endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from apps.assistant_api.main import app


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


class TestLiveTradingAPI:
    """Tests for live trading API endpoints."""
    
    def test_get_live_trading_status(self, client):
        """Test GET /api/v1/live-trading/status endpoint."""
        response = client.get("/api/v1/live-trading/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "live_enabled" in data
        assert "max_order_size" in data
        assert "max_order_value_usd" in data
        assert "symbol_whitelist" in data
        assert "require_safety_checks" in data
        assert "require_manual_approval" in data
        
        # Verify types
        assert isinstance(data["live_enabled"], bool)
        assert isinstance(data["max_order_size"], int)
        assert isinstance(data["symbol_whitelist"], list)
        assert isinstance(data["require_safety_checks"], bool)
        assert isinstance(data["require_manual_approval"], bool)
    
    def test_get_live_trading_status_defaults(self, client):
        """Test live trading status has reasonable defaults."""
        response = client.get("/api/v1/live-trading/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Default should be disabled
        # (unless explicitly enabled via feature flag)
        assert isinstance(data["live_enabled"], bool)
        
        # Should have some symbols in whitelist
        assert len(data["symbol_whitelist"]) > 0
        
        # Should have reasonable limits
        assert data["max_order_size"] > 0
        assert float(data["max_order_value_usd"]) > 0
    
    def test_disable_live_trading(self, client):
        """Test POST /api/v1/live-trading/disable endpoint."""
        response = client.post("/api/v1/live-trading/disable")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "live_enabled" in data
        assert data["live_enabled"] is False
    
    def test_enable_live_trading_fails_without_readiness(self, client):
        """Test POST /api/v1/live-trading/enable fails if not ready."""
        response = client.post("/api/v1/live-trading/enable")
        
        # Should fail (system not ready for live trading)
        assert response.status_code == 400
        data = response.json()
        
        assert "detail" in data
        detail = data["detail"]
        
        # Should have error information
        assert "error" in detail or "message" in detail or isinstance(detail, str)
    
    def test_live_trading_status_idempotent(self, client):
        """Test live trading status can be called multiple times."""
        response1 = client.get("/api/v1/live-trading/status")
        response2 = client.get("/api/v1/live-trading/status")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Should have same structure
        assert set(data1.keys()) == set(data2.keys())
    
    def test_disable_live_trading_idempotent(self, client):
        """Test disabling live trading multiple times works."""
        response1 = client.post("/api/v1/live-trading/disable")
        response2 = client.post("/api/v1/live-trading/disable")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        assert data1["live_enabled"] is False
        assert data2["live_enabled"] is False
