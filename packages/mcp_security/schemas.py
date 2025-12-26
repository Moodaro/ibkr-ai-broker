"""
Pydantic schemas for MCP tool validation.

Defines strict schemas for all MCP tools to prevent parameter injection.
"""

from decimal import Decimal
from typing import Optional

from pydantic import Field

from packages.mcp_security import StrictBaseModel


class RequestApprovalSchema(StrictBaseModel):
    """
    Schema for request_approval tool (ONLY write tool allowed).
    
    Validates all parameters strictly and rejects any extra fields.
    """
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    side: str = Field(..., pattern="^(BUY|SELL)$", description="Order side: BUY or SELL")
    quantity: Decimal = Field(..., gt=0, description="Order quantity (must be positive)")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Optional[Decimal] = Field(None, gt=0, description="Limit price for LMT orders")
    market_price: Decimal = Field(..., gt=0, description="Current market price")
    reason: str = Field(..., min_length=10, max_length=500, description="Reason for order (min 10 chars)")


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
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Optional[Decimal] = Field(None, gt=0, description="Limit price")
    market_price: Decimal = Field(..., gt=0, description="Current market price")


class EvaluateRiskSchema(StrictBaseModel):
    """Schema for evaluate_risk tool (read-only risk check)."""
    account_id: str = Field(..., min_length=1, max_length=100, description="Account identifier")
    symbol: str = Field(..., min_length=1, max_length=50, description="Instrument symbol")
    side: str = Field(..., pattern="^(BUY|SELL)$", description="Order side: BUY or SELL")
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    order_type: str = Field("MKT", pattern="^(MKT|LMT|STP|STP_LMT)$", description="Order type")
    limit_price: Optional[Decimal] = Field(None, gt=0, description="Limit price")
    market_price: Decimal = Field(..., gt=0, description="Current market price")


class ListFlexQueriesSchema(StrictBaseModel):
    """Schema for list_flex_queries tool (read-only)."""
    enabled_only: bool = Field(True, description="Return only enabled queries")


class RunFlexQuerySchema(StrictBaseModel):
    """Schema for run_flex_query tool (read-only, generates report)."""
    query_id: str = Field(..., min_length=1, max_length=50, description="Flex Query ID")
    from_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="End date (YYYY-MM-DD)")


# Schema registry: maps tool names to their validation schemas
TOOL_SCHEMAS = {
    "request_approval": RequestApprovalSchema,
    "get_portfolio": GetPortfolioSchema,
    "get_positions": GetPositionsSchema,
    "get_market_snapshot": GetMarketSnapshotSchema,
    "simulate_order": SimulateOrderSchema,
    "evaluate_risk": EvaluateRiskSchema,
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
