"""Broker adapter models for IBKR AI Broker.

This module defines Pydantic models for broker data structures.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class InstrumentType(str, Enum):
    """Instrument type enum."""

    STK = "STK"  # Stock
    ETF = "ETF"  # Exchange Traded Fund
    OPT = "OPT"  # Option
    FUT = "FUT"  # Future
    FX = "FX"  # Forex
    CRYPTO = "CRYPTO"  # Cryptocurrency
    BOND = "BOND"  # Bond
    CFD = "CFD"  # Contract for Difference


class OrderSide(str, Enum):
    """Order side enum."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type enum."""

    MKT = "MKT"  # Market
    LMT = "LMT"  # Limit
    STP = "STP"  # Stop
    STP_LMT = "STP_LMT"  # Stop Limit
    TRAIL = "TRAIL"  # Trailing Stop


class TimeInForce(str, Enum):
    """Time in force enum."""

    DAY = "DAY"  # Day order
    GTC = "GTC"  # Good till canceled
    IOC = "IOC"  # Immediate or cancel
    GTD = "GTD"  # Good till date
    FOK = "FOK"  # Fill or kill


class OrderStatus(str, Enum):
    """Order status enum."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


class Instrument(BaseModel):
    """Instrument representation."""

    type: InstrumentType
    symbol: str
    con_id: Optional[int] = None  # IBKR contract ID
    exchange: Optional[str] = None
    currency: str = "USD"
    description: Optional[str] = None

    model_config = {"frozen": True}


class Position(BaseModel):
    """Position in portfolio."""

    instrument: Instrument
    quantity: Decimal
    average_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Decimal("0")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class Cash(BaseModel):
    """Cash balance."""

    currency: str
    available: Decimal
    total: Decimal
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class Portfolio(BaseModel):
    """Complete portfolio snapshot."""

    account_id: str
    positions: list[Position]
    cash: list[Cash]
    total_value: Decimal
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class Account(BaseModel):
    """Account information."""

    account_id: str
    account_type: str  # e.g., "PAPER", "LIVE"
    status: str = "active"  # Status of account
    currency: str = "USD"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class MarketSnapshot(BaseModel):
    """Market data snapshot."""

    instrument: Instrument
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    last: Optional[Decimal] = None
    close: Optional[Decimal] = None
    volume: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class OpenOrder(BaseModel):
    """Open order representation."""

    order_id: str
    broker_order_id: Optional[str] = None
    account_id: str
    instrument: Instrument
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce
    status: OrderStatus
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Optional[Decimal] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
