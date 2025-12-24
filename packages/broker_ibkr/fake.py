"""Fake broker adapter for testing.

This module provides a mock broker adapter with realistic data
for testing purposes without connecting to real IBKR.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from .adapter import BrokerAdapter
from .models import (
    Account,
    Cash,
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


class FakeBrokerAdapter:
    """Fake broker adapter for testing.

    Provides realistic mock data without requiring IBKR connection.
    Useful for unit tests and development.
    """

    def __init__(self, account_id: str = "DU123456") -> None:
        """Initialize fake adapter.

        Args:
            account_id: Mock account ID.
        """
        self._account_id = account_id
        self._connected = False
        self._positions: list[Position] = self._create_mock_positions()
        self._cash: list[Cash] = self._create_mock_cash()
        self._open_orders: list[OpenOrder] = []

    def connect(self) -> None:
        """Simulate connection."""
        self._connected = True

    def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected

    def get_accounts(self) -> list[Account]:
        """Get mock accounts."""
        return [
            Account(
                account_id=self._account_id,
                account_type="PAPER",
                currency="USD",
                timestamp=datetime.utcnow(),
            )
        ]

    def get_portfolio(self, account_id: str) -> Portfolio:
        """Get mock portfolio.

        Args:
            account_id: Account ID.

        Returns:
            Mock portfolio.

        Raises:
            ValueError: If account_id doesn't match.
        """
        if account_id != self._account_id:
            raise ValueError(f"Invalid account_id: {account_id}")

        total_value = sum(
            pos.market_value for pos in self._positions
        ) + sum(cash.total for cash in self._cash)

        return Portfolio(
            account_id=account_id,
            positions=self._positions,
            cash=self._cash,
            total_value=total_value,
            timestamp=datetime.utcnow(),
        )

    def get_open_orders(self, account_id: str) -> list[OpenOrder]:
        """Get mock open orders.

        Args:
            account_id: Account ID.

        Returns:
            List of mock open orders.

        Raises:
            ValueError: If account_id doesn't match.
        """
        if account_id != self._account_id:
            raise ValueError(f"Invalid account_id: {account_id}")

        return self._open_orders.copy()

    def get_market_snapshot(self, instrument: Instrument) -> MarketSnapshot:
        """Get mock market data.

        Args:
            instrument: Instrument to get data for.

        Returns:
            Mock market snapshot.
        """
        # Mock prices based on symbol
        base_price = self._get_mock_price(instrument.symbol)

        return MarketSnapshot(
            instrument=instrument,
            bid=base_price * Decimal("0.9995"),
            ask=base_price * Decimal("1.0005"),
            last=base_price,
            close=base_price * Decimal("0.998"),
            volume=1_000_000,
            timestamp=datetime.utcnow(),
        )

    def add_mock_order(self, order: OpenOrder) -> None:
        """Add mock order for testing.

        Args:
            order: Order to add.
        """
        self._open_orders.append(order)

    def clear_mock_orders(self) -> None:
        """Clear all mock orders."""
        self._open_orders.clear()

    def _create_mock_positions(self) -> list[Position]:
        """Create mock positions."""
        return [
            Position(
                instrument=Instrument(
                    type=InstrumentType.ETF,
                    symbol="SPY",
                    exchange="ARCA",
                    currency="USD",
                    description="SPDR S&P 500 ETF Trust",
                ),
                quantity=Decimal("100"),
                average_cost=Decimal("450.00"),
                market_value=Decimal("46000.00"),
                unrealized_pnl=Decimal("1000.00"),
                realized_pnl=Decimal("0"),
                timestamp=datetime.utcnow(),
            ),
            Position(
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="AAPL",
                    exchange="NASDAQ",
                    currency="USD",
                    description="Apple Inc.",
                ),
                quantity=Decimal("50"),
                average_cost=Decimal("180.00"),
                market_value=Decimal("9500.00"),
                unrealized_pnl=Decimal("500.00"),
                realized_pnl=Decimal("250.00"),
                timestamp=datetime.utcnow(),
            ),
        ]

    def _create_mock_cash(self) -> list[Cash]:
        """Create mock cash balances."""
        return [
            Cash(
                currency="USD",
                available=Decimal("50000.00"),
                total=Decimal("50000.00"),
                timestamp=datetime.utcnow(),
            )
        ]

    def _get_mock_price(self, symbol: str) -> Decimal:
        """Get mock price for symbol."""
        mock_prices = {
            "SPY": Decimal("460.00"),
            "AAPL": Decimal("190.00"),
            "MSFT": Decimal("380.00"),
            "GOOGL": Decimal("140.00"),
            "TSLA": Decimal("250.00"),
        }
        return mock_prices.get(symbol, Decimal("100.00"))
