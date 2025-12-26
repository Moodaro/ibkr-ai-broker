"""
Tests for FlexQuery schemas.
"""

import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from packages.schemas.flex_query import (
    FlexQueryType,
    FlexQueryStatus,
    FlexQueryConfig,
    TradeConfirmation,
    RealizedPnL,
    CashTransaction,
    FlexQueryResult,
    FlexQueryRequest,
    FlexQueryListResponse,
    FlexQueryExecutionResponse,
)


def test_flex_query_type_enum():
    """Test FlexQueryType enum values."""
    assert FlexQueryType.TRADES == "TRADES"
    assert FlexQueryType.EXECUTIONS == "EXECUTIONS"
    assert FlexQueryType.REALIZED_PNL == "REALIZED_PNL"
    assert FlexQueryType.POSITIONS == "POSITIONS"
    assert FlexQueryType.CASH_REPORT == "CASH_REPORT"
    assert FlexQueryType.ACTIVITY_STATEMENT == "ACTIVITY_STATEMENT"
    
    # All 6 types
    assert len(list(FlexQueryType)) == 6


def test_flex_query_status_enum():
    """Test FlexQueryStatus enum values."""
    assert FlexQueryStatus.PENDING == "PENDING"
    assert FlexQueryStatus.PROCESSING == "PROCESSING"
    assert FlexQueryStatus.READY == "READY"
    assert FlexQueryStatus.COMPLETED == "COMPLETED"
    assert FlexQueryStatus.FAILED == "FAILED"
    assert FlexQueryStatus.EXPIRED == "EXPIRED"
    
    # All 6 states
    assert len(list(FlexQueryStatus)) == 6


def test_flex_query_config_valid():
    """Test FlexQueryConfig with valid data."""
    config = FlexQueryConfig(
        query_id="123456",
        name="Daily Trades",
        query_type=FlexQueryType.TRADES,
        description="Daily trade confirmations",
        enabled=True,
        auto_schedule=True,
        schedule_cron="0 9 * * *",
        retention_days=90,
    )
    
    assert config.query_id == "123456"
    assert config.name == "Daily Trades"
    assert config.query_type == FlexQueryType.TRADES
    assert config.enabled is True
    assert config.auto_schedule is True
    assert config.schedule_cron == "0 9 * * *"
    assert config.retention_days == 90


def test_flex_query_config_cron_validation_5_fields():
    """Test cron validation with 5 fields."""
    config = FlexQueryConfig(
        query_id="123456",
        name="Test",
        query_type=FlexQueryType.TRADES,
        schedule_cron="0 9 * * *",  # 5 fields: valid
    )
    assert config.schedule_cron == "0 9 * * *"


def test_flex_query_config_cron_validation_6_fields():
    """Test cron validation with 6 fields."""
    config = FlexQueryConfig(
        query_id="123456",
        name="Test",
        query_type=FlexQueryType.TRADES,
        schedule_cron="0 0 9 * * *",  # 6 fields: valid
    )
    assert config.schedule_cron == "0 0 9 * * *"


def test_flex_query_config_cron_validation_invalid():
    """Test cron validation with invalid expression."""
    with pytest.raises(ValueError, match="Cron expression must have 5 or 6 fields"):
        FlexQueryConfig(
            query_id="123456",
            name="Test",
            query_type=FlexQueryType.TRADES,
            schedule_cron="invalid cron",  # Only 2 fields
        )


def test_flex_query_config_defaults():
    """Test FlexQueryConfig default values."""
    config = FlexQueryConfig(
        query_id="123456",
        name="Test",
        query_type=FlexQueryType.TRADES,
    )
    
    assert config.enabled is True
    assert config.auto_schedule is False
    assert config.schedule_cron is None
    assert config.retention_days == 90
    assert config.description is None


def test_trade_confirmation_valid():
    """Test TradeConfirmation with valid data."""
    trade = TradeConfirmation(
        trade_id="T12345",
        execution_id="E67890",
        account_id="DU123456",
        symbol="AAPL",
        description="Apple Inc.",
        con_id=265598,
        trade_date=date(2025, 12, 26),
        settle_date=date(2025, 12, 28),
        quantity=Decimal("100"),
        trade_price=Decimal("195.50"),
        proceeds=Decimal("19550.00"),
        commission=Decimal("1.00"),
        net_cash=Decimal("19549.00"),
        buy_sell="BUY",
        order_time=datetime(2025, 12, 26, 9, 30, 0, tzinfo=timezone.utc),
        currency="USD",
        exchange="NASDAQ",
    )
    
    assert trade.trade_id == "T12345"
    assert trade.symbol == "AAPL"
    assert trade.quantity == Decimal("100")
    assert trade.buy_sell == "BUY"
    assert trade.commission == Decimal("1.00")


def test_trade_confirmation_buy_sell_uppercase():
    """Test TradeConfirmation buy_sell uppercase validation."""
    trade = TradeConfirmation(
        trade_id="T12345",
        execution_id="E67890",
        account_id="DU123456",
        symbol="AAPL",
        description="Apple Inc.",
        trade_date=date(2025, 12, 26),
        quantity=Decimal("100"),
        trade_price=Decimal("195.50"),
        proceeds=Decimal("19550.00"),
        commission=Decimal("1.00"),
        net_cash=Decimal("19549.00"),
        buy_sell="buy",  # lowercase
    )
    
    # Should be converted to uppercase
    assert trade.buy_sell == "BUY"


