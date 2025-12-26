"""
Unit tests for order cancel flow.

Tests cover:
- Schema validation (XOR logic for proposal_id/broker_order_id)
- Kill switch behavior  
- Broker cancel_order functionality
- Error handling
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType, OrderStatus
from packages.schemas.order_intent import OrderIntent
from packages.schemas.order_cancel import OrderCancelIntent, OrderCancelResponse
from packages.schemas.approval import ApprovalToken
from packages.kill_switch import KillSwitch


@pytest.fixture
def broker():
    """Create fake broker for testing."""
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    return broker


@pytest.fixture
def kill_switch():
    """Create fresh kill switch for each test."""
    ks = KillSwitch()
    # Ensure it starts disabled
    if ks.is_enabled():
        ks.deactivate(deactivated_by="test_fixture")
    return ks


@pytest.fixture
def submitted_order(broker):
    """Create a submitted order for cancellation tests."""
    intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("10"),
        order_type="MKT",
        time_in_force="DAY",
        reason="Test order for cancellation",
        strategy_tag="test_cancel",
    )
    
    # Create proper approval token with all required fields
    from datetime import timedelta
    token = ApprovalToken(
        token_id="test_token",
        proposal_id="test_proposal",
        account_id="DU123456",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        intent_hash="test_hash_12345",
    )
    
    order = broker.submit_order(intent, token)
    return order


def test_cancel_intent_with_proposal_id():
    """Test OrderCancelIntent with proposal_id."""
    intent = OrderCancelIntent(
        account_id="DU123456",
        proposal_id="proposal_abc123",
        broker_order_id=None,
        reason="Market conditions changed significantly",
    )
    
    assert intent.account_id == "DU123456"
    assert intent.proposal_id == "proposal_abc123"
    assert intent.broker_order_id is None


def test_cancel_intent_with_broker_order_id():
    """Test OrderCancelIntent with broker_order_id."""
    intent = OrderCancelIntent(
        account_id="DU123456",
        proposal_id=None,
        broker_order_id="MOCK12345678",
        reason="User requested immediate cancellation",
    )
    
    assert intent.broker_order_id == "MOCK12345678"
    assert intent.proposal_id is None


def test_kill_switch_activation(kill_switch):
    """Test kill switch activation and deactivation."""
    # Initially disabled
    assert not kill_switch.is_enabled()
    
    # Activate
    kill_switch.activate(activated_by="test", reason="Testing")
    assert kill_switch.is_enabled()
    
    # Deactivate
    kill_switch.deactivate(deactivated_by="test")
    assert not kill_switch.is_enabled()


def test_broker_cancel_order_success(broker, submitted_order):
    """Test successful order cancellation."""
    # Verify order is submitted
    assert submitted_order.status == OrderStatus.SUBMITTED
    
    # Cancel order
    success = broker.cancel_order(submitted_order.broker_order_id)
    assert success is True
    
    # Verify order is cancelled
    cancelled_order = broker.get_order_status(submitted_order.broker_order_id)
    assert cancelled_order.status == OrderStatus.CANCELLED


def test_broker_cancel_filled_order_fails(broker, submitted_order):
    """Test cancellation fails for filled orders."""
    # Fill the order first
    broker.simulate_fill(submitted_order.broker_order_id)
    
    # Attempt to cancel - should raise ValueError
    with pytest.raises(ValueError) as exc_info:
        broker.cancel_order(submitted_order.broker_order_id)
    
    assert "cannot be cancelled" in str(exc_info.value).lower()


def test_broker_cancel_nonexistent_order(broker):
    """Test cancellation fails for non-existent order."""
    with pytest.raises(ValueError) as exc_info:
        broker.cancel_order("NONEXISTENT123")
    
    assert "not found" in str(exc_info.value).lower()


def test_cancel_response_structure():
    """Test OrderCancelResponse structure."""
    response = OrderCancelResponse(
        approval_id="cancel_abc123def456",
        proposal_id="proposal_xyz",
        broker_order_id=None,
        status="PENDING_APPROVAL",
        reason="Market changed",
        requested_at=datetime.now(timezone.utc),
    )
    
    assert response.approval_id == "cancel_abc123def456"
    assert response.proposal_id == "proposal_xyz"
    assert response.status == "PENDING_APPROVAL"


def test_mcp_schema_xor_validation():
    """Test MCP RequestCancelSchema XOR validation."""
    from packages.mcp_security.schemas import RequestCancelSchema
    from pydantic import ValidationError
    
    # Valid with proposal_id only
    schema = RequestCancelSchema(
        account_id="DU123456",
        proposal_id="proposal_abc",
        broker_order_id=None,
        reason="Valid reason here that is long enough",
    )
    assert schema.proposal_id == "proposal_abc"
    
    # Valid with broker_order_id only
    schema2 = RequestCancelSchema(
        account_id="DU123456",
        proposal_id=None,
        broker_order_id="MOCK123",
        reason="Valid reason here that is long enough",
    )
    assert schema2.broker_order_id == "MOCK123"
    
    # Invalid - both missing (XOR validation should fail)
    with pytest.raises(ValidationError):
        RequestCancelSchema(
            account_id="DU123456",
            proposal_id=None,
            broker_order_id=None,
            reason="Should fail validation",
        )


def test_mcp_schema_reason_validation():
    """Test reason field validation."""
    from packages.mcp_security.schemas import RequestCancelSchema
    from pydantic import ValidationError
    
    # Invalid - reason too short (min 10 chars)
    with pytest.raises(ValidationError) as exc_info:
        RequestCancelSchema(
            account_id="DU123456",
            proposal_id="proposal_abc",
            broker_order_id=None,
            reason="Short",
        )
    
    errors = exc_info.value.errors()
    assert any("reason" in str(e["loc"]) for e in errors)


def test_mcp_schema_forbids_extra_fields():
    """Test that RequestCancelSchema rejects unknown fields."""
    from packages.mcp_security.schemas import RequestCancelSchema
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        RequestCancelSchema(
            account_id="DU123456",
            proposal_id="proposal_abc",
            broker_order_id=None,
            reason="Valid reason here that is long enough",
            unknown_field="should fail",
        )
    
    errors = exc_info.value.errors()
    assert any("unknown_field" in str(e["loc"]) for e in errors)
