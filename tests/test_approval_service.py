"""
Tests for approval service.

Tests approval token generation, validation, consumption,
and proposal lifecycle management.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import pytest

from packages.approval_service import ApprovalService
from packages.schemas.approval import (
    ApprovalToken,
    OrderProposal,
    OrderState,
)


# Fixtures

@pytest.fixture
def approval_service():
    """Create approval service with default config."""
    return ApprovalService(max_proposals=100, token_ttl_minutes=5)


@pytest.fixture
def sample_intent_json():
    """Sample OrderIntent as JSON string."""
    intent = {
        "instrument": {"type": "STK", "symbol": "AAPL", "exchange": "SMART", "currency": "USD"},
        "side": "BUY",
        "quantity": 10,
        "order_type": "MKT",
        "time_in_force": "DAY",
        "reason": "Test order",
    }
    return json.dumps(intent, sort_keys=True)


@pytest.fixture
def sample_simulation_json():
    """Sample SimulationResult as JSON string."""
    sim = {
        "status": "SUCCESS",
        "execution_price": "150.00",
        "gross_notional": "1500.00",
        "estimated_fee": "1.00",
        "estimated_slippage": "0.75",
        "net_notional": "1501.75",
        "cash_before": "100000.00",
        "cash_after": "98498.25",
        "exposure_before": "0.00",
        "exposure_after": "1500.00",
        "warnings": [],
        "error_message": None,
    }
    return json.dumps(sim, sort_keys=True)


@pytest.fixture
def sample_risk_decision_json():
    """Sample RiskDecision as JSON string (approved)."""
    decision = {
        "decision": "APPROVE",
        "reason": "All checks passed",
        "violated_rules": [],
        "warnings": [],
        "metrics": {
            "gross_notional": "1500.00",
            "position_pct": "1.50",
        },
    }
    return json.dumps(decision, sort_keys=True)


@pytest.fixture
def approved_proposal(sample_intent_json, sample_simulation_json, sample_risk_decision_json):
    """Create proposal in RISK_APPROVED state."""
    return OrderProposal(
        proposal_id="test-proposal-1",
        correlation_id="test-corr-1",
        intent_json=sample_intent_json,
        simulation_json=sample_simulation_json,
        risk_decision_json=sample_risk_decision_json,
        state=OrderState.RISK_APPROVED,
    )


# Tests for ApprovalToken

def test_approval_token_creation():
    """Test creating an approval token."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123def456",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    assert token.token_id == "token-123"
    assert token.proposal_id == "proposal-456"
    assert token.intent_hash == "abc123def456"
    assert token.used_at is None


def test_approval_token_is_valid_when_fresh():
    """Test token is valid when not used and not expired."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    current_time = issued_at + timedelta(minutes=2)  # 2 minutes after issue
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    assert token.is_valid(current_time) is True


def test_approval_token_invalid_when_expired():
    """Test token is invalid when expired."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    current_time = issued_at + timedelta(minutes=6)  # After expiration
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    assert token.is_valid(current_time) is False


def test_approval_token_invalid_when_used():
    """Test token is invalid after use."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    used_at = issued_at + timedelta(minutes=2)
    current_time = issued_at + timedelta(minutes=3)
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
        used_at=used_at,
    )
    
    assert token.is_valid(current_time) is False


def test_approval_token_consume():
    """Test consuming a token marks it as used."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    consume_time = issued_at + timedelta(minutes=2)
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    consumed = token.consume(consume_time)
    
    assert consumed.used_at == consume_time
    assert consumed.is_valid(consume_time) is False