def test_trade_confirmation_negative_quantity():
    """Test TradeConfirmation with negative quantity (sell)."""
    trade = TradeConfirmation(
        trade_id="T12345",
        execution_id="E67890",
        account_id="DU123456",
        symbol="AAPL",
        description="Apple Inc.",
        trade_date=date(2025, 12, 26),
        quantity=Decimal("-100"),  # Negative for sell
        trade_price=Decimal("195.50"),
        proceeds=Decimal("-19550.00"),
        commission=Decimal("1.00"),
        net_cash=Decimal("-19551.00"),
        buy_sell="SELL",
    )
    
    assert trade.quantity == Decimal("-100")
    assert trade.buy_sell == "SELL"


def test_realized_pnl_valid():
    """Test RealizedPnL with valid data."""
    pnl = RealizedPnL(
        account_id="DU123456",
        symbol="AAPL",
        realized_pnl=Decimal("500.00"),
        unrealized_pnl=Decimal("150.00"),
        mtm_pnl=Decimal("650.00"),
        fifo_pnl=Decimal("500.00"),
        currency="USD",
        report_date=date(2025, 12, 26),
    )
    
    assert pnl.account_id == "DU123456"
    assert pnl.symbol == "AAPL"
    assert pnl.realized_pnl == Decimal("500.00")
    assert pnl.report_date == date(2025, 12, 26)


def test_cash_transaction_valid():
    """Test CashTransaction with valid data."""
    txn = CashTransaction(
        transaction_id="CT12345",
        account_id="DU123456",
        transaction_date=date(2025, 12, 26),
        description="Deposit",
        amount=Decimal("10000.00"),
        balance=Decimal("50000.00"),
        currency="USD",
        transaction_type="DEPOSIT",
    )
    
    assert txn.transaction_id == "CT12345"
    assert txn.amount == Decimal("10000.00")
    assert txn.transaction_type == "DEPOSIT"


def test_flex_query_result_valid():
    """Test FlexQueryResult with valid data."""
    result = FlexQueryResult(
        query_id="123456",
        execution_id="EX-20251226-001",
        status=FlexQueryStatus.COMPLETED,
        query_type=FlexQueryType.TRADES,
        from_date=date(2025, 12, 1),
        to_date=date(2025, 12, 26),
        raw_xml="<FlexQueryResponse>...</FlexQueryResponse>",
        data_hash="abc123def456",
        trades=[
            TradeConfirmation(
                trade_id="T1",
                execution_id="E1",
                account_id="DU123456",
                symbol="AAPL",
                description="Apple Inc.",
                trade_date=date(2025, 12, 26),
                quantity=Decimal("100"),
                trade_price=Decimal("195.50"),
                proceeds=Decimal("19550.00"),
                commission=Decimal("1.00"),
                net_cash=Decimal("19549.00"),
                buy_sell="BUY",
            )
        ],
    )
    
    assert result.query_id == "123456"
    assert result.status == FlexQueryStatus.COMPLETED
    assert len(result.trades) == 1
    assert result.trades[0].symbol == "AAPL"
    assert result.data_hash == "abc123def456"


def test_flex_query_result_defaults():
    """Test FlexQueryResult default values."""
    result = FlexQueryResult(
        query_id="123456",
        execution_id="EX-20251226-001",
        status=FlexQueryStatus.PENDING,
        query_type=FlexQueryType.TRADES,
    )
    
    assert result.trades == []
    assert result.pnl_records == []
    assert result.cash_transactions == []
    assert result.raw_xml is None
    assert result.raw_csv is None
    assert result.data_hash is None
    assert result.error_message is None
    assert result.completion_time is None


def test_flex_query_request_valid():
    """Test FlexQueryRequest with valid data."""
    request = FlexQueryRequest(
        query_id="123456",
        from_date=date(2025, 12, 1),
        to_date=date(2025, 12, 26),
    )
    
    assert request.query_id == "123456"
    assert request.from_date == date(2025, 12, 1)
    assert request.to_date == date(2025, 12, 26)


def test_flex_query_request_future_date_validation():
    """Test FlexQueryRequest rejects future dates."""
    from datetime import timedelta
    
    future_date = date.today() + timedelta(days=1)
    
    with pytest.raises(ValueError, match="Date cannot be in the future"):
        FlexQueryRequest(
            query_id="123456",
            from_date=future_date,
        )


def test_flex_query_list_response_valid():
    """Test FlexQueryListResponse with valid data."""
    response = FlexQueryListResponse(
        queries=[
            FlexQueryConfig(
                query_id="123456",
                name="Daily Trades",
                query_type=FlexQueryType.TRADES,
            ),
            FlexQueryConfig(
                query_id="789012",
                name="Weekly P&L",
                query_type=FlexQueryType.REALIZED_PNL,
            ),
        ],
        total=2,
    )
    
    assert len(response.queries) == 2
    assert response.total == 2
    assert response.queries[0].query_id == "123456"
    assert response.queries[1].query_id == "789012"


def test_flex_query_execution_response_valid():
    """Test FlexQueryExecutionResponse with valid data."""
    response = FlexQueryExecutionResponse(
        execution_id="EX-20251226-001",
        status=FlexQueryStatus.PROCESSING,
        message="Query is being processed by IBKR",
        estimated_completion_seconds=60,
    )
    
    assert response.execution_id == "EX-20251226-001"
    assert response.status == FlexQueryStatus.PROCESSING
    assert response.estimated_completion_seconds == 60
