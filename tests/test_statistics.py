"""
Tests for paper trading statistics collection and pre-live validation.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from packages.statistics import (
    OrderStatus,
    RejectionReason,
    OrderStats,
    ReconciliationStats,
    PreLiveStatus,
    StatisticsCollector,
    get_stats_collector,
)


@pytest.fixture
def temp_storage():
    """Temporary storage file for persistence tests."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def collector():
    """Fresh statistics collector for each test."""
    # Reset singleton
    import packages.statistics
    packages.statistics._stats_collector = None
    return StatisticsCollector()


class TestOrderStats:
    """Tests for OrderStats dataclass and derived metrics."""
    
    def test_order_stats_creation(self):
        """Test basic OrderStats creation."""
        stats = OrderStats(
            order_id="ord_123",
            proposal_id="prop_456",
            symbol="AAPL",
            side="BUY",
            quantity=10.0,
        )
        
        assert stats.order_id == "ord_123"
        assert stats.proposal_id == "prop_456"
        assert stats.symbol == "AAPL"
        assert stats.side == "BUY"
        assert stats.quantity == 10.0
        assert stats.status == OrderStatus.PROPOSED
    
    def test_latency_calculation(self):
        """Test latency calculation from timestamps."""
        stats = OrderStats(order_id="ord_1", symbol="AAPL")
        
        # No latency without timestamps
        assert stats.latency_seconds is None
        
        # Set timestamps
        now = datetime.utcnow()
        stats.submitted_at = now
        stats.filled_at = now + timedelta(seconds=2.5)
        
        assert stats.latency_seconds == pytest.approx(2.5, abs=0.1)
    
    def test_simulator_accuracy(self):
        """Test simulator accuracy calculation."""
        stats = OrderStats(order_id="ord_1", symbol="AAPL")
        
        # No accuracy without prices
        assert stats.simulator_accuracy is None
        
        # Perfect prediction
        stats.simulated_price = 100.0
        stats.fill_price = 100.0
        assert stats.simulator_accuracy == 1.0
        
        # 5% error
        stats.simulated_price = 100.0
        stats.fill_price = 105.0
        assert stats.simulator_accuracy == pytest.approx(0.95, abs=0.01)
        
        # 10% error
        stats.simulated_price = 100.0
        stats.fill_price = 110.0
        assert stats.simulator_accuracy == pytest.approx(0.90, abs=0.01)
    
    def test_is_successful(self):
        """Test successful order detection."""
        stats = OrderStats(order_id="ord_1", symbol="AAPL")
        
        assert not stats.is_successful
        
        stats.status = OrderStatus.FILLED
        assert stats.is_successful
        
        stats.status = OrderStatus.REJECTED
        assert not stats.is_successful
    
    def test_is_rejected(self):
        """Test rejected order detection."""
        stats = OrderStats(order_id="ord_1", symbol="AAPL")
        
        assert not stats.is_rejected
        
        stats.status = OrderStatus.RISK_REJECTED
        assert stats.is_rejected
        
        stats.status = OrderStatus.APPROVAL_DENIED
        assert stats.is_rejected
        
        stats.status = OrderStatus.REJECTED
        assert stats.is_rejected
        
        stats.status = OrderStatus.FILLED
        assert not stats.is_rejected
    
    def test_to_dict_serialization(self):
        """Test OrderStats serialization."""
        now = datetime.utcnow()
        stats = OrderStats(
            order_id="ord_1",
            symbol="AAPL",
            side="BUY",
            quantity=10.0,
            proposed_at=now,
            status=OrderStatus.FILLED,
        )
        
        data = stats.to_dict()
        
        assert data["order_id"] == "ord_1"
        assert data["symbol"] == "AAPL"
        assert data["status"] == "FILLED"
        assert "proposed_at" in data
        assert data["is_successful"] is True
        assert data["is_rejected"] is False


