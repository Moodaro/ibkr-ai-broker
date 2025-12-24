"""
Audit event models for tracking all system decisions and state transitions.

This module provides the core data models for the audit system, which implements
a lightweight event sourcing pattern for compliance and debugging.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    """Types of audit events that can be logged."""

    # Portfolio & Market Data
    PORTFOLIO_SNAPSHOT_TAKEN = "PortfolioSnapshotTaken"
    MARKET_SNAPSHOT_TAKEN = "MarketSnapshotTaken"

    # Broker Connection
    BROKER_CONNECTED = "BrokerConnected"
    BROKER_DISCONNECTED = "BrokerDisconnected"
    BROKER_RECONNECTING = "BrokerReconnecting"

    # Order Lifecycle
    ORDER_PROPOSED = "OrderProposed"
    ORDER_SIMULATED = "OrderSimulated"
    RISK_GATE_EVALUATED = "RiskGateEvaluated"
    APPROVAL_REQUESTED = "ApprovalRequested"
    APPROVAL_GRANTED = "ApprovalGranted"
    APPROVAL_DENIED = "ApprovalDenied"
    ORDER_SUBMITTED = "OrderSubmitted"
    ORDER_CONFIRMED = "OrderConfirmed"
    ORDER_FILLED = "OrderFilled"
    ORDER_CANCELLED = "OrderCancelled"
    ORDER_REJECTED = "OrderRejected"

    # System Events
    KILL_SWITCH_ACTIVATED = "KillSwitchActivated"
    KILL_SWITCH_RELEASED = "KillSwitchReleased"
    ERROR_OCCURRED = "ErrorOccurred"

    # MCP Tool Calls
    MCP_TOOL_CALLED = "MCPToolCalled"
    MCP_TOOL_COMPLETED = "MCPToolCompleted"
    MCP_TOOL_FAILED = "MCPToolFailed"


class AuditEvent(BaseModel):
    """
    Immutable audit event representing a state transition or decision.

    All events are append-only and include full context for reconstruction.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of event")
    correlation_id: str = Field(
        ...,
        description="Correlation ID to trace related events across the system",
        min_length=1,
        max_length=100,
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Event timestamp in UTC"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data (structured JSON)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (user, session, environment)",
    )

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, v: str) -> str:
        """Ensure correlation ID is not empty and properly formatted."""
        if not v or not v.strip():
            raise ValueError("correlation_id cannot be empty")
        return v.strip()

    model_config = {"frozen": True}  # Immutable


class AuditEventCreate(BaseModel):
    """
    Model for creating new audit events (without auto-generated fields).
    """

    event_type: EventType
    correlation_id: str = Field(..., min_length=1, max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, v: str) -> str:
        """Ensure correlation ID is not empty and properly formatted."""
        if not v or not v.strip():
            raise ValueError("correlation_id cannot be empty")
        return v.strip()


class AuditQuery(BaseModel):
    """
    Query parameters for searching audit events.
    """

    event_types: list[EventType] | None = Field(
        None, description="Filter by event types"
    )
    correlation_id: str | None = Field(None, description="Filter by correlation ID")
    start_time: datetime | None = Field(None, description="Start of time range")
    end_time: datetime | None = Field(None, description="End of time range")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")


class AuditStats(BaseModel):
    """
    Statistics about audit events.
    """

    total_events: int = Field(..., description="Total number of events")
    event_type_counts: dict[str, int] = Field(
        default_factory=dict, description="Count by event type"
    )
    earliest_event: datetime | None = Field(None, description="Timestamp of earliest event")
    latest_event: datetime | None = Field(None, description="Timestamp of latest event")
    correlation_id_count: int = Field(
        ..., description="Number of unique correlation IDs"
    )
