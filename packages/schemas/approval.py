"""
Approval system models and enums.

Defines the order lifecycle state machine, approval tokens, and approval requests/responses.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, computed_field
import hashlib
import json


class OrderState(str, Enum):
    """Order lifecycle states in the two-step commit flow."""
    
    PROPOSED = "PROPOSED"  # Initial state: OrderIntent created
    SIMULATED = "SIMULATED"  # Simulation completed
    RISK_APPROVED = "RISK_APPROVED"  # Risk gate approved
    RISK_REJECTED = "RISK_REJECTED"  # Risk gate rejected
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"  # Awaiting human/auto approval
    APPROVAL_GRANTED = "APPROVAL_GRANTED"  # Approved by human/auto
    APPROVAL_DENIED = "APPROVAL_DENIED"  # Denied by human
    SUBMITTED = "SUBMITTED"  # Submitted to broker
    FILLED = "FILLED"  # Order filled by broker
    CANCELLED = "CANCELLED"  # Order cancelled
    REJECTED = "REJECTED"  # Order rejected by broker


class OrderProposal(BaseModel):
    """
    Complete order proposal with lifecycle tracking.
    
    Contains the OrderIntent, simulation result, risk decision,
    and current state in the approval pipeline.
    """
    
    model_config = {"frozen": True}
    
    proposal_id: str = Field(..., description="Unique proposal identifier (UUID)")
    correlation_id: str = Field(..., description="Request correlation ID")
    
    intent_json: str = Field(..., description="OrderIntent as JSON string")
    simulation_json: Optional[str] = Field(None, description="SimulationResult as JSON string")
    risk_decision_json: Optional[str] = Field(None, description="RiskDecision as JSON string")
    
    state: OrderState = Field(OrderState.PROPOSED, description="Current lifecycle state")
    
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Proposal creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last state update timestamp"
    )
    
    approval_token: Optional[str] = Field(None, description="Approval token if granted")
    approval_reason: Optional[str] = Field(None, description="Human reason for approval/denial")
    broker_order_id: Optional[str] = Field(None, description="Broker order ID after submission")
    
    @computed_field
    @property
    def intent_hash(self) -> str:
        """Compute SHA256 hash of intent JSON for anti-tamper verification."""
        return hashlib.sha256(self.intent_json.encode('utf-8')).hexdigest()
    
    def with_state(self, new_state: OrderState, **updates) -> "OrderProposal":
        """Create new OrderProposal with updated state and fields."""
        data = self.model_dump(exclude={"updated_at"})
        data["state"] = new_state
        data["updated_at"] = datetime.now(timezone.utc)
        data.update(updates)
        return OrderProposal(**data)


class ApprovalToken(BaseModel):
    """
    Single-use token for order commit approval.
    
    Contains anti-tamper hash verification and expiration.
    """
    
    model_config = {"frozen": True}
    
    token_id: str = Field(..., description="Unique token identifier (UUID)")
    proposal_id: str = Field(..., description="Associated proposal ID")
    intent_hash: str = Field(..., description="SHA256 hash of OrderIntent JSON")
    
    issued_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Token issue timestamp"
    )
    expires_at: datetime = Field(..., description="Token expiration timestamp")
    
    used_at: Optional[datetime] = Field(None, description="Token consumption timestamp")
    
    @field_validator("expires_at")
    @classmethod
    def expires_must_be_future(cls, v: datetime, info) -> datetime:
        """Ensure expiration is in the future."""
        issued_at = info.data.get("issued_at")
        if issued_at and v <= issued_at:
            raise ValueError("expires_at must be after issued_at")
        return v
    
    def is_valid(self, current_time: datetime) -> bool:
        """Check if token is valid: not used and not expired."""
        if self.used_at is not None:
            return False
        if current_time >= self.expires_at:
            return False
        return True
    
    def consume(self, current_time: datetime) -> "ApprovalToken":
        """Mark token as used and return updated token."""
        if not self.is_valid(current_time):
            raise ValueError("Cannot consume invalid token")
        
        data = self.model_dump()
        data["used_at"] = current_time
        return ApprovalToken(**data)


class ApprovalRequest(BaseModel):
    """Request model for POST /api/v1/approval/request."""
    
    proposal_id: str = Field(..., description="Proposal ID to request approval for")


class ApprovalResponse(BaseModel):
    """Response model for approval request."""
    
    proposal_id: str
    state: OrderState
    message: str
    correlation_id: str


class GrantApprovalRequest(BaseModel):
    """Request model for POST /api/v1/approval/grant."""
    
    proposal_id: str = Field(..., description="Proposal ID to approve")
    reason: Optional[str] = Field(None, description="Optional approval reason")


class GrantApprovalResponse(BaseModel):
    """Response model for grant approval."""
    
    proposal_id: str
    token: str = Field(..., description="Single-use approval token")
    expires_at: datetime
    message: str
    correlation_id: str


class DenyApprovalRequest(BaseModel):
    """Request model for POST /api/v1/approval/deny."""
    
    proposal_id: str = Field(..., description="Proposal ID to deny")
    reason: str = Field(..., description="Required denial reason")


class DenyApprovalResponse(BaseModel):
    """Response model for deny approval."""
    
    proposal_id: str
    state: OrderState
    message: str
    correlation_id: str


class PendingProposal(BaseModel):
    """Minimal representation of a pending proposal for UI."""
    
    proposal_id: str
    correlation_id: str
    state: OrderState
    created_at: datetime
    
    # Parsed fields for UI
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[Decimal] = None
    gross_notional: Optional[Decimal] = None
    risk_decision: Optional[str] = None  # APPROVE/REJECT/MANUAL_REVIEW
    risk_reason: Optional[str] = None


class PendingProposalsResponse(BaseModel):
    """Response model for GET /api/v1/approval/pending."""
    
    proposals: list[PendingProposal]
    count: int
