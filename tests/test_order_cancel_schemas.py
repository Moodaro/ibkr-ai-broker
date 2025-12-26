"""
Tests for Order Cancel schemas.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from pydantic import ValidationError

from packages.schemas.order_cancel import (
    OrderCancelIntent,
    OrderCancelRequest,
    OrderCancelResponse,
    CancelExecutionRequest,
    CancelExecutionResponse,
)


class TestOrderCancelIntent:
    """Tests for OrderCancelIntent schema."""

    def test_valid_with_proposal_id(self):
        """Test valid intent with proposal_id."""
        intent = OrderCancelIntent(
            account_id="DU12345",
            proposal_id="proposal_abc123",
            broker_order_id=None,
            reason="Market conditions changed significantly",
        )
        assert intent.account_id == "DU12345"
        assert intent.proposal_id == "proposal_abc123"
        assert intent.broker_order_id is None
        assert intent.reason == "Market conditions changed significantly"

    def test_valid_with_broker_order_id(self):
        """Test valid intent with broker_order_id."""
        intent = OrderCancelIntent(
            account_id="DU12345",
            proposal_id=None,
            broker_order_id="MOCK12345678",
            reason="Need to cancel this order",
        )
        assert intent.account_id == "DU12345"
        assert intent.proposal_id is None
        assert intent.broker_order_id == "MOCK12345678"
        assert intent.reason == "Need to cancel this order"

    def test_valid_with_both_ids(self):
        """Test valid intent with both IDs (allowed in OrderCancelIntent)."""
        intent = OrderCancelIntent(
            account_id="DU12345",
            proposal_id="proposal_abc",
            broker_order_id="MOCK12345678",
            reason="Cancel this specific order",
        )
        assert intent.proposal_id == "proposal_abc"
        assert intent.broker_order_id == "MOCK12345678"

    def test_rejects_empty_account_id(self):
        """Test rejection of empty account_id."""
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelIntent(
                account_id="",
                proposal_id="proposal_abc",
                reason="Testing empty account",
            )
        errors = exc_info.value.errors()
        assert any("account_id" in str(e["loc"]) for e in errors)

    def test_rejects_short_reason(self):
        """Test rejection of reason shorter than 10 chars."""
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelIntent(
                account_id="DU12345",
                proposal_id="proposal_abc",
                reason="Short",
            )
        errors = exc_info.value.errors()
        assert any("reason" in str(e["loc"]) for e in errors)

    def test_rejects_long_reason(self):
        """Test rejection of reason longer than 500 chars."""
        long_reason = "x" * 501
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelIntent(
                account_id="DU12345",
                proposal_id="proposal_abc",
                reason=long_reason,
            )
        errors = exc_info.value.errors()
        assert any("reason" in str(e["loc"]) for e in errors)

    def test_rejects_extra_fields(self):
        """Test rejection of unknown fields (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelIntent(
                account_id="DU12345",
                proposal_id="proposal_abc",
                reason="Valid reason here",
                unknown_field="should fail",
            )
        errors = exc_info.value.errors()
        assert any("unknown_field" in str(e["loc"]) for e in errors)


class TestOrderCancelRequest:
    """Tests for OrderCancelRequest schema."""

    def test_valid_with_proposal_id(self):
        """Test valid request with proposal_id."""
        request = OrderCancelRequest(
            proposal_id="proposal_abc123",
            broker_order_id=None,
            reason="Market volatility too high",
        )
        assert request.proposal_id == "proposal_abc123"
        assert request.broker_order_id is None

    def test_valid_with_broker_order_id(self):
        """Test valid request with broker_order_id."""
        request = OrderCancelRequest(
            proposal_id=None,
            broker_order_id="MOCK12345678",
            reason="Order no longer needed",
        )
        assert request.broker_order_id == "MOCK12345678"

    def test_rejects_extra_fields(self):
        """Test rejection of unknown fields."""
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelRequest(
                proposal_id="proposal_abc",
                reason="Valid reason",
                extra_field="not allowed",
            )
        errors = exc_info.value.errors()
        assert any("extra_field" in str(e["loc"]) for e in errors)


class TestOrderCancelResponse:
    """Tests for OrderCancelResponse schema."""

    def test_valid_response_with_proposal_id(self):
        """Test valid response with proposal_id."""
        now = datetime.now(timezone.utc)
        response = OrderCancelResponse(
            approval_id="cancel_abc123def456",
            proposal_id="proposal_xyz",
            broker_order_id=None,
            status="PENDING_APPROVAL",
            reason="Market changed",
            requested_at=now,
        )
        assert response.approval_id == "cancel_abc123def456"
        assert response.proposal_id == "proposal_xyz"
        assert response.status == "PENDING_APPROVAL"
        assert response.requested_at == now

    def test_valid_response_with_broker_order_id(self):
        """Test valid response with broker_order_id."""
        now = datetime.now(timezone.utc)
        response = OrderCancelResponse(
            approval_id="cancel_123",
            proposal_id=None,
            broker_order_id="MOCK12345",
            status="PENDING_APPROVAL",
            reason="User requested cancel",
            requested_at=now,
        )
        assert response.broker_order_id == "MOCK12345"
        assert response.proposal_id is None

    def test_rejects_extra_fields(self):
        """Test rejection of unknown fields."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError) as exc_info:
            OrderCancelResponse(
                approval_id="cancel_123",
                proposal_id="proposal_abc",
                broker_order_id=None,
                status="PENDING_APPROVAL",
                reason="Valid reason",
                requested_at=now,
                invalid_field="should fail",
            )
        errors = exc_info.value.errors()
        assert any("invalid_field" in str(e["loc"]) for e in errors)


class TestCancelExecutionRequest:
    """Tests for CancelExecutionRequest schema."""

    def test_valid_grant_action(self):
        """Test valid grant action."""
        request = CancelExecutionRequest(
            approval_id="cancel_abc123",
            action="grant",
            notes="Approved by trader",
        )
        assert request.approval_id == "cancel_abc123"
        assert request.action == "grant"
        assert request.notes == "Approved by trader"

    def test_valid_deny_action(self):
        """Test valid deny action."""
        request = CancelExecutionRequest(
            approval_id="cancel_xyz789",
            action="deny",
            notes="Order already filled",
        )
        assert request.action == "deny"

    def test_valid_without_notes(self):
        """Test valid request without notes (optional field)."""
        request = CancelExecutionRequest(
            approval_id="cancel_123",
            action="grant",
        )
        assert request.notes is None

    def test_rejects_invalid_action(self):
        """Test rejection of invalid action."""
        with pytest.raises(ValidationError) as exc_info:
            CancelExecutionRequest(
                approval_id="cancel_123",
                action="invalid_action",
            )
        errors = exc_info.value.errors()
        assert any("action" in str(e["loc"]) for e in errors)

    def test_rejects_extra_fields(self):
        """Test rejection of unknown fields."""
        with pytest.raises(ValidationError) as exc_info:
            CancelExecutionRequest(
                approval_id="cancel_123",
                action="grant",
                unknown="field",
            )
        errors = exc_info.value.errors()
        assert any("unknown" in str(e["loc"]) for e in errors)


class TestCancelExecutionResponse:
    """Tests for CancelExecutionResponse schema."""

    def test_valid_cancelled_status(self):
        """Test valid response with CANCELLED status."""
        now = datetime.now(timezone.utc)
        response = CancelExecutionResponse(
            approval_id="cancel_abc123",
            broker_order_id="MOCK123",
            status="CANCELLED",
            message="Order MOCK123 cancelled successfully",
            cancelled_at=now,
            error=None,
        )
        assert response.status == "CANCELLED"
        assert response.cancelled_at == now
        assert response.error is None
        assert response.approval_id == "cancel_abc123"

    def test_valid_denied_status(self):
        """Test valid response with DENIED status."""
        response = CancelExecutionResponse(
            approval_id="cancel_xyz789",
            broker_order_id=None,
            status="DENIED",
            message="Cancel request denied by user",
            cancelled_at=None,
            error=None,
        )
        assert response.status == "DENIED"
        assert response.cancelled_at is None
        assert response.approval_id == "cancel_xyz789"

    def test_valid_failed_status(self):
        """Test valid response with FAILED status."""
        response = CancelExecutionResponse(
            approval_id="cancel_fail123",
            broker_order_id="MOCK123",
            status="FAILED",
            message="Cancel failed for order MOCK123",
            cancelled_at=None,
            error="Order already filled",
        )
        assert response.status == "FAILED"
        assert response.error == "Order already filled"
        assert response.approval_id == "cancel_fail123"

    def test_rejects_extra_fields(self):
        """Test rejection of unknown fields."""
        with pytest.raises(ValidationError) as exc_info:
            CancelExecutionResponse(
                approval_id="cancel_123",
                broker_order_id=None,
                status="CANCELLED",
                message="Success",
                cancelled_at=None,
                error=None,
                extra_field="not allowed",
            )
        errors = exc_info.value.errors()
        assert any("extra_field" in str(e["loc"]) for e in errors)
