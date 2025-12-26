"""
Pydantic schemas for MCP tool validation.

Defines strict schemas for all MCP tools to prevent parameter injection.
"""

from decimal import Decimal
from typing import Optional, Union

from pydantic import Field, field_validator

from packages.mcp_security import StrictBaseModel


class RequestApprovalSchema(StrictBaseModel):
    """
    Schema for request_approval tool (ONLY write tool allowed).
    
    Validates all parameters strictly and rejects any extra fields.
    """
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    side: str = Field(..., pattern="^(BUY|SELL)$", description="Order side: BUY or SELL")
    quantity: Union[Decimal, str, int, float] = Field(..., description="Order quantity (must be positive)")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Union[Decimal, str, int, float, None] = Field(None, description="Limit price for LMT orders")
    market_price: Union[Decimal, str, int, float] = Field(..., description="Current market price")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for order (min 10 chars)")
    
    @field_validator("quantity", "market_price", "limit_price", mode="before")
    @classmethod
    def convert_to_decimal(cls, v):
        """Convert numeric strings/ints/floats to Decimal."""
        if v is None:
            return v
        return Decimal(str(v))
    
    @field_validator("quantity", "market_price", "limit_price", mode="after")
    @classmethod
    def validate_positive(cls, v):
        """Ensure quantity/prices are positive."""
        if v is not None and v <= 0:
            raise ValueError("must be greater than 0")
        return v


class GetPortfolioSchema(StrictBaseModel):
    """Schema for get_portfolio tool (read-only)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")


class GetPositionsSchema(StrictBaseModel):
    """Schema for get_positions tool (read-only)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")


class GetMarketSnapshotSchema(StrictBaseModel):
    """Schema for get_market_snapshot tool (read-only)."""
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")


class SimulateOrderSchema(StrictBaseModel):
    """Schema for simulate_order tool (read-only simulation)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    side: str = Field(..., pattern="^(BUY|SELL)$", description="Order side: BUY or SELL")
    quantity: Union[Decimal, str, int, float] = Field(..., description="Order quantity")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Union[Decimal, str, int, float, None] = Field(None, description="Limit price")
    market_price: Union[Decimal, str, int, float] = Field(..., description="Current market price")
    
    @field_validator("quantity", "market_price", "limit_price", mode="before")
    @classmethod
    def convert_to_decimal(cls, v):
        """Convert numeric strings/ints/floats to Decimal."""
        if v is None:
            return v
        return Decimal(str(v))
    
    @field_validator("quantity", "market_price", "limit_price", mode="after")
    @classmethod
    def validate_positive(cls, v):
        """Ensure quantity/prices are positive."""
        if v is not None and v <= 0:
            raise ValueError("must be greater than 0")
        return v


class EvaluateRiskSchema(StrictBaseModel):
    """Schema for evaluate_risk tool (read-only risk check)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    side: str = Field(..., pattern="^(BUY|SELL)$", description="Order side: BUY or SELL")
    quantity: Union[Decimal, str, int, float] = Field(..., description="Order quantity")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Union[Decimal, str, int, float, None] = Field(None, description="Limit price")
    market_price: Union[Decimal, str, int, float] = Field(..., description="Current market price")
    
    @field_validator("quantity", "market_price", "limit_price", mode="before")
    @classmethod
    def convert_to_decimal(cls, v):
        """Convert numeric strings/ints/floats to Decimal."""
        if v is None:
            return v
        return Decimal(str(v))
    
    @field_validator("quantity", "market_price", "limit_price", mode="after")
    @classmethod
    def validate_positive(cls, v):
        """Ensure quantity/prices are positive."""
        if v is not None and v <= 0:
            raise ValueError("must be greater than 0")
        return v


class ListFlexQueriesSchema(StrictBaseModel):
    """Schema for list_flex_queries tool (read-only)."""
    enabled_only: bool = Field(True, description="Return only enabled queries")


class RunFlexQuerySchema(StrictBaseModel):
    """Schema for run_flex_query tool (read-only, generates report)."""
    query_id: str = Field(..., min_length=1, max_length=50, description="Flex Query ID")
    from_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date (YYYY-MM-DD)")


class GetCashSchema(StrictBaseModel):
    """Schema for get_cash tool (read-only)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")


class GetOpenOrdersSchema(StrictBaseModel):
    """Schema for get_open_orders tool (read-only)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")


class GetMarketBarsSchema(StrictBaseModel):
    """Schema for get_market_bars tool (read-only)."""
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    bar_size: str = Field("1 day", pattern=r"^\d+ (sec|min|hour|day|week|month)s?$", description="Bar size")
    duration: str = Field("1 Y", pattern=r"^\d+ (S|D|W|M|Y)$", description="Duration")


class InstrumentSearchSchema(StrictBaseModel):
    """Schema for instrument_search tool (read-only)."""
    query: str = Field(..., min_length=1, max_length=100, description="Search query")
    limit: int = Field(10, ge=1, le=100, description="Max results (1-100)")


class InstrumentResolveSchema(StrictBaseModel):
    """Schema for instrument_resolve tool (read-only)."""
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")


# Schema registry: maps tool names to their validation schemas
TOOL_SCHEMAS = {
    "request_approval": RequestApprovalSchema,
    "get_portfolio": GetPortfolioSchema,
    "get_positions": GetPositionsSchema,
    "get_cash": GetCashSchema,
    "get_open_orders": GetOpenOrdersSchema,
    "get_market_snapshot": GetMarketSnapshotSchema,
    "get_market_bars": GetMarketBarsSchema,
    "simulate_order": SimulateOrderSchema,
    "evaluate_risk": EvaluateRiskSchema,
    "instrument_search": InstrumentSearchSchema,
    "instrument_resolve": InstrumentResolveSchema,
    "list_flex_queries": ListFlexQueriesSchema,
    "run_flex_query": RunFlexQuerySchema,
}


def get_schema_for_tool(tool_name: str) -> type[StrictBaseModel] | None:
    """
    Get the validation schema for a tool.
    
    Args:
        tool_name: Name of the MCP tool
        
    Returns:
        Pydantic schema class or None if no schema defined
    """
    return TOOL_SCHEMAS.get(tool_name)