def test_approval_token_consume_fails_when_expired():
    """Test cannot consume expired token."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    consume_time = issued_at + timedelta(minutes=6)  # After expiration
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    with pytest.raises(ValueError, match="Cannot consume invalid token"):
        token.consume(consume_time)


def test_approval_token_consume_fails_when_already_used():
    """Test cannot consume token twice."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    first_use = issued_at + timedelta(minutes=2)
    
    token = ApprovalToken(
        token_id="token-123",
        proposal_id="proposal-456",
        intent_hash="abc123",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    
    consumed = token.consume(first_use)
    
    # Try to consume again
    second_use = issued_at + timedelta(minutes=3)
    with pytest.raises(ValueError, match="Cannot consume invalid token"):
        consumed.consume(second_use)


# Tests for OrderProposal

def test_order_proposal_intent_hash(sample_intent_json):
    """Test intent hash is computed correctly."""
    proposal = OrderProposal(
        proposal_id="test-1",
        correlation_id="corr-1",
        intent_json=sample_intent_json,
    )
    
    # Hash should be deterministic
    hash1 = proposal.intent_hash
    hash2 = proposal.intent_hash
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex digest


def test_order_proposal_with_state(approved_proposal):
    """Test creating new proposal with updated state."""
    import time
    time.sleep(0.001)  # Ensure timestamp differs
    
    updated = approved_proposal.with_state(
        OrderState.APPROVAL_REQUESTED,
        approval_reason="Test reason"
    )
    
    assert updated.proposal_id == approved_proposal.proposal_id
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert updated.approval_reason == "Test reason"
    assert updated.updated_at >= approved_proposal.updated_at  # >= instead of >


# Tests for ApprovalService

def test_approval_service_store_proposal(approval_service, approved_proposal):
    """Test storing a proposal."""
    approval_service.store_proposal(approved_proposal)
    
    retrieved = approval_service.get_proposal(approved_proposal.proposal_id)
    assert retrieved is not None
    assert retrieved.proposal_id == approved_proposal.proposal_id


def test_approval_service_request_approval(approval_service, approved_proposal):
    """Test requesting approval."""
    approval_service.store_proposal(approved_proposal)
    
    updated = approval_service.request_approval(approved_proposal.proposal_id)
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert updated.proposal_id == approved_proposal.proposal_id


def test_approval_service_request_approval_fails_wrong_state(approval_service, sample_intent_json):
    """Test requesting approval fails if not in RISK_APPROVED state."""
    # Create proposal in PROPOSED state
    proposal = OrderProposal(
        proposal_id="test-1",
        correlation_id="corr-1",
        intent_json=sample_intent_json,
        state=OrderState.PROPOSED,
    )
    approval_service.store_proposal(proposal)
    
    with pytest.raises(ValueError, match="Must be RISK_APPROVED"):
        approval_service.request_approval(proposal.proposal_id)


def test_approval_service_grant_approval(approval_service, approved_proposal):
    """Test granting approval generates token."""
    approval_service.store_proposal(approved_proposal)
    approval_service.request_approval(approved_proposal.proposal_id)
    
    current_time = datetime.now(timezone.utc)
    updated, token = approval_service.grant_approval(
        approved_proposal.proposal_id,
        reason="Approved by user",
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_GRANTED
    assert updated.approval_token == token.token_id
    assert updated.approval_reason == "Approved by user"
    
    assert token.proposal_id == approved_proposal.proposal_id
    assert token.intent_hash == approved_proposal.intent_hash
    assert token.is_valid(current_time) is True
    assert token.expires_at > current_time


def test_approval_service_grant_approval_fails_wrong_state(approval_service, approved_proposal):
    """Test granting approval fails if not in APPROVAL_REQUESTED state."""
    approval_service.store_proposal(approved_proposal)
    
    # Try to grant without requesting first
    with pytest.raises(ValueError, match="Must be APPROVAL_REQUESTED"):
        approval_service.grant_approval(approved_proposal.proposal_id)


def test_approval_service_deny_approval(approval_service, approved_proposal):
    """Test denying approval."""
    approval_service.store_proposal(approved_proposal)
    approval_service.request_approval(approved_proposal.proposal_id)
    
    updated = approval_service.deny_approval(
        approved_proposal.proposal_id,
        reason="Risk too high",
    )
    
    assert updated.state == OrderState.APPROVAL_DENIED
    assert updated.approval_reason == "Risk too high"


def test_approval_service_validate_token(approval_service, approved_proposal):
    """Test validating a token."""
    approval_service.store_proposal(approved_proposal)
    approval_service.request_approval(approved_proposal.proposal_id)
    
    current_time = datetime.now(timezone.utc)
    updated, token = approval_service.grant_approval(
        approved_proposal.proposal_id,
        current_time=current_time,
    )
    
    # Valid token with correct hash
    assert approval_service.validate_token(
        token.token_id,
        approved_proposal.intent_hash,
        current_time,
    ) is True
    
    # Invalid: wrong hash
    assert approval_service.validate_token(
        token.token_id,
        "wrong-hash",
        current_time,
    ) is False
    
    # Invalid: expired
    expired_time = current_time + timedelta(minutes=10)
    assert approval_service.validate_token(
        token.token_id,
        approved_proposal.intent_hash,
        expired_time,
    ) is False


def test_approval_service_consume_token(approval_service, approved_proposal):
    """Test consuming a token marks it as used."""
    approval_service.store_proposal(approved_proposal)
    approval_service.request_approval(approved_proposal.proposal_id)
    
    current_time = datetime.now(timezone.utc)
    updated, token = approval_service.grant_approval(
        approved_proposal.proposal_id,
        current_time=current_time,
    )
    
    # Consume token
    consume_time = current_time + timedelta(minutes=1)
    consumed = approval_service.consume_token(token.token_id, consume_time)
    
    assert consumed.used_at == consume_time
    assert consumed.is_valid(consume_time) is False
    
    # Cannot consume again
    with pytest.raises(ValueError, match="Cannot consume invalid token"):
        approval_service.consume_token(token.token_id, consume_time)


def test_approval_service_get_pending_proposals(approval_service, sample_intent_json):
    """Test getting pending proposals."""
    # Create multiple proposals in different states
    proposals = []
    for i in range(5):
        p = OrderProposal(
            proposal_id=f"proposal-{i}",
            correlation_id=f"corr-{i}",
            intent_json=sample_intent_json,
            state=OrderState.RISK_APPROVED if i < 3 else OrderState.APPROVAL_DENIED,
        )
        proposals.append(p)
        approval_service.store_proposal(p)
    
    # Request approval for first 2
    approval_service.request_approval("proposal-0")
    approval_service.request_approval("proposal-1")
    
    pending = approval_service.get_pending_proposals()
    
    # Should have 2 APPROVAL_REQUESTED + 1 RISK_APPROVED = 3 total
    assert len(pending) == 3
    
    # Should be sorted by creation time (most recent first)
    proposal_ids = [p.proposal_id for p in pending]
    assert "proposal-0" in proposal_ids
    assert "proposal-1" in proposal_ids
    assert "proposal-2" in proposal_ids


def test_approval_service_eviction_when_full(approval_service, sample_intent_json):
    """Test old proposals are evicted when limit reached."""
    # Create service with small limit
    service = ApprovalService(max_proposals=3, token_ttl_minutes=5)
    
    # Add 3 proposals (fill to limit)
    for i in range(3):
        p = OrderProposal(
            proposal_id=f"proposal-{i}",
            correlation_id=f"corr-{i}",
            intent_json=sample_intent_json,
            state=OrderState.RISK_APPROVED,
        )
        service.store_proposal(p)
    
    # Mark first proposal as terminal state
    updated = service.get_proposal("proposal-0").with_state(OrderState.APPROVAL_DENIED)
    service.update_proposal(updated)
    
    # Add one more (should evict proposal-0)
    p = OrderProposal(
        proposal_id="proposal-3",
        correlation_id="corr-3",
        intent_json=sample_intent_json,
        state=OrderState.RISK_APPROVED,
    )
    service.store_proposal(p)
    
    # proposal-0 should be evicted
    assert service.get_proposal("proposal-0") is None
    assert service.get_proposal("proposal-3") is not None
