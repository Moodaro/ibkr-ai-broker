"""Risk Engine models for IBKR AI Broker.

This module defines the risk evaluation framework including decisions,
rules, and evaluation results.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Decision(str, Enum):
    """Risk gate decision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RiskDecision(BaseModel):
    """Risk evaluation result with decision and reasoning."""

    decision: Decision = Field(
        ...,
        description="Final risk gate decision",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation for the decision",
        min_length=1,
    )
    violated_rules: list[str] = Field(
        default_factory=list,
        description="List of rule IDs that were violated (e.g., R1, R2)",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings for manual review",
    )
    metrics: dict[str, Decimal | int | float | str] = Field(
        default_factory=dict,
        description="Calculated risk metrics (e.g., position_pct, concentration)",
    )

    model_config = {"frozen": True}

    def is_approved(self) -> bool:
        """Check if order is approved."""
        return self.decision == Decision.APPROVE

    def is_rejected(self) -> bool:
        """Check if order is rejected."""
        return self.decision == Decision.REJECT


class RiskLimits(BaseModel):
    """Risk limits configuration from policy."""

    # R1: Maximum notional value per order
    max_notional: Decimal = Field(
        default=Decimal("50000.00"),
        description="Maximum notional value for a single order",
        gt=Decimal("0"),
    )

    # R2: Maximum position size as percentage of portfolio
    max_position_pct: Decimal = Field(
        default=Decimal("10.0"),
        description="Maximum position size as % of portfolio value",
        gt=Decimal("0"),
        le=Decimal("100.0"),
    )

    # R3: Maximum sector exposure
    max_sector_exposure_pct: Decimal = Field(
        default=Decimal("30.0"),
        description="Maximum exposure to single sector as % of portfolio",
        gt=Decimal("0"),
        le=Decimal("100.0"),
    )

    # R4: Maximum slippage tolerance
    max_slippage_bps: int = Field(
        default=50,
        description="Maximum acceptable slippage in basis points",
        ge=0,
        le=1000,
    )

    # R6: Minimum liquidity (daily volume)
    min_daily_volume: int = Field(
        default=100000,
        description="Minimum required average daily volume",
        ge=0,
    )

    # R7: Maximum trades per day
    max_daily_trades: int = Field(
        default=50,
        description="Maximum number of trades allowed per day",
        ge=1,
    )

    # R8: Maximum daily loss
    max_daily_loss: Decimal = Field(
        default=Decimal("5000.00"),
        description="Maximum allowed loss per day in USD",
        gt=Decimal("0"),
    )

    model_config = {"frozen": True}


class TradingHours(BaseModel):
    """Trading hours configuration for R5."""

    allow_pre_market: bool = Field(
        default=False,
        description="Allow trading during pre-market hours",
    )
    allow_after_hours: bool = Field(
        default=False,
        description="Allow trading during after-hours",
    )
    market_open_utc: str = Field(
        default="14:30",
        description="Market open time in UTC (HH:MM format)",
    )
    market_close_utc: str = Field(
        default="21:00",
        description="Market close time in UTC (HH:MM format)",
    )

    model_config = {"frozen": True}
