"""Tests for metrics collector."""

from decimal import Decimal

import pytest

from packages.metrics_collector import MetricsCollector, get_metrics_collector, set_metrics_collector


class TestMetricsCollector:
    """Test metrics collector functionality."""
    
    def test_increment_proposal_count(self):
        """Test incrementing proposal count."""
        collector = MetricsCollector()
        
        collector.increment_proposal_count("AAPL", "RISK_APPROVED")
        collector.increment_proposal_count("AAPL", "RISK_APPROVED")
        collector.increment_proposal_count("TSLA", "APPROVAL_GRANTED")
        
        assert collector.proposal_count[("AAPL", "RISK_APPROVED")] == 2
        assert collector.proposal_count[("TSLA", "APPROVAL_GRANTED")] == 1
    
    def test_record_risk_rejection(self):
        """Test recording risk rejections."""
        collector = MetricsCollector()
        
        collector.record_risk_rejection("R1")
        collector.record_risk_rejection("R1")
        collector.record_risk_rejection("R2")
        
        assert collector.risk_rejection_count["R1"] == 2
        assert collector.risk_rejection_count["R2"] == 1
    
    def test_increment_broker_errors(self):
        """Test incrementing broker errors."""
        collector = MetricsCollector()
        
        collector.increment_broker_errors()
        collector.increment_broker_errors()
        
        assert collector.broker_error_count == 2
    
    def test_set_daily_pnl(self):
        """Test setting daily P&L."""
        collector = MetricsCollector()
        
        collector.set_daily_pnl(Decimal("1250.50"))
        
        assert collector.daily_pnl == Decimal("1250.50")
    
    def test_record_order_latency(self):
        """Test recording order latencies."""
        collector = MetricsCollector()
        
        collector.record_order_latency("submission", 0.250)
        collector.record_order_latency("submission", 0.150)
        collector.record_order_latency("fill", 1.500)
        
        assert len(collector.submission_latencies) == 2
        assert len(collector.fill_latencies) == 1
        assert collector.submission_latencies[0] == 0.250
        assert collector.fill_latencies[0] == 1.500
    
    def test_reset_daily_metrics(self):
        """Test resetting daily metrics."""
        collector = MetricsCollector()
        
        collector.set_daily_pnl(Decimal("500.00"))
        collector.reset_daily_metrics()
        
        assert collector.daily_pnl == Decimal("0")
    
    def test_get_uptime_seconds(self):
        """Test getting uptime."""
        import time
        
        collector = MetricsCollector()
        time.sleep(0.01)  # Sleep 10ms
        
        uptime = collector.get_uptime_seconds()
        assert uptime > 0.01
        assert uptime < 1.0
    
    def test_export_prometheus_empty(self):
        """Test exporting empty metrics."""
        collector = MetricsCollector()
        
        output = collector.export_prometheus()
        
        # Should have metadata and uptime
        assert "ibkr_broker_info" in output
        assert "ibkr_uptime_seconds" in output
        assert "ibkr_daily_pnl_usd" in output
        assert "# HELP" in output
        assert "# TYPE" in output
    
    def test_export_prometheus_with_data(self):
        """Test exporting metrics with data."""
        collector = MetricsCollector()
        
        # Add data
        collector.increment_proposal_count("AAPL", "RISK_APPROVED")
        collector.increment_proposal_count("AAPL", "APPROVAL_GRANTED")
        collector.record_risk_rejection("R1")
        collector.record_risk_rejection("R2")
        collector.increment_broker_errors()
        collector.set_daily_pnl(Decimal("1250.50"))
        collector.record_order_latency("submission", 0.250)
        collector.record_order_latency("submission", 0.150)
        collector.record_order_latency("fill", 1.500)
        
        output = collector.export_prometheus()
        
        # Verify proposal counts
        assert 'ibkr_proposal_total{symbol="AAPL",state="RISK_APPROVED"} 1' in output
        assert 'ibkr_proposal_total{symbol="AAPL",state="APPROVAL_GRANTED"} 1' in output
        
        # Verify risk rejections
        assert 'ibkr_risk_rejection_total{rule="R1"} 1' in output
        assert 'ibkr_risk_rejection_total{rule="R2"} 1' in output
        
        # Verify broker errors
        assert "ibkr_broker_error_total 1" in output
        
        # Verify P&L
        assert "ibkr_daily_pnl_usd 1250.50" in output
        
        # Verify latency metrics
        assert "ibkr_submission_latency_seconds_count 2" in output
        assert "ibkr_fill_latency_seconds_count 1" in output
        assert "quantile" in output
    
    def test_thread_safety(self):
        """Test thread safety of metrics collection."""
        import threading
        
        collector = MetricsCollector()
        
        def increment_proposals():
            for _ in range(100):
                collector.increment_proposal_count("AAPL", "RISK_APPROVED")
        
        # Run 10 threads concurrently
        threads = [threading.Thread(target=increment_proposals) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have 1000 total increments (10 threads * 100 each)
        assert collector.proposal_count[("AAPL", "RISK_APPROVED")] == 1000
    
    def test_prometheus_quantiles(self):
        """Test Prometheus quantile calculation."""
        collector = MetricsCollector()
        
        # Add latencies: 0.1, 0.2, 0.3, ..., 1.0
        for i in range(1, 11):
            collector.record_order_latency("submission", i * 0.1)
        
        output = collector.export_prometheus()
        
        # Verify quantiles exist
        assert 'quantile="0.5"' in output  # Median
        assert 'quantile="0.95"' in output  # P95
        assert 'quantile="0.99"' in output  # P99
        
        # Verify count and sum
        assert "ibkr_submission_latency_seconds_count 10" in output
        assert "ibkr_submission_latency_seconds_sum" in output


class TestGlobalMetricsCollector:
    """Test global metrics collector singleton."""
    
    def test_get_metrics_collector_singleton(self):
        """Test that get_metrics_collector returns same instance."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()
        
        assert collector1 is collector2
    
    def test_set_metrics_collector(self):
        """Test setting custom metrics collector."""
        custom_collector = MetricsCollector()
        custom_collector.increment_proposal_count("TEST", "TEST_STATE")
        
        set_metrics_collector(custom_collector)
        
        retrieved = get_metrics_collector()
        assert retrieved is custom_collector
        assert retrieved.proposal_count[("TEST", "TEST_STATE")] == 1
    
    def test_metrics_persist_across_calls(self):
        """Test that metrics persist across multiple calls."""
        collector = get_metrics_collector()
        
        collector.increment_proposal_count("AAPL", "RISK_APPROVED")
        
        # Get collector again
        collector2 = get_metrics_collector()
        
        # Should have same data
        assert collector2.proposal_count[("AAPL", "RISK_APPROVED")] >= 1
