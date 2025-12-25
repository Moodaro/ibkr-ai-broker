"""
API tests for safety checks endpoint.
"""

import pytest
from fastapi.testclient import TestClient
import os

from apps.assistant_api.main import app


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


class TestSafetyChecksAPI:
    """Tests for GET /api/v1/safety-checks/status endpoint."""
    
    def test_get_safety_checks_success(self, client):
        """Test safety checks endpoint returns valid response."""
        response = client.get("/api/v1/safety-checks/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "ready_for_live" in data
        assert "checks_passed" in data
        assert "checks_total" in data
        assert "checks" in data
        assert "blocking_issues" in data
        assert "warnings" in data
        assert "recommendations" in data
        assert "timestamp" in data
        
        # Verify types
        assert isinstance(data["ready_for_live"], bool)
        assert isinstance(data["checks_passed"], int)
        assert isinstance(data["checks_total"], int)
        assert isinstance(data["checks"], list)
        assert isinstance(data["blocking_issues"], list)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["recommendations"], list)
        
        # Should have 7 checks
        assert data["checks_total"] == 7
        assert len(data["checks"]) == 7
    
    def test_get_safety_checks_structure(self, client):
        """Test safety checks response has correct check structure."""
        response = client.get("/api/v1/safety-checks/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify each check has required fields
        for check in data["checks"]:
            assert "name" in check
            assert "status" in check
            assert "severity" in check
            assert "message" in check
            assert "details" in check
            assert "timestamp" in check
            
            # Verify enums are valid strings
            assert check["status"] in ["PASS", "FAIL", "WARNING", "SKIP"]
            assert check["severity"] in ["BLOCKER", "CRITICAL", "WARNING", "INFO"]
    
    def test_get_safety_checks_check_names(self, client):
        """Test safety checks includes all expected checks."""
        response = client.get("/api/v1/safety-checks/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Extract check names
        check_names = {check["name"] for check in data["checks"]}
        
        # Expected checks
        expected_names = {
            "Test Coverage",
            "Audit Backup",
            "Alerting System",
            "Reconciliation System",
            "Kill Switch",
            "Feature Flags",
            "Statistics Collection",
        }
        
        assert check_names == expected_names
    
    def test_get_safety_checks_decision_logic(self, client):
        """Test safety checks ready_for_live logic."""
        response = client.get("/api/v1/safety-checks/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # If no blocking issues, should be ready
        if len(data["blocking_issues"]) == 0:
            assert data["ready_for_live"] is True
        else:
            # If blocking issues, should not be ready
            assert data["ready_for_live"] is False
    
    def test_get_safety_checks_idempotent(self, client):
        """Test safety checks can be called multiple times."""
        response1 = client.get("/api/v1/safety-checks/status")
        response2 = client.get("/api/v1/safety-checks/status")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Should have same structure
        assert data1["checks_total"] == data2["checks_total"]
        assert data1["checks_passed"] == data2["checks_passed"]
        
        # Check names should match
        names1 = {check["name"] for check in data1["checks"]}
        names2 = {check["name"] for check in data2["checks"]}
        assert names1 == names2
    
    def test_get_safety_checks_with_alerting_configured(self, client):
        """Test safety checks with alerting configured."""
        # Configure alerting
        os.environ["ALERT_SMTP_HOST"] = "smtp.example.com"
        
        try:
            response = client.get("/api/v1/safety-checks/status")
            
            assert response.status_code == 200
            data = response.json()
            
            # Find alerting check
            alerting_check = next(
                (c for c in data["checks"] if c["name"] == "Alerting System"),
                None
            )
            
            assert alerting_check is not None
            # Should pass if module exists and alerting is configured
            if alerting_check["status"] != "FAIL":  # Module exists
                assert alerting_check["status"] in ["PASS", "WARNING"]
        
        finally:
            os.environ.pop("ALERT_SMTP_HOST", None)
    
    def test_get_safety_checks_recommendations(self, client):
        """Test safety checks provides recommendations."""
        response = client.get("/api/v1/safety-checks/status")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have recommendations list (may be empty)
        assert isinstance(data["recommendations"], list)
        
        # If not ready, should have recommendations
        if not data["ready_for_live"]:
            # Should have either blocking issues or warnings
            assert len(data["blocking_issues"]) > 0 or len(data["warnings"]) > 0
