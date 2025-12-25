"""API tests for performance monitoring endpoints."""

import pytest
from fastapi.testclient import TestClient

from apps.assistant_api.main import app
from packages.performance_monitor import get_performance_monitor


@pytest.fixture
def client():
    """Test client."""
    return TestClient(app)


@pytest.fixture
def monitor():
    """Fresh performance monitor with sample data."""
    import packages.performance_monitor
    packages.performance_monitor._performance_monitor = None
    
    monitor = get_performance_monitor()
    
    # Add sample operations
    for i in range(10):
        monitor.record_operation("test_op", latency_ms=100 + i * 10, success=True)
    
    for i in range(5):
        monitor.record_operation("another_op", latency_ms=50 + i * 5, success=True)
    
    # Collect system metrics
    monitor.collect_system_metrics()
    
    return monitor


class TestPerformanceOperationsEndpoints:
    """Tests for /api/v1/performance/operations endpoints."""
    
    def test_get_all_operations(self, client, monitor):
        """Test getting all operation statistics."""
        response = client.get("/api/v1/performance/operations")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "operations" in data
        assert "count" in data
        assert data["count"] >= 2  # At least test_op and another_op
    
    def test_get_all_operations_with_time_filter(self, client, monitor):
        """Test filtering operations by time."""
        response = client.get("/api/v1/performance/operations?since_minutes=5")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "operations" in data
        assert data["since_minutes"] == 5
    
    def test_get_specific_operation(self, client, monitor):
        """Test getting statistics for specific operation."""
        response = client.get("/api/v1/performance/operations/test_op")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["operation_name"] == "test_op"
        assert data["count"] == 10
        assert "avg_latency_ms" in data
        assert "p95_latency_ms" in data
    
    def test_get_nonexistent_operation(self, client, monitor):
        """Test getting stats for non-existent operation."""
        response = client.get("/api/v1/performance/operations/nonexistent")
        
        assert response.status_code == 404


class TestPerformanceSystemEndpoints:
    """Tests for /api/v1/performance/system endpoints."""
    
    def test_get_current_system_metrics(self, client, monitor):
        """Test getting current system metrics."""
        response = client.get("/api/v1/performance/system")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "cpu_percent" in data
        assert "memory_percent" in data
        assert "memory_mb" in data
        assert "process_threads" in data
        assert data["memory_mb"] > 0
    
    def test_get_system_metrics_history(self, client, monitor):
        """Test getting system metrics history."""
        response = client.get("/api/v1/performance/system/history?since_minutes=10&limit=50")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "metrics" in data
        assert "count" in data
        assert data["since_minutes"] == 10
        assert isinstance(data["metrics"], list)


class TestPerformanceDegradationEndpoint:
    """Tests for /api/v1/performance/degradation endpoint."""
    
    def test_check_degradation(self, client, monitor):
        """Test checking for performance degradation."""
        response = client.get("/api/v1/performance/degradation/test_op?window_minutes=15")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "operation" in data
        assert "degraded" in data
        assert data["operation"] == "test_op"
        assert isinstance(data["degraded"], bool)
