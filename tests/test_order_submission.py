"""
Tests for order submission logic.

Tests token validation, order submission, state transitions,
and broker integration.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import pytest
import uuid

from packages.approval_service import ApprovalService
from packages.audit_store import AuditStore, AuditQuery
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import OrderStatus
from packages.order_submission import OrderSubmitter, OrderSubmissionError
from packages.schemas.approval import OrderState, OrderProposal, ApprovalToken


# Fixtures

@pytest.fixture
def audit_store(tmp_path):
    """Create temporary audit store."""
    db_path = tmp_path / "test_audit.db"
    return AuditStore(str(db_path))


@pytest.fixture
def approval_service():
    """Create approval service."""
    return ApprovalService(max_proposals=100, token_ttl_minutes=5)


@pytest.fixture
def broker():
    """Create fake broker adapter."""
    adapter = FakeBrokerAdapter(account_id="DU123456")
    adapter.connect()
    return adapter


@pytest.fixture
def order_submitter(broker, approval_service, audit_store):
    """Create order submitter."""
    return OrderSubmitter(
        broker=broker,
        approval_service=approval_service,
        audit_store=audit_store,
    )


@pytest.fixture
def sample_intent_json():
    """Sample OrderIntent as JSON."""
    intent = {
        "account_id": "DU123456",
        "instrument": {"type": "STK", "symbol": "AAPL", "exchange": "NASDAQ", "currency": "USD"},
        "side": "BUY",
        "quantity": "10",
        "order_type": "MKT",
        "time_in_force": "DAY",
        "reason": "Test order for submission",
        "strategy_tag": "test",
        "constraints": {},
    }
    return json.dumps(intent, sort_keys=True)


@pytest.fixture
def approved_proposal_with_token(approval_service, sample_intent_json):
    """Create proposal in APPROVAL_GRANTED state with token."""
    proposal_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    
    # Create proposal in RISK_APPROVED state
    proposal = OrderProposal(
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        intent_json=sample_intent_json,
        simulation_json='{"gross_notional": "1900.00"}',
        risk_decision_json='{"decision": "APPROVE"}',
        state=OrderState.RISK_APPROVED,
    )
    approval_service.store_proposal(proposal)
    
    # Request approval
    approval_service.request_approval(proposal_id)
    
    # Grant approval (generates token)
    current_time = datetime.now(timezone.utc)
    updated, token = approval_service.grant_approval(
        proposal_id,
        reason="Test approval",
        current_time=current_time,
    )
    
    return updated, token


# Tests for OrderSubmitter.submit_order

def test_submit_order_success(order_submitter, approved_proposal_with_token):
    """Test successful order submission."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit order
    open_order = order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Verify order submitted
    assert open_order.broker_order_id is not None
    assert open_order.status == OrderStatus.SUBMITTED
    assert open_order.instrument.symbol == "AAPL"
    assert open_order.side == "BUY"
    assert open_order.quantity == Decimal("10")


def test_submit_order_validates_token(order_submitter, approved_proposal_with_token):
    """Test submission fails with invalid token."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Try to submit with wrong token
    with pytest.raises(ValueError, match="Invalid or expired approval token"):
        order_submitter.submit_order(
            proposal_id=proposal.proposal_id,
            token_id="wrong-token-id",
            correlation_id=correlation_id,
            current_time=current_time,
        )


def test_submit_order_consumes_token(order_submitter, approval_service, approved_proposal_with_token):
    """Test token is consumed after submission."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit order
    order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Verify token is consumed
    consumed_token = approval_service.get_token(token.token_id)
    assert consumed_token is not None
    assert consumed_token.used_at is not None
    assert consumed_token.is_valid(current_time) is False


