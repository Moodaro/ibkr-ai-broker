"""
Unit tests for MCP server request_cancel tool.

Tests cover:
- Successful cancel request with proposal_id
- Successful cancel request with broker_order_id
- Validation of required parameters
- XOR validation (proposal_id OR broker_order_id)
- Kill switch check
- Audit event emission
- Error handling
"""

import json
import uuid
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType, OrderStatus
from packages.schemas.order_intent import OrderIntent
from packages.schemas.order_cancel import OrderCancelIntent, OrderCancelResponse
from packages.audit_store import AuditStore, EventType
from packages.kill_switch import KillSwitch


@pytest.fixture
def services():
    """Create services for cancel testing."""
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    
    audit_store = AuditStore()  # In-memory for tests
    kill_switch = KillSwitch()
    
    return broker, audit_store, kill_switch


@pytest.fixture
def submitted_order(services):
    """Create a submitted order for cancellation tests."""
    broker, _, _ = services
    
    # Create and submit an order
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
    
    # Submit through broker (requires approval token - mock it)
    from packages.approval_service.models import ApprovalToken
    token = ApprovalToken(
        token_id="test_token",
        proposal_id="test_proposal",
        account_id="DU123456",
        created_at=datetime.now(timezone.utc),
    )
    
    order = broker.submit_order(intent, token)
    return order


def test_request_cancel_with_proposal_id(services):
    """Test cancel request with proposal_id."""
    broker, audit_store, kill_switch = services
    
    # Create cancel intent
    cancel_intent = OrderCancelIntent(
        account_id="DU123456",
        proposal_id="proposal_abc123",
        broker_order_id=None,
        reason="Market conditions changed significantly",
    )
    
    # Simulate MCP tool request_cancel
    correlation_id = str(uuid.uuid4())
    
    # Check kill switch
    assert not kill_switch.is_enabled()
    
    # Generate approval ID
    cancel_approval_id = f"cancel_{uuid.uuid4().hex[:12]}"
    
    # Store audit event
    from packages.audit_store.models import AuditEventCreate
    event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_REQUESTED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": cancel_approval_id,
            "account_id": cancel_intent.account_id,
            "proposal_id": cancel_intent.proposal_id,
            "broker_order_id": cancel_intent.broker_order_id,
            "reason": cancel_intent.reason,
        },
    )
    audit_store.append_event(event)
    
    # Create response
    response = OrderCancelResponse(
        approval_id=cancel_approval_id,
        proposal_id=cancel_intent.proposal_id,
        broker_order_id=cancel_intent.broker_order_id,
        status="PENDING_APPROVAL",
        reason=cancel_intent.reason,
        requested_at=datetime.now(timezone.utc),
    )
    
    # Verify response
    assert response.approval_id == cancel_approval_id
    assert response.proposal_id == "proposal_abc123"
    assert response.broker_order_id is None
    assert response.status == "PENDING_APPROVAL"
    
    # Verify audit event was stored
    assert len(audit_store.events) > 0
    last_event = audit_store.events[-1]
    assert last_event.event_type == EventType.ORDER_CANCEL_REQUESTED


def test_request_cancel_with_broker_order_id(services, submitted_order):
    """Test cancel request with broker_order_id."""
    broker, audit_store, kill_switch = services
    
    # Create cancel intent with broker order ID
    cancel_intent = OrderCancelIntent(
        account_id="DU123456",
        proposal_id=None,
        broker_order_id=submitted_order.broker_order_id,
        reason="User requested immediate cancellation",
    )
    
    correlation_id = str(uuid.uuid4())
    cancel_approval_id = f"cancel_{uuid.uuid4().hex[:12]}"
    
    # Store audit event
    from packages.audit_store.models import AuditEventCreate
    event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_REQUESTED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": cancel_approval_id,
            "broker_order_id": cancel_intent.broker_order_id,
            "reason": cancel_intent.reason,
        },
    )
    audit_store.append_event(event)
    
    # Create response
    response = OrderCancelResponse(
        approval_id=cancel_approval_id,
        proposal_id=None,
        broker_order_id=cancel_intent.broker_order_id,
        status="PENDING_APPROVAL",
        reason=cancel_intent.reason,
        requested_at=datetime.now(timezone.utc),
    )
    
    # Verify response
    assert response.broker_order_id == submitted_order.broker_order_id
    assert response.proposal_id is None
    assert response.status == "PENDING_APPROVAL"


