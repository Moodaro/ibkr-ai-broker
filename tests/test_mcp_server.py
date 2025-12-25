"""
Tests for MCP server.
"""

import json
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from apps.mcp_server.main import (
    emit_audit_event,
    handle_get_portfolio,
    handle_get_positions,
    handle_get_cash,
    handle_get_open_orders,
    handle_simulate_order,
    handle_evaluate_risk,
)
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
from packages.trade_sim import TradeSimulator, SimulationConfig


@pytest.fixture
def mock_audit_store(tmp_path, monkeypatch):
    """Mock audit store."""
    from packages.audit_store import AuditStore
    import apps.mcp_server.main as mcp_main
    
    store = AuditStore(str(tmp_path / "test_mcp_audit.db"))
    monkeypatch.setattr(mcp_main, "audit_store", store)
    return store


@pytest.fixture
def mock_broker(monkeypatch):
    """Mock broker adapter."""
    import apps.mcp_server.main as mcp_main
    
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    monkeypatch.setattr(mcp_main, "broker", broker)
    return broker


@pytest.fixture
def mock_simulator(monkeypatch):
    """Mock trade simulator."""
    import apps.mcp_server.main as mcp_main
    
    simulator = TradeSimulator(config=SimulationConfig())
    monkeypatch.setattr(mcp_main, "simulator", simulator)
    return simulator


@pytest.fixture
def mock_risk_engine(monkeypatch):
    """Mock risk engine."""
    import apps.mcp_server.main as mcp_main
    
    engine = RiskEngine(
        limits=RiskLimits(
            max_notional=Decimal("100000"),
            max_position_pct=Decimal("100.0"),
        ),
        trading_hours=TradingHours(allow_pre_market=True, allow_after_hours=True),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )
    monkeypatch.setattr(mcp_main, "risk_engine", engine)
    return engine


@pytest.mark.asyncio
async def test_get_portfolio(mock_audit_store, mock_broker):
    """Test get_portfolio tool."""
    result = await handle_get_portfolio({"account_id": "DU123456"})
    
    assert len(result) == 1
    assert result[0].type == "text"
    
    data = json.loads(result[0].text)
    assert data["account_id"] == "DU123456"
    assert "total_value" in data
    assert "positions" in data
    assert "cash" in data


@pytest.mark.asyncio
async def test_get_portfolio_missing_account_id(mock_audit_store, mock_broker):
    """Test get_portfolio with missing account_id."""
    result = await handle_get_portfolio({})
    
    assert len(result) == 1
    assert "Error" in result[0].text
    assert "account_id is required" in result[0].text


@pytest.mark.asyncio
async def test_get_positions(mock_audit_store, mock_broker):
    """Test get_positions tool."""
    result = await handle_get_positions({"account_id": "DU123456"})
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "positions" in data
    assert "count" in data
    assert isinstance(data["positions"], list)


