"""
Instrument resolution schemas for contract disambiguation.

IBKR requires precise contract specifications (conId, exchange, currency)
to avoid rejections. These schemas support instrument search and resolution.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


InstrumentTypeEnum = Literal["STK", "ETF", "OPT", "FUT", "FX", "CRYPTO", "BOND", "IND"]
ExchangeEnum = Literal["SMART", "NASDAQ", "NYSE", "ARCA", "CBOE", "CME", "IDEALPRO", "PAXOS"]


class InstrumentContract(BaseModel):
    """
    Fully resolved instrument contract with IBKR specifications.
    
    Contains all information needed to uniquely identify an instrument
    and submit orders without ambiguity.
    """
    
    con_id: int = Field(..., description="IBKR contract ID (unique identifier)")
    symbol: str = Field(..., description="Instrument symbol")
    type: InstrumentTypeEnum = Field(..., description="Instrument type")
    exchange: str = Field(..., description="Primary exchange")
    currency: str = Field(..., description="Trading currency")
    
    # Optional details
    local_symbol: Optional[str] = Field(None, description="Local symbol (exchange-specific)")
    name: Optional[str] = Field(None, description="Full instrument name")
    sector: Optional[str] = Field(None, description="Industry sector")
    multiplier: Optional[Decimal] = Field(None, description="Contract multiplier (for derivatives)")
    expiry: Optional[datetime] = Field(None, description="Expiration date (for derivatives)")
    strike: Optional[Decimal] = Field(None, description="Strike price (for options)")
    right: Optional[Literal["C", "P"]] = Field(None, description="Call/Put (for options)")
    
    # Trading information
    min_tick: Optional[Decimal] = Field(None, description="Minimum price increment")
    lot_size: Optional[int] = Field(None, description="Standard lot size")
    tradeable: bool = Field(True, description="Whether instrument is currently tradeable")
    
    @field_validator('con_id')
    @classmethod
    def validate_con_id(cls, v):
        """Validate conId is positive."""
        if v <= 0:
            raise ValueError("conId must be positive")
        return v
    
    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        """Validate currency code."""
        if len(v) != 3:
            raise ValueError("Currency must be 3-letter ISO code")
        return v.upper()
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        """Validate and normalize symbol."""
        if not v or len(v) > 20:
            raise ValueError("Symbol must be 1-20 characters")
        return v.upper()

    class Config:
        json_schema_extra = {
            "example": {
                "con_id": 265598,
                "symbol": "AAPL",
                "type": "STK",
                "exchange": "NASDAQ",
                "currency": "USD",
                "name": "Apple Inc.",
                "sector": "Technology",
                "tradeable": True
            }
        }


class SearchCandidate(BaseModel):
    """
    Single search result candidate from instrument search.
    
    Contains basic contract information and a match score for ranking.
    """
    
    con_id: int = Field(..., description="IBKR contract ID")
    symbol: str = Field(..., description="Instrument symbol")
    type: InstrumentTypeEnum = Field(..., description="Instrument type")
    exchange: str = Field(..., description="Primary exchange")
    currency: str = Field(..., description="Trading currency")
    name: Optional[str] = Field(None, description="Full instrument name")
    match_score: float = Field(..., ge=0.0, le=1.0, description="Match confidence (0-1)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "con_id": 265598,
                "symbol": "AAPL",
                "type": "STK",
                "exchange": "NASDAQ",
                "currency": "USD",
                "name": "Apple Inc.",
                "match_score": 0.95
            }
        }


class InstrumentSearchRequest(BaseModel):
    """Request to search for instruments."""
    
    query: str = Field(..., min_length=1, max_length=100, description="Search query (symbol or name)")
    type: Optional[InstrumentTypeEnum] = Field(None, description="Filter by instrument type")
    exchange: Optional[str] = Field(None, description="Filter by exchange")
    currency: Optional[str] = Field(None, description="Filter by currency")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results to return")
    
    @field_validator('query')
    @classmethod
    def normalize_query(cls, v):
        """Normalize search query."""
        return v.strip().upper()
    
    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        """Validate currency filter."""
        if v and len(v) != 3:
            raise ValueError("Currency must be 3-letter ISO code")
        return v.upper() if v else None


class InstrumentSearchResponse(BaseModel):
    """Response from instrument search."""
    
    query: str = Field(..., description="Original search query")
    candidates: List[SearchCandidate] = Field(..., description="Matching candidates")
    total_found: int = Field(..., description="Total matches found (may exceed returned)")
    filters_applied: dict = Field(default_factory=dict, description="Filters used in search")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "AAPL",
                "candidates": [
                    {
                        "con_id": 265598,
                        "symbol": "AAPL",
                        "type": "STK",
                        "exchange": "NASDAQ",
                        "currency": "USD",
                        "name": "Apple Inc.",
                        "match_score": 1.0
                    }
                ],
                "total_found": 1,
                "filters_applied": {"type": "STK", "currency": "USD"}
            }
        }


class InstrumentResolveRequest(BaseModel):
    """Request to resolve instrument to exact contract."""
    
    symbol: str = Field(..., min_length=1, max_length=20, description="Instrument symbol")
    type: Optional[InstrumentTypeEnum] = Field(None, description="Instrument type (recommended)")
    exchange: Optional[str] = Field(None, description="Exchange (recommended)")
    currency: Optional[str] = Field(None, description="Currency (recommended)")
    con_id: Optional[int] = Field(None, description="Explicit conId (bypasses resolution)")
    
    @field_validator('symbol')
    @classmethod
    def normalize_symbol(cls, v):
        """Normalize symbol."""
        return v.strip().upper()
    
    @field_validator('con_id')
    @classmethod
    def validate_con_id(cls, v):
        """Validate conId if provided."""
        if v is not None and v <= 0:
            raise ValueError("conId must be positive")
        return v


class InstrumentResolveResponse(BaseModel):
    """Response from instrument resolution."""
    
    contract: InstrumentContract = Field(..., description="Resolved contract")
    ambiguous: bool = Field(..., description="Whether multiple matches were found")
    alternatives: List[SearchCandidate] = Field(
        default_factory=list,
        description="Alternative matches if ambiguous"
    )
    resolution_method: str = Field(..., description="How contract was resolved")
    
    class Config:
        json_schema_extra = {
            "example": {
                "contract": {
                    "con_id": 265598,
                    "symbol": "AAPL",
                    "type": "STK",
                    "exchange": "NASDAQ",
                    "currency": "USD",
                    "name": "Apple Inc.",
                    "tradeable": True
                },
                "ambiguous": False,
                "alternatives": [],
                "resolution_method": "exact_match"
            }
        }


class InstrumentResolutionError(Exception):
    """Raised when instrument cannot be resolved."""
    
    def __init__(self, message: str, candidates: Optional[List[SearchCandidate]] = None):
        super().__init__(message)
        self.candidates = candidates or []
