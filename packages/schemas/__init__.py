"""Schemas package for IBKR AI Broker.

This package contains Pydantic models for all structured data.
"""

from .approval import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalToken,
    DenyApprovalRequest,
    DenyApprovalResponse,
    GrantApprovalRequest,
    GrantApprovalResponse,
    OrderProposal as OrderProposalLifecycle,
    OrderState,
    PendingProposal,
    PendingProposalsResponse,
)
from .order_intent import (
    OrderConstraints,
    OrderIntent,
    OrderIntentResponse,
    OrderProposal,
    RiskEvaluationRequest,
    RiskEvaluationResponse,
    SimulationRequest,
    SimulationResponse,
)
from .submission import (
    SubmitOrderRequest,
    SubmitOrderResponse,
)

__all__ = [
    # Approval system
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalToken",
    "DenyApprovalRequest",
    "DenyApprovalResponse",
    "GrantApprovalRequest",
    "GrantApprovalResponse",
    "OrderProposalLifecycle",
    "OrderState",
    "PendingProposal",
    "PendingProposalsResponse",
    # Order intent
    "OrderConstraints",
    "OrderIntent",
    "OrderIntentResponse",
    "OrderProposal",
    "RiskEvaluationRequest",
    "RiskEvaluationResponse",
    "SimulationRequest",
    "SimulationResponse",
    # Order submission
    "SubmitOrderRequest",
    "SubmitOrderResponse",
]
