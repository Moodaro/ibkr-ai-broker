"""
Order submission request/response schemas.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from packages.broker_ibkr.models import OrderStatus, OrderSide, OrderType, TimeInForce


class SubmitOrderRequest(BaseModel):
    """Request to submit approved order to broker."""
    
    proposal_id: str = Field(..., description="Proposal ID to submit")
    token_id: str = Field(..., description="Approval token ID")
    
    model_config = {"frozen": True}


class SubmitOrderResponse(BaseModel):
    """Response from order submission."""
    
    proposal_id: str = Field(..., description="Proposal ID")
    broker_order_id: str = Field(..., description="Broker order ID")
    status: OrderStatus = Field(..., description="Initial order status")
    symbol: str = Field(..., description="Instrument symbol")
    side: OrderSide = Field(..., description="Order side")
    quantity: Decimal = Field(..., description="Order quantity")
    order_type: OrderType = Field(..., description="Order type")
    limit_price: Optional[Decimal] = Field(None, description="Limit price if applicable")
    submitted_at: datetime = Field(..., description="Submission timestamp")
    
    model_config = {"frozen": True}


__all__ = [
    "SubmitOrderRequest",
    "SubmitOrderResponse",
]
