"""Simulation models for trade simulator."""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SimulationStatus(str, Enum):
    """Status of simulation execution."""

    SUCCESS = "SUCCESS"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
    CONSTRAINT_VIOLATED = "CONSTRAINT_VIOLATED"


class SimulationConfig(BaseModel):
    """Configuration for trade simulation."""

    # Fee structure
    fee_per_share: Decimal = Field(
        default=Decimal("0.005"),
        description="Commission per share (USD)",
        ge=Decimal("0"),
    )
    min_fee: Decimal = Field(
        default=Decimal("1.0"),
        description="Minimum commission per order (USD)",
        ge=Decimal("0"),
    )
    max_fee: Decimal = Field(
        default=Decimal("0.01"),
        description="Maximum commission as % of notional",
        ge=Decimal("0"),
        le=Decimal("1.0"),
    )

    # Slippage modeling
    base_slippage_bps: Decimal = Field(
        default=Decimal("5"),
        description="Base slippage in basis points",
        ge=Decimal("0"),
    )
    market_impact_factor: Decimal = Field(
        default=Decimal("0.1"),
        description="Additional slippage per $10k notional",
        ge=Decimal("0"),
    )

    model_config = {"frozen": True}


class SimulationResult(BaseModel):
    """Result of order simulation."""

    status: SimulationStatus
    
    # Execution details
    execution_price: Optional[Decimal] = Field(
        default=None,
        description="Estimated execution price including slippage",
    )
    gross_notional: Optional[Decimal] = Field(
        default=None,
        description="Notional value before fees (price × quantity)",
    )
    estimated_fee: Optional[Decimal] = Field(
        default=None,
        description="Estimated commission",
    )
    estimated_slippage: Optional[Decimal] = Field(
        default=None,
        description="Estimated slippage in USD",
    )
    net_notional: Optional[Decimal] = Field(
        default=None,
        description="Net value including fees and slippage",
    )
    
    # Portfolio impact
    cash_before: Optional[Decimal] = Field(
        default=None,
        description="Cash balance before trade",
    )
    cash_after: Optional[Decimal] = Field(
        default=None,
        description="Cash balance after trade",
    )
    exposure_before: Optional[Decimal] = Field(
        default=None,
        description="Total exposure before trade",
    )
    exposure_after: Optional[Decimal] = Field(
        default=None,
        description="Total exposure after trade",
    )
    
    # Warnings and errors
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-critical warnings",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if simulation failed",
    )

    model_config = {"frozen": True}
