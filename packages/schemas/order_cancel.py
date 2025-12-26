"""
Order cancellation schemas for IBKR AI Broker.

Defines Pydantic models for order cancel request/response flow.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class OrderCancelIntent(BaseModel):
    """
    Intent to cancel an order.
    
    Can reference either:
    - proposal_id: Internal approval system ID (from request_approval)
    - broker_order_id: IBKR order ID (from submitted orders)
    
    At least one must be provided.
    """
    model_config = ConfigDict(extra="forbid")
    
    proposal_id: Optional[str] = Field(None, min_length=1, max_length=100, description="Internal approval/proposal ID")
    broker_order_id: Optional[str] = Field(None, min_length=1, max_length=100, description="Broker order ID (IBKR)")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for cancellation")
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")


class OrderCancelRequest(BaseModel):
    """Request to cancel an order (for API endpoint)."""
    model_config = ConfigDict(extra="forbid")
    
    proposal_id: Optional[str] = Field(None, description="Proposal ID to cancel")
    broker_order_id: Optional[str] = Field(None, description="Broker order ID to cancel")
    reason: str = Field(..., min_length=10, description="Reason for cancellation")


class OrderCancelResponse(BaseModel):
    """Response after requesting order cancellation approval."""
    model_config = ConfigDict(extra="forbid")
    
    approval_id: str = Field(..., description="Approval ID for the cancel request")
    proposal_id: Optional[str] = Field(None, description="Original proposal ID (if applicable)")
    broker_order_id: Optional[str] = Field(None, description="Broker order ID to cancel")
    status: str = Field(..., description="Status: PENDING_APPROVAL")
    reason: str = Field(..., description="Reason for cancellation")
    requested_at: datetime = Field(default_factory=lambda: datetime.now(), description="Request timestamp")


class CancelExecutionRequest(BaseModel):
    """Request to execute an approved cancellation."""
    model_config = ConfigDict(extra="forbid")
    
    approval_id: str = Field(..., min_length=1, description="Approval ID")
    action: str = Field(..., pattern="^(grant|deny)$", description="Action: grant or deny")
    notes: Optional[str] = Field(None, max_length=500, description="Optional notes")


class CancelExecutionResponse(BaseModel):
    """Response after executing a cancellation."""
    model_config = ConfigDict(extra="forbid")
    
    approval_id: str = Field(..., description="Approval ID")
    broker_order_id: Optional[str] = Field(None, description="Broker order ID that was cancelled")
    status: str = Field(..., description="CANCELLED | FAILED | DENIED")
    message: str = Field(..., description="Human-readable result message")
    cancelled_at: Optional[datetime] = Field(None, description="Cancellation timestamp")
    error: Optional[str] = Field(None, description="Error message if failed")