def test_submit_order_cannot_reuse_token(order_submitter, approval_service, approved_proposal_with_token):
    """Test cannot submit order twice with same token."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # First submission succeeds
    order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Get updated proposal (now in SUBMITTED state)
    updated_proposal = approval_service.get_proposal(proposal.proposal_id)
    
    # Second submission fails (proposal already submitted)
    with pytest.raises(ValueError, match="Must be APPROVAL_GRANTED"):
        order_submitter.submit_order(
            proposal_id=proposal.proposal_id,
            token_id=token.token_id,
            correlation_id=correlation_id,
            current_time=current_time + timedelta(seconds=1),
        )


def test_submit_order_transitions_to_submitted(order_submitter, approval_service, approved_proposal_with_token):
    """Test proposal transitions to SUBMITTED state."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit order
    open_order = order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Verify proposal state updated
    updated_proposal = approval_service.get_proposal(proposal.proposal_id)
    assert updated_proposal.state == OrderState.SUBMITTED
    assert updated_proposal.broker_order_id == open_order.broker_order_id


def test_submit_order_requires_approval_granted(order_submitter, approval_service, sample_intent_json):
    """Test cannot submit order not in APPROVAL_GRANTED state."""
    # Create proposal in APPROVAL_REQUESTED state (not granted)
    proposal_id = str(uuid.uuid4())
    proposal = OrderProposal(
        proposal_id=proposal_id,
        correlation_id=str(uuid.uuid4()),
        intent_json=sample_intent_json,
        state=OrderState.APPROVAL_REQUESTED,
    )
    approval_service.store_proposal(proposal)
    
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Try to submit
    with pytest.raises(ValueError, match="Must be APPROVAL_GRANTED"):
        order_submitter.submit_order(
            proposal_id=proposal_id,
            token_id="fake-token",
            correlation_id=correlation_id,
            current_time=current_time,
        )


def test_submit_order_emits_audit_events(order_submitter, audit_store, approved_proposal_with_token):
    """Test submission emits audit events."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit order
    order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Verify audit events
    query = AuditQuery(correlation_id=correlation_id)
    events = audit_store.query_events(query)
    
    # Should have OrderSubmitted event
    submitted_events = [e for e in events if e.event_type == "OrderSubmitted"]
    assert len(submitted_events) > 0
    
    event = submitted_events[0]
    assert event.data["proposal_id"] == proposal.proposal_id
    assert event.data["token_id"] == token.token_id
    assert "broker_order_id" in event.data


# Tests for OrderSubmitter.poll_order_until_terminal

def test_poll_order_until_filled(order_submitter, broker, approval_service, approved_proposal_with_token):
    """Test polling order until FILLED state."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit order
    open_order = order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    # Simulate fill
    broker.simulate_fill(open_order.broker_order_id, fill_price=Decimal("190.00"))
    
    # Poll until terminal
    final_order = order_submitter.poll_order_until_terminal(
        broker_order_id=open_order.broker_order_id,
        proposal_id=proposal.proposal_id,
        correlation_id=correlation_id,
        max_polls=10,
        poll_interval_seconds=0,
    )
    
    # Verify filled
    assert final_order.status == OrderStatus.FILLED
    assert final_order.filled_quantity == Decimal("10")
    assert final_order.average_fill_price == Decimal("190.00")
    
    # Verify proposal updated to FILLED
    updated_proposal = approval_service.get_proposal(proposal.proposal_id)
    assert updated_proposal.state == OrderState.FILLED


def test_poll_order_emits_terminal_event(order_submitter, audit_store, broker, approved_proposal_with_token):
    """Test polling emits terminal event."""
    proposal, token = approved_proposal_with_token
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Submit and fill
    open_order = order_submitter.submit_order(
        proposal_id=proposal.proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    broker.simulate_fill(open_order.broker_order_id)
    
    # Poll
    order_submitter.poll_order_until_terminal(
        broker_order_id=open_order.broker_order_id,
        proposal_id=proposal.proposal_id,
        correlation_id=correlation_id,
        max_polls=10,
        poll_interval_seconds=0,
    )
    
    # Verify terminal event
    query = AuditQuery(correlation_id=correlation_id)
    events = audit_store.query_events(query)
    filled_events = [e for e in events if "Filled" in e.event_type]
    assert len(filled_events) > 0
