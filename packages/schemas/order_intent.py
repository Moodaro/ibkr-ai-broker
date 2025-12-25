"""Order intent schema for IBKR AI Broker.

This module defines the structured format for order proposals.
All orders must conform to this schema before being processed.
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from packages.broker_ibkr.models import (
    Instrument,
    OrderSide,
    OrderType,
    TimeInForce,
)


class OrderConstraints(BaseModel):
    """Constraints and risk limits for an order."""

    max_slippage_bps: Optional[int] = Field(
        default=None,
        description="Maximum acceptable slippage in basis points",
        ge=0,
        le=1000,
    )
    max_notional: Optional[Decimal] = Field(
        default=None,
        description="Maximum notional value for the order",
        gt=Decimal("0"),
    )
    min_liquidity: Optional[int] = Field(
        default=None,
        description="Minimum required daily volume",
        gt=0,
    )
    execution_window_minutes: Optional[int] = Field(
        default=None,
        description="Maximum time window for order execution",
        gt=0,
        le=480,  # 8 hours max
    )

    model_config = {"frozen": True}


class OrderIntent(BaseModel):
    """
    Structured order proposal.

    This is the canonical format for all order proposals in the system.
    Must be validated before simulation and risk evaluation.
    """

    account_id: str = Field(
        ...,
        description="Account identifier",
        min_length=1,
    )
    instrument: Instrument = Field(
        ...,
        description="Instrument to trade",
    )
    side: OrderSide = Field(
        ...,
        description="Buy or sell",
    )
    quantity: Decimal = Field(
        ...,
        description="Quantity to trade",
        gt=Decimal("0"),
    )
    order_type: OrderType = Field(
        ...,
        description="Order type (MKT, LMT, STP, etc.)",
    )
    limit_price: Optional[Decimal] = Field(
        default=None,
        description="Limit price (required for LMT and STP_LMT orders)",
        gt=Decimal("0"),
    )
    stop_price: Optional[Decimal] = Field(
        default=None,
        description="Stop price (required for STP and STP_LMT orders)",
        gt=Decimal("0"),
    )
    time_in_force: TimeInForce = Field(
        default=TimeInForce.DAY,
        description="Time in force",
    )
    reason: str = Field(
        ...,
        description="Human-readable reason for the order",
        min_length=10,
        max_length=500,
    )
    strategy_tag: str = Field(
        ...,
        description="Strategy identifier (e.g., rebal_monthly_v1)",
        min_length=1,
        max_length=50,
    )
    constraints: Optional[OrderConstraints] = Field(
        default=None,
        description="Order constraints and risk limits",
    )

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        """Validate account ID format."""
        if not v or not v.strip():
            raise ValueError("account_id must be non-empty")
        return v.strip()

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate reason is meaningful."""
        if not v or not v.strip():
            raise ValueError("reason cannot be empty")
        
        # Check for meaningful content (not just "order" or "buy")
        words = v.strip().split()
        if len(words) < 3:
            raise ValueError(
                "reason must be descriptive (at least 3 words)"
            )
        
        return v.strip()

    @model_validator(mode="after")
    def validate_prices(self) -> "OrderIntent":
        """Validate limit_price and stop_price based on order_type."""
        if self.order_type in [OrderType.LMT, OrderType.STP_LMT]:
            if self.limit_price is None:
                raise ValueError(
                    f"limit_price is required for {self.order_type.value} orders"
                )
        
        if self.order_type in [OrderType.STP, OrderType.STP_LMT]:
            if self.stop_price is None:
                raise ValueError(
                    f"stop_price is required for {self.order_type.value} orders"
                )
        
        return self

    model_config = {"frozen": True}


class OrderProposal(BaseModel):
    """
    Input model for order proposal endpoint.

    Allows LLM or user to propose an order with rationale.
    """

    account_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.LMT
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    reason: str
    strategy_tag: str = "manual"
    exchange: Optional[str] = None
    currency: str = "USD"
    instrument_type: Optional[str] = None
    max_slippage_bps: Optional[int] = None
    max_notional: Optional[Decimal] = None


class OrderIntentResponse(BaseModel):
    """Response model for validated order intent."""

    intent: OrderIntent
    validation_passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    correlation_id: str
