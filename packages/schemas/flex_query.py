"""
FlexQuery schemas for IBKR reporting and reconciliation.

Defines models for Flex Queries, trade confirmations, realized P&L,
and report storage.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FlexQueryType(str, Enum):
    """Types of Flex Queries supported."""
    
    TRADES = "TRADES"  # Trade confirmations
    EXECUTIONS = "EXECUTIONS"  # Execution details
    REALIZED_PNL = "REALIZED_PNL"  # Realized profit/loss
    POSITIONS = "POSITIONS"  # Position snapshot
    CASH_REPORT = "CASH_REPORT"  # Cash transactions
    ACTIVITY_STATEMENT = "ACTIVITY_STATEMENT"  # Full activity statement


class FlexQueryStatus(str, Enum):
    """Status of a Flex Query execution."""
    
    PENDING = "PENDING"  # Request submitted, waiting for IBKR
    PROCESSING = "PROCESSING"  # IBKR is generating report
    READY = "READY"  # Report ready for download
    COMPLETED = "COMPLETED"  # Downloaded and parsed successfully
    FAILED = "FAILED"  # Generation or parsing failed
    EXPIRED = "EXPIRED"  # Report expired (IBKR retention ~7 days)


class FlexQueryConfig(BaseModel):
    """Configuration for a Flex Query."""
    
    query_id: str = Field(..., description="IBKR Flex Query ID")
    name: str = Field(..., description="Human-readable query name")
    query_type: FlexQueryType = Field(..., description="Type of report")
    description: Optional[str] = Field(None, description="Optional description")
    enabled: bool = Field(True, description="Whether query is enabled")
    auto_schedule: bool = Field(False, description="Run automatically on schedule")
    schedule_cron: Optional[str] = Field(None, description="Cron expression for scheduling")
    retention_days: int = Field(90, description="Days to retain downloaded reports")
    
    @field_validator("schedule_cron")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        """Validate cron expression format."""
        if v is None:
            return None
        # Basic validation: 5 or 6 fields
        parts = v.split()
        if len(parts) not in (5, 6):
            raise ValueError("Cron expression must have 5 or 6 fields")
        return v


class TradeConfirmation(BaseModel):
    """Individual trade confirmation from Flex Query."""
    
    trade_id: str = Field(..., description="Unique trade identifier")
    execution_id: str = Field(..., description="Execution ID")
    account_id: str = Field(..., description="Account identifier")
    
    symbol: str = Field(..., description="Instrument symbol")
    description: str = Field(..., description="Full instrument description")
    con_id: Optional[int] = Field(None, description="IBKR contract ID")
    
    trade_date: date = Field(..., description="Trade date")
    settle_date: Optional[date] = Field(None, description="Settlement date")
    
    quantity: Decimal = Field(..., description="Quantity traded (signed: + = buy, - = sell)")
    trade_price: Decimal = Field(..., description="Execution price")
    proceeds: Decimal = Field(..., description="Total proceeds (signed)")
    commission: Decimal = Field(..., description="Commission paid")
    net_cash: Decimal = Field(..., description="Net cash impact (proceeds - commission)")
    
    buy_sell: str = Field(..., description="BUY or SELL")
    order_time: Optional[datetime] = Field(None, description="Order submission time")
    
    currency: str = Field("USD", description="Currency")
    exchange: Optional[str] = Field(None, description="Exchange")
    
    @field_validator("buy_sell")
    @classmethod
    def validate_buy_sell(cls, v: str) -> str:
        """Ensure buy_sell is uppercase."""
        return v.upper()


class RealizedPnL(BaseModel):
    """Realized profit/loss from Flex Query."""
    
    account_id: str = Field(..., description="Account identifier")
    symbol: str = Field(..., description="Instrument symbol")
    
    realized_pnl: Decimal = Field(..., description="Realized P&L")
    unrealized_pnl: Decimal = Field(..., description="Unrealized P&L (snapshot)")
    
    mtm_pnl: Decimal = Field(..., description="Mark-to-market P&L")
    fifo_pnl: Decimal = Field(..., description="FIFO P&L")
    
    currency: str = Field("USD", description="Currency")
    report_date: date = Field(..., description="Report date")


class CashTransaction(BaseModel):
    """Cash transaction from Flex Query."""
    
    transaction_id: str = Field(..., description="Transaction ID")
    account_id: str = Field(..., description="Account identifier")
    
    transaction_date: date = Field(..., description="Transaction date")
    description: str = Field(..., description="Transaction description")
    amount: Decimal = Field(..., description="Amount (signed)")
    balance: Decimal = Field(..., description="Balance after transaction")
    
    currency: str = Field("USD", description="Currency")
    transaction_type: str = Field(..., description="Transaction type (e.g., DEPOSIT, WITHDRAWAL, DIVIDEND)")


class FlexQueryResult(BaseModel):
    """Result of a Flex Query execution."""
    
    query_id: str = Field(..., description="IBKR Flex Query ID")
    execution_id: str = Field(..., description="Unique execution ID")
    
    status: FlexQueryStatus = Field(..., description="Query execution status")
    query_type: FlexQueryType = Field(..., description="Type of report")
    
    request_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When query was requested"
    )
    completion_time: Optional[datetime] = Field(None, description="When query completed")
    
    from_date: Optional[date] = Field(None, description="Report start date")
    to_date: Optional[date] = Field(None, description="Report end date")
    
    # Raw data
    raw_xml: Optional[str] = Field(None, description="Raw XML response")
    raw_csv: Optional[str] = Field(None, description="Raw CSV response")
    data_hash: Optional[str] = Field(None, description="SHA256 hash of raw data")
    
    # Parsed data (populated based on query_type)
    trades: list[TradeConfirmation] = Field(default_factory=list, description="Trade confirmations")
    pnl_records: list[RealizedPnL] = Field(default_factory=list, description="P&L records")
    cash_transactions: list[CashTransaction] = Field(default_factory=list, description="Cash transactions")
    
    error_message: Optional[str] = Field(None, description="Error message if failed")


class FlexQueryRequest(BaseModel):
    """Request to execute a Flex Query."""
    
    query_id: str = Field(..., description="IBKR Flex Query ID")
    from_date: Optional[date] = Field(None, description="Report start date (optional)")
    to_date: Optional[date] = Field(None, description="Report end date (optional)")
    
    @field_validator("from_date", "to_date")
    @classmethod
    def validate_dates(cls, v: Optional[date]) -> Optional[date]:
        """Ensure dates are not in the future."""
        if v is not None and v > date.today():
            raise ValueError("Date cannot be in the future")
        return v


class FlexQueryListResponse(BaseModel):
    """Response with list of available Flex Queries."""
    
    queries: list[FlexQueryConfig] = Field(..., description="Available queries")
    total: int = Field(..., description="Total number of queries")


class FlexQueryExecutionResponse(BaseModel):
    """Response after executing a Flex Query."""
    
    execution_id: str = Field(..., description="Unique execution ID")
    status: FlexQueryStatus = Field(..., description="Current status")
    message: str = Field(..., description="Status message")
    estimated_completion_seconds: Optional[int] = Field(None, description="Estimated time to completion")
