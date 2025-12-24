"""Tests for broker adapter models and fake implementation.

This module contains tests for broker data models and FakeBrokerAdapter.
"""

from decimal import Decimal

import pytest

from packages.broker_ibkr import (
    Account,
    Cash,
    FakeBrokerAdapter,
    Instrument,
    InstrumentType,
    MarketSnapshot,
    OpenOrder,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    TimeInForce,
)


class TestBrokerModels:
    """Tests for broker data models."""

    def test_instrument_creation(self) -> None:
        """Test instrument model creation."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="NASDAQ",
            currency="USD",
            description="Apple Inc.",
        )

        assert instrument.type == InstrumentType.STK
        assert instrument.symbol == "AAPL"
        assert instrument.exchange == "NASDAQ"
        assert instrument.currency == "USD"

    def test_instrument_immutability(self) -> None:
        """Test instrument is immutable."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
        )

        with pytest.raises(Exception):  # Pydantic ValidationError
            instrument.symbol = "MSFT"  # type: ignore

    def test_position_with_pnl(self) -> None:
        """Test position with P&L calculation."""
        instrument = Instrument(
            type=InstrumentType.ETF,
            symbol="SPY",
        )

        position = Position(
            instrument=instrument,
            quantity=Decimal("100"),
            average_cost=Decimal("450.00"),
            market_value=Decimal("46000.00"),
            unrealized_pnl=Decimal("1000.00"),
        )

        assert position.quantity == Decimal("100")
        assert position.unrealized_pnl == Decimal("1000.00")

    def test_cash_balance(self) -> None:
        """Test cash balance model."""
        cash = Cash(
            currency="USD",
            available=Decimal("50000.00"),
            total=Decimal("50000.00"),
        )

        assert cash.available == Decimal("50000.00")
        assert cash.total == Decimal("50000.00")

    def test_portfolio_snapshot(self) -> None:
        """Test portfolio snapshot."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
        )

        position = Position(
            instrument=instrument,
            quantity=Decimal("50"),
            average_cost=Decimal("180.00"),
            market_value=Decimal("9500.00"),
            unrealized_pnl=Decimal("500.00"),
        )

        cash = Cash(
            currency="USD",
            available=Decimal("50000.00"),
            total=Decimal("50000.00"),
        )

        portfolio = Portfolio(
            account_id="DU123456",
            positions=[position],
            cash=[cash],
            total_value=Decimal("59500.00"),
        )

        assert portfolio.account_id == "DU123456"
        assert len(portfolio.positions) == 1
        assert len(portfolio.cash) == 1
        assert portfolio.total_value == Decimal("59500.00")

    def test_market_snapshot(self) -> None:
        """Test market snapshot model."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
        )

        snapshot = MarketSnapshot(
            instrument=instrument,
            bid=Decimal("189.50"),
            ask=Decimal("189.55"),
            last=Decimal("189.52"),
            close=Decimal("188.00"),
            volume=50_000_000,
        )

        assert snapshot.bid == Decimal("189.50")
        assert snapshot.ask == Decimal("189.55")
        assert snapshot.last == Decimal("189.52")
        assert snapshot.volume == 50_000_000

    def test_open_order(self) -> None:
        """Test open order model."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="MSFT",
        )

        order = OpenOrder(
            order_id="ord-123",
            account_id="DU123456",
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            order_type=OrderType.LMT,
            limit_price=Decimal("380.00"),
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.SUBMITTED,
        )

        assert order.side == OrderSide.BUY
        assert order.quantity == Decimal("10")
        assert order.limit_price == Decimal("380.00")
        assert order.status == OrderStatus.SUBMITTED


class TestFakeBrokerAdapter:
    """Tests for FakeBrokerAdapter."""

    @pytest.fixture
    def adapter(self) -> FakeBrokerAdapter:
        """Create fake adapter instance."""
        return FakeBrokerAdapter(account_id="DU123456")

    def test_connection_lifecycle(self, adapter: FakeBrokerAdapter) -> None:
        """Test connect/disconnect cycle."""
        assert not adapter.is_connected()

        adapter.connect()
        assert adapter.is_connected()

        adapter.disconnect()
        assert not adapter.is_connected()

    def test_get_accounts(self, adapter: FakeBrokerAdapter) -> None:
        """Test getting accounts."""
        accounts = adapter.get_accounts()

        assert len(accounts) == 1
        assert accounts[0].account_id == "DU123456"
        assert accounts[0].account_type == "PAPER"

    def test_get_portfolio(self, adapter: FakeBrokerAdapter) -> None:
        """Test getting portfolio."""
        portfolio = adapter.get_portfolio("DU123456")

        assert portfolio.account_id == "DU123456"
        assert len(portfolio.positions) == 2  # SPY + AAPL
        assert len(portfolio.cash) == 1
        assert portfolio.total_value > Decimal("0")

    def test_get_portfolio_invalid_account(
        self, adapter: FakeBrokerAdapter
    ) -> None:
        """Test portfolio with invalid account."""
        with pytest.raises(ValueError, match="Invalid account_id"):
            adapter.get_portfolio("INVALID")

    def test_get_open_orders_empty(self, adapter: FakeBrokerAdapter) -> None:
        """Test getting open orders when empty."""
        orders = adapter.get_open_orders("DU123456")
        assert len(orders) == 0

    def test_add_mock_order(self, adapter: FakeBrokerAdapter) -> None:
        """Test adding mock order."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="TSLA",
        )

        order = OpenOrder(
            order_id="ord-456",
            account_id="DU123456",
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=Decimal("5"),
            order_type=OrderType.MKT,
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.PENDING,
        )

        adapter.add_mock_order(order)
        orders = adapter.get_open_orders("DU123456")

        assert len(orders) == 1
        assert orders[0].order_id == "ord-456"

    def test_get_market_snapshot(self, adapter: FakeBrokerAdapter) -> None:
        """Test getting market snapshot."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
        )

        snapshot = adapter.get_market_snapshot(instrument)

        assert snapshot.instrument.symbol == "AAPL"
        assert snapshot.bid is not None
        assert snapshot.ask is not None
        assert snapshot.last is not None
        assert snapshot.ask > snapshot.bid  # Spread check

    def test_mock_prices_realistic(self, adapter: FakeBrokerAdapter) -> None:
        """Test mock prices are realistic."""
        instrument = Instrument(
            type=InstrumentType.ETF,
            symbol="SPY",
        )

        snapshot = adapter.get_market_snapshot(instrument)

        # Check bid/ask spread is reasonable (<1%)
        spread = snapshot.ask - snapshot.bid  # type: ignore
        mid = (snapshot.ask + snapshot.bid) / Decimal("2")  # type: ignore
        spread_pct = (spread / mid) * Decimal("100")

        assert spread_pct < Decimal("1.0")

    def test_clear_mock_orders(self, adapter: FakeBrokerAdapter) -> None:
        """Test clearing mock orders."""
        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="MSFT",
        )

        order = OpenOrder(
            order_id="ord-789",
            account_id="DU123456",
            instrument=instrument,
            side=OrderSide.SELL,
            quantity=Decimal("10"),
            order_type=OrderType.LMT,
            limit_price=Decimal("380.00"),
            time_in_force=TimeInForce.GTC,
            status=OrderStatus.SUBMITTED,
        )

        adapter.add_mock_order(order)
        assert len(adapter.get_open_orders("DU123456")) == 1

        adapter.clear_mock_orders()
        assert len(adapter.get_open_orders("DU123456")) == 0

    def test_portfolio_value_calculation(
        self, adapter: FakeBrokerAdapter
    ) -> None:
        """Test portfolio total value calculation."""
        portfolio = adapter.get_portfolio("DU123456")

        # Calculate expected total
        positions_value = sum(pos.market_value for pos in portfolio.positions)
        cash_value = sum(c.total for c in portfolio.cash)
        expected_total = positions_value + cash_value

        assert portfolio.total_value == expected_total