class TestStatisticsCollector:
    """Tests for StatisticsCollector class."""
    
    def test_record_order_lifecycle(self, collector):
        """Test complete order lifecycle recording."""
        order_id = "ord_123"
        
        # Propose
        collector.record_order_proposed(order_id, "AAPL", "BUY", 10.0, "prop_456")
        assert order_id in collector.orders
        assert collector.orders[order_id].status == OrderStatus.PROPOSED
        assert collector.orders[order_id].symbol == "AAPL"
        
        # Simulate
        collector.record_order_simulated(order_id, simulated_price=100.0)
        assert collector.orders[order_id].status == OrderStatus.SIMULATED
        assert collector.orders[order_id].simulated_price == 100.0
        
        # Risk approve
        collector.record_order_risk_evaluated(order_id, approved=True)
        assert collector.orders[order_id].status == OrderStatus.RISK_APPROVED
        
        # Approval request
        collector.record_order_approval_requested(order_id)
        assert collector.orders[order_id].status == OrderStatus.APPROVAL_REQUESTED
        
        # Approval granted
        collector.record_order_approval_decided(order_id, approved=True)
        assert collector.orders[order_id].status == OrderStatus.APPROVAL_GRANTED
        
        # Submit
        collector.record_order_submitted(order_id, "MOCK123")
        assert collector.orders[order_id].status == OrderStatus.SUBMITTED
        assert collector.orders[order_id].broker_order_id == "MOCK123"
        
        # Fill (with explicit timestamp)
        now = datetime.utcnow()
        collector.orders[order_id].submitted_at = now
        filled_at = now + timedelta(seconds=2.0)
        collector.record_order_filled(order_id, fill_price=101.0, filled_at=filled_at)
        assert collector.orders[order_id].status == OrderStatus.FILLED
        assert collector.orders[order_id].fill_price == 101.0
        assert collector.orders[order_id].is_successful
        assert collector.orders[order_id].latency_seconds == pytest.approx(2.0, abs=0.1)
    
    def test_record_risk_rejection(self, collector):
        """Test risk rejection recording."""
        order_id = "ord_reject"
        
        collector.record_order_proposed(order_id, "TSLA", "BUY", 100.0)
        collector.record_order_simulated(order_id)
        collector.record_order_risk_evaluated(
            order_id,
            approved=False,
            rejection_reason=RejectionReason.RISK_NOTIONAL,
            rejection_details="Exceeds $10,000 limit",
        )
        
        assert collector.orders[order_id].status == OrderStatus.RISK_REJECTED
        assert collector.orders[order_id].rejection_reason == RejectionReason.RISK_NOTIONAL
        assert collector.orders[order_id].rejection_details == "Exceeds $10,000 limit"
        assert collector.orders[order_id].is_rejected
    
    def test_record_human_denial(self, collector):
        """Test human denial recording."""
        order_id = "ord_denied"
        
        collector.record_order_proposed(order_id, "NVDA", "SELL", 5.0)
        collector.record_order_simulated(order_id)
        collector.record_order_risk_evaluated(order_id, approved=True)
        collector.record_order_approval_requested(order_id)
        collector.record_order_approval_decided(
            order_id,
            approved=False,
            reason="Market conditions changed",
        )
        
        assert collector.orders[order_id].status == OrderStatus.APPROVAL_DENIED
        assert collector.orders[order_id].rejection_reason == RejectionReason.HUMAN_DENIED
        assert collector.orders[order_id].rejection_details == "Market conditions changed"
        assert collector.orders[order_id].is_rejected
    
    def test_record_broker_rejection(self, collector):
        """Test broker rejection recording."""
        order_id = "ord_broker_reject"
        
        collector.record_order_proposed(order_id, "AAPL", "BUY", 10.0)
        collector.record_order_simulated(order_id)
        collector.record_order_risk_evaluated(order_id, approved=True)
        collector.record_order_approval_requested(order_id)
        collector.record_order_approval_decided(order_id, approved=True)
        collector.record_order_submitted(order_id, "MOCK123")
        collector.record_order_rejected(order_id, "Insufficient margin")
        
        assert collector.orders[order_id].status == OrderStatus.REJECTED
        assert collector.orders[order_id].rejection_reason == RejectionReason.BROKER_REJECTED
        assert collector.orders[order_id].rejection_details == "Insufficient margin"
        assert collector.orders[order_id].is_rejected
    
    def test_record_reconciliation(self, collector):
        """Test reconciliation event recording."""
        collector.record_reconciliation(
            is_reconciled=True,
            discrepancy_count=0,
            has_critical_discrepancies=False,
            duration_ms=123.45,
        )
        
        assert len(collector.reconciliations) == 1
        assert collector.reconciliations[0].is_reconciled is True
        assert collector.reconciliations[0].discrepancy_count == 0
        assert collector.reconciliations[0].duration_ms == 123.45
    
    def test_get_summary_empty(self, collector):
        """Test summary with no data."""
        summary = collector.get_summary()
        
        assert summary["total_orders"] == 0
        assert summary["success_rate"] == 0.0
        assert summary["reject_rate"] == 0.0
        assert summary["avg_latency_seconds"] is None
        assert summary["rejection_breakdown"] == {}
    
    def test_get_summary_with_orders(self, collector):
        """Test summary calculation with orders."""
        # 3 successful orders
        for i in range(3):
            oid = f"ord_success_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid, simulated_price=100.0)
            collector.record_order_risk_evaluated(oid, approved=True)
            collector.record_order_approval_requested(oid)
            collector.record_order_approval_decided(oid, approved=True)
            collector.record_order_submitted(oid, f"MOCK{i}")
            
            # Add latency
            now = datetime.utcnow()
            collector.orders[oid].submitted_at = now
            filled_at = now + timedelta(seconds=2.0)
            
            collector.record_order_filled(oid, fill_price=101.0, filled_at=filled_at)
        
        # 1 risk rejected order
        oid = "ord_risk_reject"
        collector.record_order_proposed(oid, "TSLA", "BUY", 100.0)
        collector.record_order_simulated(oid)
        collector.record_order_risk_evaluated(
            oid,
            approved=False,
            rejection_reason=RejectionReason.RISK_NOTIONAL,
        )
        
        # 1 human denied order
        oid = "ord_human_deny"
        collector.record_order_proposed(oid, "NVDA", "SELL", 5.0)
        collector.record_order_simulated(oid)
        collector.record_order_risk_evaluated(oid, approved=True)
        collector.record_order_approval_requested(oid)
        collector.record_order_approval_decided(oid, approved=False)
        
        summary = collector.get_summary()
        
        assert summary["total_orders"] == 5
        assert summary["successful_orders"] == 3
        assert summary["rejected_orders"] == 2
        assert summary["success_rate"] == pytest.approx(0.6, abs=0.01)  # 3/5
        assert summary["reject_rate"] == pytest.approx(0.4, abs=0.01)  # 2/5
        assert summary["avg_latency_seconds"] == pytest.approx(2.0, abs=0.1)
        assert summary["rejection_breakdown"]["risk_notional"] == 1
        assert summary["rejection_breakdown"]["human_denied"] == 1
    
    def test_get_summary_simulator_accuracy(self, collector):
        """Test simulator accuracy in summary."""
        # Order with perfect prediction
        oid1 = "ord_perfect"
        collector.record_order_proposed(oid1, "AAPL", "BUY", 10.0)
        collector.record_order_simulated(oid1, simulated_price=100.0)
        collector.record_order_risk_evaluated(oid1, approved=True)
        collector.record_order_approval_requested(oid1)
        collector.record_order_approval_decided(oid1, approved=True)
        collector.record_order_submitted(oid1, "MOCK1")
        collector.record_order_filled(oid1, fill_price=100.0)
        
        # Order with 5% error
        oid2 = "ord_error"
        collector.record_order_proposed(oid2, "GOOGL", "BUY", 5.0)
        collector.record_order_simulated(oid2, simulated_price=100.0)
        collector.record_order_risk_evaluated(oid2, approved=True)
        collector.record_order_approval_requested(oid2)
        collector.record_order_approval_decided(oid2, approved=True)
        collector.record_order_submitted(oid2, "MOCK2")
        collector.record_order_filled(oid2, fill_price=105.0)
        
        summary = collector.get_summary()
        
        # Verify reconciliation keys present
        assert "total_reconciliations" in summary
        assert "successful_reconciliations" in summary
        assert "reconciliation_success_rate" in summary
        
        # Average accuracy: (1.0 + 0.95) / 2 = 0.975
        assert summary["avg_simulator_accuracy"] == pytest.approx(0.975, abs=0.01)
    
    def test_get_summary_reconciliation(self, collector):
        """Test reconciliation statistics in summary."""
        # 3 successful reconciliations
        for _ in range(3):
            collector.record_reconciliation(
                is_reconciled=True,
                discrepancy_count=0,
                has_critical_discrepancies=False,
                duration_ms=100.0,
            )
        
        # 1 failed reconciliation
        collector.record_reconciliation(
            is_reconciled=False,
            discrepancy_count=2,
            has_critical_discrepancies=False,
            duration_ms=150.0,
        )
        
        summary = collector.get_summary()
        
        assert summary["total_reconciliations"] == 4
        assert summary["successful_reconciliations"] == 3
        assert summary["reconciliation_success_rate"] == pytest.approx(0.75, abs=0.01)


