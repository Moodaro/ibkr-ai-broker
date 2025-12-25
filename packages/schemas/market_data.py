"""
Market data schemas for snapshot and historical bar data.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


TimeframeType = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"]


class MarketSnapshot(BaseModel):
    """
    Real-time market snapshot for an instrument.
    
    Contains current bid/ask/last prices, mid-price calculation,
    and volume. Used for current market conditions and quick price checks.
    """
    
    instrument: str = Field(..., description="Instrument identifier (symbol)")
    timestamp: datetime = Field(..., description="Snapshot timestamp (UTC)")
    bid: Optional[Decimal] = Field(None, description="Current bid price")
    ask: Optional[Decimal] = Field(None, description="Current ask price")
    last: Optional[Decimal] = Field(None, description="Last traded price")
    volume: Optional[int] = Field(None, description="Current session volume")
    mid: Optional[Decimal] = Field(None, description="Mid-price (bid+ask)/2")
    
    # Additional optional fields
    bid_size: Optional[int] = Field(None, description="Bid quantity")
    ask_size: Optional[int] = Field(None, description="Ask quantity")
    high: Optional[Decimal] = Field(None, description="Session high")
    low: Optional[Decimal] = Field(None, description="Session low")
    open_price: Optional[Decimal] = Field(None, description="Session open")
    prev_close: Optional[Decimal] = Field(None, description="Previous close")
    
    @model_validator(mode='after')
    def calculate_mid_price(self):
        """Calculate mid-price from bid/ask if not provided."""
        if self.mid is None and self.bid is not None and self.ask is not None:
            self.mid = (self.bid + self.ask) / Decimal('2')
        return self
    
    @field_validator('bid', 'ask', 'last', 'high', 'low', 'open_price', 'prev_close', mode='before')
    @classmethod
    def validate_positive(cls, v):
        """Validate that prices are positive."""
        if v is not None and v <= 0:
            raise ValueError("Price must be positive")
        return v
    
    @field_validator('volume', 'bid_size', 'ask_size', mode='before')
    @classmethod
    def validate_non_negative(cls, v):
        """Validate that sizes/volumes are non-negative."""
        if v is not None and v < 0:
            raise ValueError("Size/volume must be non-negative")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "instrument": "AAPL",
                "timestamp": "2025-12-25T14:30:00Z",
                "bid": "175.50",
                "ask": "175.55",
                "last": "175.52",
                "volume": 1500000,
                "mid": "175.525"
            }
        }


class MarketBar(BaseModel):
    """
    OHLCV bar for historical market data.
    
    Represents open/high/low/close/volume for a specific timeframe.
    Used for technical analysis, backtesting, and volatility calculations.
    """
    
    instrument: str = Field(..., description="Instrument identifier (symbol)")
    timestamp: datetime = Field(..., description="Bar timestamp (UTC, start of period)")
    timeframe: TimeframeType = Field(..., description="Bar timeframe")
    open: Decimal = Field(..., description="Open price")
    high: Decimal = Field(..., description="High price")
    low: Decimal = Field(..., description="Low price")
    close: Decimal = Field(..., description="Close price")
    volume: int = Field(..., description="Volume")
    
    # Optional metadata
    vwap: Optional[Decimal] = Field(None, description="Volume-weighted average price")
    trade_count: Optional[int] = Field(None, description="Number of trades")
    
    @field_validator('high')
    @classmethod
    def validate_high(cls, v, info):
        """Validate high >= open, low, close."""
        data = info.data
        open_price = data.get('open')
        low = data.get('low')
        close = data.get('close')
        
        if open_price and v < open_price:
            raise ValueError("High must be >= open")
        if low and v < low:
            raise ValueError("High must be >= low")
        if close and v < close:
            raise ValueError("High must be >= close")
        
        return v
    
    @field_validator('low')
    @classmethod
    def validate_low(cls, v, info):
        """Validate low <= open, close."""
        data = info.data
        open_price = data.get('open')
        close = data.get('close')
        
        if open_price and v > open_price:
            raise ValueError("Low must be <= open")
        if close and v > close:
            raise ValueError("Low must be <= close")
        
        return v
    
    @field_validator('open', 'high', 'low', 'close', 'vwap', mode='before')
    @classmethod
    def validate_positive_price(cls, v):
        """Validate that prices are positive."""
        if v is not None and v <= 0:
            raise ValueError("Price must be positive")
        return v
    
    @field_validator('volume', 'trade_count', mode='before')
    @classmethod
    def validate_non_negative_count(cls, v):
        """Validate that volumes/counts are non-negative."""
        if v is not None and v < 0:
            raise ValueError("Volume/count must be non-negative")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "instrument": "AAPL",
                "timestamp": "2025-12-25T14:00:00Z",
                "timeframe": "1h",
                "open": "175.00",
                "high": "176.50",
                "low": "174.80",
                "close": "176.20",
                "volume": 250000
            }
        }


class MarketDataRequest(BaseModel):
    """Request for market data (snapshot or bars)."""
    
    instrument: str = Field(..., description="Instrument identifier")
    fields: Optional[list[str]] = Field(
        default=None,
        description="Specific fields to retrieve (snapshot only)"
    )


class BarDataRequest(BaseModel):
    """Request for historical bar data."""
    
    instrument: str = Field(..., description="Instrument identifier")
    timeframe: TimeframeType = Field(..., description="Bar timeframe")
    start: Optional[datetime] = Field(None, description="Start time (UTC)")
    end: Optional[datetime] = Field(None, description="End time (UTC)")
    limit: Optional[int] = Field(
        default=100,
        ge=1,
        le=5000,
        description="Maximum number of bars to return"
    )
    rth_only: bool = Field(
        default=True,
        description="Regular trading hours only"
    )
    
    @field_validator('end')
    @classmethod
    def validate_date_range(cls, v, info):
        """Validate that end >= start."""
        start = info.data.get('start')
        if start and v and v < start:
            raise ValueError("End time must be >= start time")
        return v
