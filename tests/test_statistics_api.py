"""
API tests for statistics endpoints.
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

import packages.statistics
from packages.statistics import RejectionReason
from apps.assistant_api.main import app


@pytest.fixture(autouse=True)
def reset_stats():
    """Reset statistics singleton before each test."""
    packages.statistics._stats_collector = None
    yield
    packages.statistics._stats_collector = None


class TestStatisticsAPI:
    """Tests for statistics API endpoints."""
    
    def test_get_statistics_summary_empty(self):
        """Test statistics summary with no data."""
        client = TestClient(app)
        response = client.get("/api/v1/statistics/summary")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_orders"] == 0
        assert data["success_rate"] == 0.0
        assert data["reject_rate"] == 0.0
        assert data["avg_latency_seconds"] is None
        assert data["rejection_breakdown"] == {}
        assert data["total_reconciliations"] == 0
    
    def test_get_statistics_summary_with_orders(self):
        """Test statistics summary with order data."""
        client = TestClient(app)
        
        # Add some orders via stats collector
        from packages.statistics import get_stats_collector
        collector = get_stats_collector()
        
        # 2 successful orders
        for i in range(2):
            oid = f"ord_success_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid, simulated_price=100.0)
            collector.record_order_risk_evaluated(oid, approved=True)
            collector.record_order_approval_requested(oid)
            collector.record_order_approval_decided(oid, approved=True)
            collector.record_order_submitted(oid, f"MOCK{i}")
            
            # Add timestamps for latency
            now = datetime.utcnow()
            collector.orders[oid].submitted_at = now
            filled_at = now + timedelta(seconds=1.0)
            collector.record_order_filled(oid, fill_price=101.0, filled_at=filled_at)
        
        # 1 rejected order
        oid = "ord_reject"
        collector.record_order_proposed(oid, "TSLA", "BUY", 100.0)
        collector.record_order_simulated(oid)
        collector.record_order_risk_evaluated(
            oid,
            approved=False,
            rejection_reason=RejectionReason.RISK_NOTIONAL,
        )
        
        # Get summary
        response = client.get("/api/v1/statistics/summary")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_orders"] == 3
        assert data["successful_orders"] == 2
        assert data["rejected_orders"] == 1
        assert data["success_rate"] == pytest.approx(0.66, abs=0.01)
        assert data["reject_rate"] == pytest.approx(0.33, abs=0.01)
        assert data["avg_latency_seconds"] == pytest.approx(1.0, abs=0.1)
        assert data["rejection_breakdown"]["risk_notional"] == 1
    
    def test_get_pre_live_checklist_not_ready(self):
        """Test pre-live checklist when system is not ready."""
        client = TestClient(app)
        
        # Add insufficient data (only 10 orders, need 200)
        from packages.statistics import get_stats_collector
        collector = get_stats_collector()
        
        for i in range(10):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid)
        
        response = client.get("/api/v1/statistics/pre-live-checklist")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["ready_for_live"] is False
        assert data["orders_simulated_ok"] is False
        assert data["orders_simulated_count"] == 10
        assert len(data["blocking_issues"]) > 0
        assert any("simulated orders" in issue.lower() for issue in data["blocking_issues"])
    
    def test_get_pre_live_checklist_ready(self):
        """Test pre-live checklist when system is ready."""
        client = TestClient(app)
        
        from packages.statistics import get_stats_collector, ReconciliationStats
        collector = get_stats_collector()
        
        # Add 200 simulated orders
        for i in range(200):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid, simulated_price=100.0)
            
            # Submit first 50
            if i < 50:
                collector.record_order_risk_evaluated(oid, approved=True)
                collector.record_order_approval_requested(oid)
                collector.record_order_approval_decided(oid, approved=True)
                collector.record_order_submitted(oid, f"MOCK{i}")
                collector.record_order_filled(oid, fill_price=101.0)
        
        # Add 30 days of perfect reconciliation
        for i in range(30):
            recon = ReconciliationStats(
                timestamp=datetime.utcnow() - timedelta(days=29-i),
                is_reconciled=True,
                discrepancy_count=0,
                has_critical_discrepancies=False,
                duration_ms=100.0,
            )
            collector.reconciliations.append(recon)
        
        response = client.get("/api/v1/statistics/pre-live-checklist")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["ready_for_live"] is True
        assert data["orders_simulated_ok"] is True
        assert data["orders_submitted_ok"] is True
        assert data["unintended_orders_ok"] is True
        assert data["reject_rate_ok"] is True
        assert data["reconciliation_ok"] is True
        assert data["checks_passed"] == data["checks_total"]
        assert len(data["blocking_issues"]) == 0
    
    def test_get_pre_live_checklist_high_reject_rate(self):
        """Test pre-live checklist with high reject rate."""
        client = TestClient(app)
        
        from packages.statistics import get_stats_collector, ReconciliationStats
        collector = get_stats_collector()
        
        # Add 200 simulated, 50 submitted
        for i in range(200):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid)
            
            if i < 50:
                collector.record_order_risk_evaluated(oid, approved=True)
                collector.record_order_approval_requested(oid)
                collector.record_order_approval_decided(oid, approved=True)
                collector.record_order_submitted(oid, f"MOCK{i}")
        
        # Add 60 rejections (24% reject rate, over 20% threshold)
        for i in range(60):
            oid = f"ord_reject_{i}"
            collector.record_order_proposed(oid, "TSLA", "BUY", 100.0)
            collector.record_order_simulated(oid)
            collector.record_order_risk_evaluated(
                oid,
                approved=False,
                rejection_reason=RejectionReason.RISK_NOTIONAL,
            )
        
        # Add 30 days of perfect reconciliation
        for i in range(30):
            recon = ReconciliationStats(
                timestamp=datetime.utcnow() - timedelta(days=29-i),
                is_reconciled=True,
                discrepancy_count=0,
                has_critical_discrepancies=False,
                duration_ms=100.0,
            )
            collector.reconciliations.append(recon)
        
        response = client.get("/api/v1/statistics/pre-live-checklist")
        
        assert response.status_code == 200
        data = response.json()
        
        # Not blocking but warning
        assert data["ready_for_live"] is True  # No blocking issues
        assert data["orders_simulated_ok"] is True
        assert data["orders_submitted_ok"] is True
        assert data["reconciliation_ok"] is True
        assert data["reject_rate_ok"] is False  # Warning: >20%
        assert data["reject_rate"] == pytest.approx(0.23, abs=0.02)
        assert len(data["warnings"]) > 0
        assert any("reject rate" in w.lower() for w in data["warnings"])
