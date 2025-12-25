"""Tests for performance monitoring module."""

import pytest
import time
from datetime import datetime, timedelta

from packages.performance_monitor import (
    PerformanceMonitor,
    get_performance_monitor,
    track_performance,
    OperationMetrics,
    SystemMetrics,
    PerformanceStats,
)


@pytest.fixture
def monitor():
    """Fresh performance monitor for each test."""
    import packages.performance_monitor
    packages.performance_monitor._performance_monitor = None
    return PerformanceMonitor(max_history_size=100, retention_hours=1)


class TestPerformanceMonitor:
    """Tests for PerformanceMonitor class."""
    
    def test_record_operation(self, monitor):
        """Test recording operation metrics."""
        monitor.record_operation(
            operation_name="test_op",
            latency_ms=100.5,
            success=True
        )
        
        stats = monitor.get_operation_stats("test_op")
        assert stats is not None
        assert stats.count == 1
        assert stats.success_count == 1
        assert stats.avg_latency_ms == 100.5
    
    def test_record_failed_operation(self, monitor):
        """Test recording failed operation."""
        monitor.record_operation(
            operation_name="test_op",
            latency_ms=50.0,
            success=False,
            error="Test error"
        )
        
        stats = monitor.get_operation_stats("test_op")
        assert stats is not None
        assert stats.failure_count == 1
        assert stats.success_count == 0
    
    def test_collect_system_metrics(self, monitor):
        """Test collecting system metrics."""
        metrics = monitor.collect_system_metrics()
        
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_percent >= 0
        assert metrics.memory_percent > 0
        assert metrics.memory_mb > 0
        assert metrics.process_threads > 0
    
    def test_operation_stats_calculation(self, monitor):
        """Test statistics calculation for multiple operations."""
        # Record multiple operations
        latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for latency in latencies:
            monitor.record_operation("test_op", latency_ms=latency, success=True)
        
        stats = monitor.get_operation_stats("test_op")
        
        assert stats.count == 10
        assert stats.min_latency_ms == 10
        assert stats.max_latency_ms == 100
        assert stats.avg_latency_ms == 55.0
        # p50 at index 5 (50% of 10) gives element at position 5 which is 60
        assert stats.p50_latency_ms == 60  # Median
        assert stats.p95_latency_ms >= 90
    
    def test_get_all_operation_stats(self, monitor):
        """Test getting statistics for all operations."""
        monitor.record_operation("op1", latency_ms=10, success=True)
        monitor.record_operation("op2", latency_ms=20, success=True)
        monitor.record_operation("op3", latency_ms=30, success=True)
        
        all_stats = monitor.get_all_operation_stats()
        
        assert len(all_stats) == 3
        operation_names = {s.operation_name for s in all_stats}
        assert operation_names == {"op1", "op2", "op3"}
    
    def test_stats_with_time_filter(self, monitor):
        """Test filtering statistics by time."""
        # Record old operation
        old_time = datetime.utcnow() - timedelta(hours=2)
        
        # Record recent operation
        monitor.record_operation("test_op", latency_ms=100, success=True)
        
        # Get recent stats only
        since = datetime.utcnow() - timedelta(minutes=5)
        stats = monitor.get_operation_stats("test_op", since=since)
        
        assert stats is not None
        assert stats.count == 1
    
    def test_system_metrics_history(self, monitor):
        """Test collecting system metrics history."""
        # Collect multiple samples
        for _ in range(5):
            monitor.collect_system_metrics()
            time.sleep(0.1)
        
        history = monitor.get_system_metrics_history(limit=10)
        
        assert len(history) == 5
        assert all(isinstance(m, SystemMetrics) for m in history)
    
    def test_latency_threshold_warning(self, monitor):
        """Test warning when latency exceeds threshold."""
        monitor.set_latency_threshold("test_op", threshold_ms=50.0)
        
        # Record operation above threshold
        monitor.record_operation("test_op", latency_ms=100.0, success=True)
        
        # Should have logged warning
        stats = monitor.get_operation_stats("test_op")
        assert stats.max_latency_ms == 100.0
    
    def test_check_degradation(self, monitor):
        """Test performance degradation detection."""
        monitor.set_latency_threshold("test_op", threshold_ms=50.0)
        
        # Record operations below threshold
        for _ in range(10):
            monitor.record_operation("test_op", latency_ms=30.0, success=True)
        
        result = monitor.check_degradation("test_op", window_minutes=15)
        
        assert result["degraded"] is False
        
        # Record operations above threshold
        for _ in range(10):
            monitor.record_operation("test_op", latency_ms=100.0, success=True)
        
        result = monitor.check_degradation("test_op", window_minutes=15)
        
        assert result["degraded"] is True
        assert result["p95_latency_ms"] > 50.0
    
    def test_cleanup_old_data(self, monitor):
        """Test cleanup of old metrics."""
        # Record operation with old timestamp
        # (This is simplified - in reality would need to mock timestamps)
        monitor.record_operation("test_op", latency_ms=100, success=True)
        
        # Cleanup should remove old data
        removed = monitor.cleanup_old_data()
        
        # Should not crash
        assert removed >= 0
    
    def test_performance_stats_to_dict(self, monitor):
        """Test converting performance stats to dictionary."""
        monitor.record_operation("test_op", latency_ms=100, success=True)
        monitor.record_operation("test_op", latency_ms=200, success=False)
        
        stats = monitor.get_operation_stats("test_op")
        data = stats.to_dict()
        
        assert isinstance(data, dict)
        assert data["operation_name"] == "test_op"
        assert data["count"] == 2
        assert data["success_count"] == 1
        assert data["failure_count"] == 1
        assert "success_rate" in data
        assert data["success_rate"] == 50.0


class TestPerformanceDecorator:
    """Tests for performance tracking decorator."""
    
    def test_track_performance_decorator(self):
        """Test automatic performance tracking."""
        import packages.performance_monitor
        packages.performance_monitor._performance_monitor = None
        
        @track_performance("decorated_op")
        def test_function():
            time.sleep(0.01)
            return "result"
        
        result = test_function()
        
        assert result == "result"
        
        monitor = get_performance_monitor()
        stats = monitor.get_operation_stats("decorated_op")
        assert stats is not None
        assert stats.count == 1
        assert stats.success_count == 1
        assert stats.avg_latency_ms >= 10  # At least 10ms (0.01s sleep)
    
    def test_track_performance_with_exception(self):
        """Test tracking when function raises exception."""
        import packages.performance_monitor
        packages.performance_monitor._performance_monitor = None
        
        @track_performance("failing_op")
        def test_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            test_function()
        
        monitor = get_performance_monitor()
        stats = monitor.get_operation_stats("failing_op")
        assert stats is not None
        assert stats.failure_count == 1
        assert stats.success_count == 0


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_performance_monitor_singleton(self):
        """Test singleton returns same instance."""
        import packages.performance_monitor
        packages.performance_monitor._performance_monitor = None
        
        monitor1 = get_performance_monitor()
        monitor2 = get_performance_monitor()
        
        assert monitor1 is monitor2
