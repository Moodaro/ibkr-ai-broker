"""Fake broker adapter for testing.

This module provides a mock broker adapter with realistic data
for testing purposes without connecting to real IBKR.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from packages.schemas.approval import ApprovalToken
    from packages.schemas.order_intent import OrderIntent

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
        self._submitted_orders: dict[str, OpenOrder] = {}  # broker_order_id -> order

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
    def submit_order(
        self,
        order_intent: "OrderIntent",
        approval_token: "ApprovalToken",
    ) -> OpenOrder:
        """Submit order to mock broker.

        Args:
            order_intent: Order intent to submit.
            approval_token: Valid approval token (caller must validate).

        Returns:
            OpenOrder with broker order ID and SUBMITTED status.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected:
            raise ConnectionError("Not connected to broker")

        # Generate broker order ID
        broker_order_id = f"MOCK{uuid.uuid4().hex[:8].upper()}"
        order_id = str(uuid.uuid4())

        # Create OpenOrder from OrderIntent
        order = OpenOrder(
            order_id=order_id,
            broker_order_id=broker_order_id,
            account_id=order_intent.account_id,
            instrument=order_intent.instrument,
            side=order_intent.side,
            quantity=order_intent.quantity,
            order_type=order_intent.order_type,
            limit_price=order_intent.limit_price,
            stop_price=order_intent.stop_price,
            time_in_force=order_intent.time_in_force,
            status=OrderStatus.SUBMITTED,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        # Store order
        self._submitted_orders[broker_order_id] = order
        self._open_orders.append(order)

        return order

    def get_order_status(self, broker_order_id: str) -> OpenOrder:
        """Get current order status.

        Args:
            broker_order_id: Broker's order identifier.

        Returns:
            OpenOrder with current status.

        Raises:
            ValueError: If order not found.
        """
        order = self._submitted_orders.get(broker_order_id)
        if order is None:
            raise ValueError(f"Order {broker_order_id} not found")

        return order

    def simulate_fill(self, broker_order_id: str, fill_price: Optional[Decimal] = None) -> OpenOrder:
        """Simulate order fill for testing.

        Args:
            broker_order_id: Broker order ID.
            fill_price: Fill price (defaults to market price).

        Returns:
            Updated OpenOrder with FILLED status.

        Raises:
            ValueError: If order not found.
        """
        order = self._submitted_orders.get(broker_order_id)
        if order is None:
            raise ValueError(f"Order {broker_order_id} not found")

        if fill_price is None:
            fill_price = self._get_mock_price(order.instrument.symbol)

        # Create filled order (immutable update)
        filled_order_data = order.model_dump()
        filled_order_data["status"] = OrderStatus.FILLED
        filled_order_data["filled_quantity"] = order.quantity
        filled_order_data["average_fill_price"] = fill_price
        filled_order_data["updated_at"] = datetime.utcnow()

        filled_order = OpenOrder(**filled_order_data)
        self._submitted_orders[broker_order_id] = filled_order

        # Update open orders list
        self._open_orders = [
            filled_order if o.broker_order_id == broker_order_id else o
            for o in self._open_orders
        ]

        return filled_order
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