@pytest.mark.asyncio
async def test_get_cash(mock_audit_store, mock_broker):
    """Test get_cash tool."""
    result = await handle_get_cash({"account_id": "DU123456"})
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "cash" in data
    assert len(data["cash"]) > 0
    assert data["cash"][0]["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_open_orders(mock_audit_store, mock_broker):
    """Test get_open_orders tool."""
    result = await handle_get_open_orders({"account_id": "DU123456"})
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "orders" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_simulate_order_success(mock_audit_store, mock_broker, mock_simulator):
    """Test simulate_order tool with valid parameters."""
    arguments = {
        "account_id": "DU123456",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "10",
        "order_type": "MKT",
        "market_price": "190.00",
    }
    
    result = await handle_simulate_order(arguments)
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "SUCCESS"
    assert "gross_notional" in data
    assert "estimated_fees" in data
    assert "cash_after" in data


@pytest.mark.asyncio
async def test_simulate_order_missing_params(mock_audit_store, mock_broker, mock_simulator):
    """Test simulate_order with missing parameters."""
    arguments = {
        "account_id": "DU123456",
        # Missing other required params
    }
    
    result = await handle_simulate_order(arguments)
    
    assert len(result) == 1
    assert "Error" in result[0].text


@pytest.mark.asyncio
async def test_evaluate_risk_approve(mock_audit_store, mock_broker, mock_simulator, mock_risk_engine):
    """Test evaluate_risk tool - should approve small order."""
    arguments = {
        "account_id": "DU123456",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "10",
        "order_type": "MKT",
        "market_price": "190.00",
    }
    
    result = await handle_evaluate_risk(arguments)
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["decision"] == "APPROVE"
    assert "reason" in data
    assert "violated_rules" in data
    assert len(data["violated_rules"]) == 0


@pytest.mark.asyncio
async def test_evaluate_risk_reject(mock_audit_store, mock_broker, mock_simulator, mock_risk_engine):
    """Test evaluate_risk tool - should reject large order."""
    arguments = {
        "account_id": "DU123456",
        "symbol": "TSLA",
        "side": "BUY",
        "quantity": "10000",  # Very large quantity
        "order_type": "MKT",
        "market_price": "250.00",
    }
    
    result = await handle_evaluate_risk(arguments)
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["decision"] == "REJECT"
    assert len(data["violated_rules"]) > 0


@pytest.mark.asyncio
async def test_audit_event_emission(mock_audit_store, mock_broker):
    """Test that tool calls emit audit events."""
    from packages.audit_store import AuditQuery
    
    # Call tool
    await handle_get_portfolio({"account_id": "DU123456"})
    
    # Query audit events
    query = AuditQuery(limit=10)
    events = mock_audit_store.query_events(query)
    
    # Should have at least one event for get_portfolio
    tool_events = [e for e in events if e.data.get("tool_name") == "get_portfolio"]
    assert len(tool_events) > 0
    
    # Check event structure
    event = tool_events[0]
    assert event.data["tool_name"] == "get_portfolio"
    assert "parameters" in event.data
    assert event.data["parameters"]["account_id"] == "DU123456"


@pytest.mark.asyncio
async def test_simulate_order_with_limit_price(mock_audit_store, mock_broker, mock_simulator):
    """Test simulate_order with limit order."""
    arguments = {
        "account_id": "DU123456",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "10",
        "order_type": "LMT",
        "limit_price": "185.00",
        "market_price": "190.00",
    }
    
    result = await handle_simulate_order(arguments)
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_evaluate_risk_with_warnings(mock_audit_store, mock_broker, mock_simulator, mock_risk_engine):
    """Test evaluate_risk returns warnings near limits."""
    # Order that's close to limits but not over
    arguments = {
        "account_id": "DU123456",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "400",  # Large but not rejected
        "order_type": "MKT",
        "market_price": "190.00",
    }
    
    result = await handle_evaluate_risk(arguments)
    
    assert len(result) == 1
    data = json.loads(result[0].text)
    # May approve with warnings or reject depending on limits
    assert "decision" in data
    assert "warnings" in data


@pytest.mark.asyncio
async def test_error_handling_broker_not_initialized(mock_audit_store, monkeypatch):
    """Test error handling when broker not initialized."""
    import apps.mcp_server.main as mcp_main
    
    # Set broker to None
    monkeypatch.setattr(mcp_main, "broker", None)
    
    result = await handle_get_portfolio({"account_id": "DU123456"})
    
    assert len(result) == 1
    assert "Error" in result[0].text
    assert "not initialized" in result[0].text.lower()


@pytest.mark.asyncio
async def test_decimal_serialization(mock_audit_store, mock_broker):
    """Test that Decimal values are properly serialized."""
    result = await handle_get_portfolio({"account_id": "DU123456"})
    
    # Should not raise JSON serialization error
    data = json.loads(result[0].text)
    
    # All numeric values should be strings (from Decimal serialization)
    assert isinstance(data["total_value"], str)
    if data["positions"]:
        assert isinstance(data["positions"][0]["quantity"], str)