class TestPreLiveValidation:
    """Tests for pre-live checklist validation."""
    
    def test_pre_live_status_insufficient_orders(self, collector):
        """Test pre-live validation with insufficient orders."""
        # Add only 50 simulated orders (need 200)
        for i in range(50):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid)
        
        status = collector.get_pre_live_status()
        
        assert not status.ready_for_live
        assert not status.orders_simulated_ok
        assert status.orders_simulated_count == 50
        assert "Insufficient simulated orders" in status.blocking_issues[0]
    
    def test_pre_live_status_insufficient_submissions(self, collector):
        """Test pre-live validation with insufficient submissions."""
        # Add 200 simulated orders
        for i in range(200):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid)
        
        # Submit only 30 (need 50)
        for i in range(30):
            oid = f"ord_{i}"
            collector.record_order_risk_evaluated(oid, approved=True)
            collector.record_order_approval_requested(oid)
            collector.record_order_approval_decided(oid, approved=True)
            collector.record_order_submitted(oid, f"MOCK{i}")
        
        status = collector.get_pre_live_status()
        
        assert not status.ready_for_live
        assert status.orders_simulated_ok  # 200+ OK
        assert not status.orders_submitted_ok
        assert status.orders_submitted_count == 30
        assert "Insufficient submitted orders" in status.blocking_issues[0]
    
    def test_pre_live_status_high_reject_rate(self, collector):
        """Test pre-live validation with high reject rate."""
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
        
        # Reject 60 orders (24% reject rate, over 20% threshold)
        for i in range(60):
            oid = f"ord_reject_{i}"
            collector.record_order_proposed(oid, "TSLA", "BUY", 100.0)
            collector.record_order_simulated(oid)
            collector.record_order_risk_evaluated(
                oid,
                approved=False,
                rejection_reason=RejectionReason.RISK_NOTIONAL,
            )
        
        status = collector.get_pre_live_status()
        
        # Not blocking, but warning
        assert status.orders_simulated_ok
        assert status.orders_submitted_ok
        assert not status.reject_rate_ok  # 24% > 20%
        assert status.reject_rate == pytest.approx(0.23, abs=0.02)  # 60/260
        assert any("Reject rate too high" in w for w in status.warnings)
        # With 50 rejections, we're at exactly 20%, so it passes
    
    def test_pre_live_status_insufficient_reconciliation_history(self, collector):
        """Test pre-live validation with insufficient reconciliation history."""
        # Meet all order requirements
        for i in range(200):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid)
            if i < 50:
                collector.record_order_risk_evaluated(oid, approved=True)
                collector.record_order_approval_requested(oid)
                collector.record_order_approval_decided(oid, approved=True)
                collector.record_order_submitted(oid, f"MOCK{i}")
        
        # Add only 10 days of reconciliation (need 30)
        for i in range(10):
            collector.record_reconciliation(
                is_reconciled=True,
                discrepancy_count=0,
                has_critical_discrepancies=False,
                duration_ms=100.0,
            )
        
        status = collector.get_pre_live_status()
        
        assert not status.ready_for_live
        assert not status.reconciliation_ok
        assert status.reconciliation_days < 30
        assert any("reconciliation history" in issue.lower() for issue in status.blocking_issues)
    
    def test_pre_live_status_all_checks_pass(self, collector):
        """Test pre-live validation with all checks passing."""
        # Add 200 simulated, 50 submitted, all successful
        for i in range(200):
            oid = f"ord_{i}"
            collector.record_order_proposed(oid, "AAPL", "BUY", 10.0)
            collector.record_order_simulated(oid, simulated_price=100.0)
            
            if i < 50:
                collector.record_order_risk_evaluated(oid, approved=True)
                collector.record_order_approval_requested(oid)
                collector.record_order_approval_decided(oid, approved=True)
                collector.record_order_submitted(oid, f"MOCK{i}")
                collector.record_order_filled(oid, fill_price=101.0)
        
        # Add 30 days of perfect reconciliation
        # Backdate to cover 30-day period
        for i in range(30):
            recon = ReconciliationStats(
                timestamp=datetime.utcnow() - timedelta(days=29-i),
                is_reconciled=True,
                discrepancy_count=0,
                has_critical_discrepancies=False,
                duration_ms=100.0,
            )
            collector.reconciliations.append(recon)
        
        status = collector.get_pre_live_status()
        
        assert status.ready_for_live
        assert status.orders_simulated_ok
        assert status.orders_submitted_ok
        assert status.unintended_orders_ok
        assert status.reject_rate_ok
        assert status.reconciliation_ok
        assert status.checks_passed == status.checks_total
        assert len(status.blocking_issues) == 0


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_stats_collector_singleton(self):
        """Test singleton returns same instance."""
        import packages.statistics
        packages.statistics._stats_collector = None
        
        collector1 = get_stats_collector()
        collector2 = get_stats_collector()
        
        assert collector1 is collector2
    
    def test_get_stats_collector_with_storage(self, temp_storage):
        """Test singleton with storage path."""
        import packages.statistics
        packages.statistics._stats_collector = None
        
        collector = get_stats_collector(storage_path=temp_storage)
        
        # Record order
        collector.record_order_proposed("ord_1", "AAPL", "BUY", 10.0)
        
        # Verify file created
        assert temp_storage.exists()
        
        # Load in new instance
        packages.statistics._stats_collector = None
        collector2 = get_stats_collector(storage_path=temp_storage)
        
        # Verify data loaded
        assert "ord_1" in collector2.orders


class TestPersistence:
    """Tests for statistics persistence."""
    
    def test_save_and_load(self, temp_storage):
        """Test save/load cycle."""
        collector = StatisticsCollector(storage_path=temp_storage)
        
        # Add data
        collector.record_order_proposed("ord_1", "AAPL", "BUY", 10.0)
        collector.record_order_simulated("ord_1", simulated_price=100.0)
        collector.record_reconciliation(
            is_reconciled=True,
            discrepancy_count=0,
            has_critical_discrepancies=False,
            duration_ms=123.45,
        )
        
        # Verify saved
        assert temp_storage.exists()
        
        # Load in new collector
        collector2 = StatisticsCollector(storage_path=temp_storage)
        
        assert "ord_1" in collector2.orders
        assert collector2.orders["ord_1"].symbol == "AAPL"
        assert len(collector2.reconciliations) == 1
        assert collector2.reconciliations[0].duration_ms == 123.45