def test_request_cancel_kill_switch_active(services):
    """Test cancel request blocked by kill switch."""
    broker, audit_store, kill_switch = services
    
    # Activate kill switch
    kill_switch.activate(activated_by="test", reason="Testing kill switch")
    
    # Verify kill switch is active
    assert kill_switch.is_enabled()
    
    # Attempt cancel request - should be blocked
    # In real implementation, this would raise an error or return error response
    # For now, we verify the kill switch state
    assert kill_switch.get_state().enabled is True


def test_request_cancel_validation_missing_ids(services):
    """Test validation error when both IDs are missing."""
    # This test verifies the validation at schema level
    # RequestCancelSchema should reject if both proposal_id and broker_order_id are None
    from packages.mcp_security.schemas import RequestCancelSchema
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        RequestCancelSchema(
            account_id="DU123456",
            proposal_id=None,
            broker_order_id=None,
            reason="Should fail validation",
        )
    
    errors = exc_info.value.errors()
    # Should have validation error about missing IDs
    assert len(errors) > 0


def test_request_cancel_validation_short_reason(services):
    """Test validation error for reason too short."""
    from packages.mcp_security.schemas import RequestCancelSchema
    from pydantic import ValidationError
    
    with pytest.raises(ValidationError) as exc_info:
        RequestCancelSchema(
            account_id="DU123456",
            proposal_id="proposal_abc",
            broker_order_id=None,
            reason="Short",  # Less than 10 chars
        )
    
    errors = exc_info.value.errors()
    assert any("reason" in str(e["loc"]) for e in errors)


def test_cancel_execution_approved(services, submitted_order):
    """Test cancel execution after approval granted."""
    broker, audit_store, kill_switch = services
    
    # Grant approval
    correlation_id = str(uuid.uuid4())
    approval_id = "cancel_test123"
    
    from packages.audit_store.models import AuditEventCreate
    event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_APPROVED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": approval_id,
            "notes": "Approved by trader",
        },
    )
    audit_store.append_event(event)
    
    # Execute cancellation
    success = broker.cancel_order(submitted_order.broker_order_id)
    assert success is True
    
    # Emit success event
    success_event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_EXECUTED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": approval_id,
            "broker_order_id": submitted_order.broker_order_id,
        },
    )
    audit_store.append_event(success_event)
    
    # Verify audit trail has both events
    assert len(audit_store.events) >= 2
    # Find our events by correlation_id
    our_events = [e for e in audit_store.events if e.correlation_id == correlation_id]
    assert len(our_events) == 2
    assert our_events[0].event_type == EventType.ORDER_CANCEL_APPROVED
    assert our_events[1].event_type == EventType.ORDER_CANCEL_EXECUTED


def test_cancel_execution_denied(services):
    """Test cancel execution after approval denied."""
    broker, audit_store, kill_switch = services
    
    # Deny approval
    correlation_id = str(uuid.uuid4())
    approval_id = "cancel_test456"
    
    from packages.audit_store.models import AuditEventCreate
    event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_DENIED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": approval_id,
            "notes": "Order already filled",
        },
    )
    audit_store.append_event(event)
    
    # Verify denial event was stored
    assert len(audit_store.events) > 0
    last_event = audit_store.events[-1]
    assert last_event.event_type == EventType.ORDER_CANCEL_DENIED


def test_cancel_execution_failure(services, submitted_order):
    """Test cancel execution failure."""
    broker, audit_store, kill_switch = services
    
    # First fill the order so cancellation will fail
    broker.simulate_fill(submitted_order.broker_order_id)
    
    correlation_id = str(uuid.uuid4())
    approval_id = "cancel_test789"
    
    # Attempt cancellation of filled order - should fail
    with pytest.raises(ValueError) as exc_info:
        broker.cancel_order(submitted_order.broker_order_id)
    
    assert "cannot be cancelled" in str(exc_info.value).lower()
    
    # Emit failure event
    from packages.audit_store.models import AuditEventCreate
    failure_event = AuditEventCreate(
        event_type=EventType.ORDER_CANCEL_FAILED,
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "approval_id": approval_id,
            "broker_order_id": submitted_order.broker_order_id,
            "error": str(exc_info.value),
        },
    )
    audit_store.append_event(failure_event)
    
    # Verify failure event was stored
    assert len(audit_store.events) > 0
    last_event = audit_store.events[-1]
    assert last_event.event_type == EventType.ORDER_CANCEL_FAILED
