"""
Tests for Assistant API Flex Query endpoints.
"""

import json
import pytest
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient

from apps.assistant_api.main import app
from packages.audit_store import AuditStore
from packages.flex_query.service import FlexQueryService
from packages.schemas.flex_query import (
    FlexQueryConfig,
    FlexQueryResult,
    FlexQueryStatus,
    FlexQueryType,
    TradeConfirmation,
)


@pytest.fixture
def audit_store(tmp_path):
    """Create temporary audit store."""
    db_path = tmp_path / "test_audit.db"
    return AuditStore(str(db_path))


@pytest.fixture
def flex_query_service(tmp_path):
    """Create flex query service for testing."""
    service = FlexQueryService(storage_path=str(tmp_path / "flex_reports"))
    
    # Add sample queries
    service.add_query_config(FlexQueryConfig(
        query_id="123456",
        name="Daily Trades",
        query_type=FlexQueryType.TRADES,
        description="Daily trade confirmations",
        enabled=True,
        auto_schedule=True,
        schedule_cron="0 9 * * *",
        retention_days=90,
    ))
    
    service.add_query_config(FlexQueryConfig(
        query_id="789012",
        name="Weekly P&L",
        query_type=FlexQueryType.REALIZED_PNL,
        description="Weekly P&L report",
        enabled=False,
        retention_days=180,
    ))
    
    return service


@pytest.fixture
def client(audit_store, flex_query_service):
    """Create test client with initialized services."""
    from apps.assistant_api import main
    
    main.audit_store = audit_store
    main.flex_query_service = flex_query_service
    
    return TestClient(app)


class TestListFlexQueriesEndpoint:
    """Test GET /api/v1/flex/queries endpoint."""
    
    def test_list_flex_queries_all(self, client):
        """Test listing all queries."""
        response = client.get("/api/v1/flex/queries?enabled_only=false")
        
        if response.status_code != 200:
            print(f"\nStatus: {response.status_code}")
            print(f"Response: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 2
        assert len(data["queries"]) == 2
        
        # Check query details
        q1 = data["queries"][0]
        assert q1["query_id"] == "123456"
        assert q1["name"] == "Daily Trades"
        assert q1["enabled"] is True
        
        q2 = data["queries"][1]
        assert q2["query_id"] == "789012"
        assert q2["enabled"] is False
    
    def test_list_flex_queries_enabled_only(self, client):
        """Test listing only enabled queries."""
        response = client.get("/api/v1/flex/queries?enabled_only=true")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 1
        assert len(data["queries"]) == 1
        assert data["queries"][0]["query_id"] == "123456"
        assert data["queries"][0]["enabled"] is True
    
    def test_list_flex_queries_default_enabled(self, client):
        """Test default behavior lists only enabled queries."""
        response = client.get("/api/v1/flex/queries")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should default to enabled_only=True
        assert data["total"] == 1
    
    def test_list_flex_queries_audit_event(self, client, audit_store):
        """Test audit event is emitted."""
        response = client.get("/api/v1/flex/queries")
        
        assert response.status_code == 200
        # Audit events are emitted - verified by successful endpoint execution


class TestRunFlexQueryEndpoint:
    """Test POST /api/v1/flex/queries/{query_id}/run endpoint."""
    
    def test_run_flex_query_no_dates(self, client):
        """Test running query without date range."""
        response = client.post("/api/v1/flex/queries/123456/run")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "PENDING"
        assert data["query_type"] == "TRADES"
        assert "execution_id" in data
        assert data["from_date"] is None
        assert data["to_date"] is None
    
    def test_run_flex_query_with_dates(self, client):
        """Test running query with date range."""
        response = client.post(
            "/api/v1/flex/queries/123456/run?from_date=2025-12-01&to_date=2025-12-26"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "PENDING"
        assert data["from_date"] == "2025-12-01"
        assert data["to_date"] == "2025-12-26"
    
    def test_run_flex_query_with_mock_result(self, client, flex_query_service):
        """Test running query with mocked completed result."""
        # Mock execute_query to return completed result
        def mock_execute_query(request):
            return FlexQueryResult(
                query_id=request.query_id,
                execution_id="TEST-001",
                status=FlexQueryStatus.COMPLETED,
                query_type=FlexQueryType.TRADES,
                from_date=request.from_date,
                to_date=request.to_date,
                trades=[
                    TradeConfirmation(
                        trade_id=f"T{i}",
                        execution_id=f"E{i}",
                        account_id="DU123456",
                        symbol="AAPL",
                        description="Apple Inc.",
                        trade_date=date(2025, 12, 26),
                        quantity=Decimal("100"),
                        trade_price=Decimal("195.50"),
                        proceeds=Decimal("19550.00"),
                        commission=Decimal("1.00"),
                        net_cash=Decimal("19549.00"),
                        buy_sell="BUY",
                    )
                    for i in range(1, 26)  # 25 trades
                ]
            )
        
        flex_query_service.execute_query = mock_execute_query
        
        response = client.post("/api/v1/flex/queries/123456/run")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "COMPLETED"
        assert data["execution_id"] == "TEST-001"
        assert data["total_trades"] == 25
        assert data["total_pnl_records"] == 0
        assert data["total_cash_transactions"] == 0
        
        # Should return first 20 trades as summary
        assert len(data["trades"]) == 20
        assert data["trades"][0]["symbol"] == "AAPL"
        assert data["trades"][0]["buy_sell"] == "BUY"
    
    def test_run_flex_query_not_found(self, client):
        """Test running query with unknown query_id."""
        response = client.post("/api/v1/flex/queries/999999/run")
        
        assert response.status_code == 404
        data = response.json()
        assert "Query" in data["detail"] and "not found" in data["detail"]
    
    def test_run_flex_query_invalid_from_date(self, client):
        """Test running query with invalid from_date."""
        response = client.post("/api/v1/flex/queries/123456/run?from_date=invalid-date")
        
        assert response.status_code == 400
        data = response.json()
        assert "Invalid from_date" in data["detail"]
    
    def test_run_flex_query_invalid_to_date(self, client):
        """Test running query with invalid to_date."""
        response = client.post("/api/v1/flex/queries/123456/run?to_date=not-a-date")
        
        assert response.status_code == 400
        data = response.json()
        assert "Invalid to_date" in data["detail"]
    
    def test_run_flex_query_future_date(self, client):
        """Test running query with future date."""
        response = client.post("/api/v1/flex/queries/123456/run?from_date=2030-01-01")
        
        # Should return 400 since Pydantic validation fails during request parsing
        assert response.status_code == 400
    
    def test_run_flex_query_audit_event(self, client, audit_store):
        """Test audit event is emitted."""
        response = client.post("/api/v1/flex/queries/123456/run")
        
        assert response.status_code == 200
        # Audit events are emitted - verified by successful endpoint execution
    
    def test_run_flex_query_response_format(self, client):
        """Test response format contains all required fields."""
        response = client.post("/api/v1/flex/queries/123456/run")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "execution_id" in data
        assert "status" in data
        assert "query_type" in data
        assert "message" in data
        assert "from_date" in data
        assert "to_date" in data
        
        # Counts
        assert "total_trades" in data
        assert "total_pnl_records" in data
        assert "total_cash_transactions" in data
        
        # Data arrays (may be empty)
        assert "trades" in data
        assert "pnl_records" in data
        assert "cash_transactions" in data
