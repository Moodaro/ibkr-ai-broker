"""Tests for health check endpoint.

NOTE: These are basic structure tests. The health endpoint returns component
status based on global state initialized during app startup.
"""

import pytest
from fastapi.testclient import TestClient


def test_health_check_structure():
    """Test health check returns correct structure."""
    from apps.assistant_api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    
    response = client.get("/api/v1/health")
    
    # Should return 200 OK
    assert response.status_code == 200
    data = response.json()
    
    # Check top-level structure
    assert "status" in data
    assert "components" in data
    assert "timestamp" in data
    assert "correlation_id" in data
    
    # Status should be one of valid values
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    
    # Components should be a dict
    assert isinstance(data["components"], dict)
    assert len(data["components"]) > 0


def test_health_check_components_present():
    """Test health check includes all expected components."""
    from apps.assistant_api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    
    data = response.json()
    components = data["components"]
    
    # All components should be present
    expected_components = [
        "kill_switch",
        "audit_store",
        "broker",
        "approval_service",
        "risk_engine",
        "simulator",
        "order_submitter",
    ]
    
    for component in expected_components:
        assert component in components, f"Missing component: {component}"
        assert "status" in components[component]
        assert "message" in components[component]


def test_health_check_idempotent():
    """Test health check can be called multiple times."""
    from apps.assistant_api.main import app
    client = TestClient(app, raise_server_exceptions=False)
    
    response1 = client.get("/api/v1/health")
    response2 = client.get("/api/v1/health")
    
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    data1 = response1.json()
    data2 = response2.json()
    
    # Status should be consistent (ignoring timestamp)
    assert data1["status"] == data2["status"]


