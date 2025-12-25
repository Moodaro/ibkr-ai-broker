"""Fake broker adapter for testing.

This module provides a mock broker adapter with realistic data
for testing purposes without connecting to real IBKR.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, TYPE_CHECKING, List
import uuid
import random
import math

if TYPE_CHECKING:
    from packages.schemas.approval import ApprovalToken
    from packages.schemas.order_intent import OrderIntent

from packages.schemas.market_data import (
    MarketSnapshot as MarketSnapshotV2,
    MarketBar,
    TimeframeType,
)
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
    
    def get_market_snapshot_v2(
        self,
        instrument: str,
        fields: Optional[List[str]] = None
    ) -> MarketSnapshotV2:
        """Get market snapshot with v2 schema.
        
        Args:
            instrument: Instrument symbol
            fields: Optional list of specific fields
        
        Returns:
            MarketSnapshotV2 with realistic mock data
        """
        base_price = self._get_mock_price(instrument)
        spread = base_price * Decimal("0.001")  # 0.1% spread
        
        # Add realistic variability
        noise = Decimal(str(random.uniform(-0.005, 0.005)))  # ±0.5%
        current_price = base_price * (Decimal("1") + noise)
        
        bid = current_price - spread / Decimal("2")
        ask = current_price + spread / Decimal("2")
        
        return MarketSnapshotV2(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=bid,
            ask=ask,
            last=current_price,
            volume=random.randint(100000, 5000000),
            bid_size=random.randint(100, 1000),
            ask_size=random.randint(100, 1000),
            high=current_price * Decimal("1.015"),
            low=current_price * Decimal("0.985"),
            open_price=base_price,
            prev_close=base_price * Decimal("0.998"),
        )
    
    def get_market_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        rth_only: bool = True
    ) -> List[MarketBar]:
        """Get historical bars with realistic OHLCV data.
        
        Args:
            instrument: Instrument symbol
            timeframe: Bar timeframe
            start: Start time (default: 24h ago)
            end: End time (default: now)
            limit: Max bars to return
            rth_only: Regular trading hours only
        
        Returns:
            List of MarketBar with simulated price movement
        """
        # Parse timeframe
        timeframe_minutes = self._parse_timeframe(timeframe)
        
        # Default time range
        if end is None:
            end = datetime.utcnow()
        if start is None:
            start = end - timedelta(hours=24)
        
        # Ensure we don't generate more bars than the time range allows
        max_possible_bars = int((end - start).total_seconds() / 60 / timeframe_minutes)
        actual_limit = min(limit, max_possible_bars, 1000)  # Cap at 1000 for safety
        
        # Generate bars
        bars = []
        base_price = self._get_mock_price(instrument)
        current_price = base_price
        current_time = start
        
        while current_time < end and len(bars) < actual_limit:
            # Simulate price movement with trend + noise
            trend = random.uniform(-0.002, 0.002)  # ±0.2% trend
            volatility = float(base_price) * 0.01  # 1% volatility
            
            # Generate OHLC
            open_price = current_price
            high = open_price + Decimal(str(abs(random.gauss(0, volatility))))
            low = open_price - Decimal(str(abs(random.gauss(0, volatility))))
            close = open_price * (Decimal("1") + Decimal(str(trend)))
            
            # Ensure OHLC relationships
            high = max(high, open_price, close)
            low = min(low, open_price, close)
            
            volume = random.randint(10000, 500000)
            
            bars.append(MarketBar(
                instrument=instrument,
                timestamp=current_time,
                timeframe=timeframe,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                vwap=(open_price + high + low + close) / Decimal("4"),
                trade_count=random.randint(100, 5000),
            ))
            
            # Move to next bar
            current_price = close
            current_time += timedelta(minutes=timeframe_minutes)
        
        return bars
    
    def _parse_timeframe(self, timeframe: TimeframeType) -> int:
        """Parse timeframe string to minutes.
        
        Args:
            timeframe: Timeframe string (e.g., "1m", "1h", "1d")
        
        Returns:
            Number of minutes in timeframe
        """
        mapping = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
            "1w": 10080,
            "1M": 43200,  # Approximate
        }
        return mapping.get(timeframe, 60)  # Default to 1h
