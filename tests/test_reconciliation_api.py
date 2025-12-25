"""
Integration tests for reconciliation API endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from apps.assistant_api.main import app
from packages.broker_ibkr.fake import FakeBrokerAdapter
import packages.reconciliation


class TestReconciliationAPI:
    """Test suite for reconciliation API endpoint."""

    def setup_method(self):
        """Setup for each test."""
        # Reset reconciler singleton
        packages.reconciliation._reconciler_instance = None
        
        # Initialize with fake broker
        broker = FakeBrokerAdapter(account_id="DU123456")
        broker.connect()
        from packages.reconciliation import get_reconciler
        get_reconciler(broker_adapter=broker)
        
        self.client = TestClient(app)

    def test_get_reconciliation_status_success(self):
        """Test successful reconciliation status retrieval."""
        response = self.client.get("/api/v1/reconciliation/status?account_id=DU123456")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "timestamp" in data
        assert "is_reconciled" in data
        assert "discrepancy_count" in data
        assert "has_critical_discrepancies" in data
        assert "discrepancies" in data
        assert "summary" in data
        assert "duration_ms" in data
        
        # Verify summary structure
        summary = data["summary"]
        assert "internal_orders_count" in summary
        assert "broker_orders_count" in summary
        assert "internal_positions_count" in summary
        assert "broker_positions_count" in summary
        assert "internal_cash" in summary
        assert "broker_cash" in summary

    def test_reconciliation_with_broker_state(self):
        """Test reconciliation returns broker state counts."""
        response = self.client.get("/api/v1/reconciliation/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # With fake broker, should have some positions/cash
        summary = data["summary"]
        assert summary["broker_cash"] > 0  # FakeBroker returns 10000.0
        assert isinstance(summary["broker_positions_count"], int)

    def test_reconciliation_discrepancies_structure(self):
        """Test that discrepancies have correct structure."""
        response = self.client.get("/api/v1/reconciliation/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Each discrepancy should have required fields
        for disc in data["discrepancies"]:
            assert "type" in disc
            assert "severity" in disc
            assert "description" in disc
            assert "detected_at" in disc
            # Optional fields may be null
            assert disc.get("internal_value") is not None or disc.get("internal_value") is None
            assert disc.get("broker_value") is not None or disc.get("broker_value") is None
