"""Broker adapter protocol for IBKR AI Broker.

This module defines the interface that all broker adapters must implement.
"""

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from packages.schemas.approval import ApprovalToken
    from packages.schemas.order_intent import OrderIntent

from .models import (
    Account,
    Instrument,
    MarketSnapshot,
    OpenOrder,
    Portfolio,
)


class BrokerAdapter(Protocol):
    """Protocol defining broker adapter interface.

    All broker adapters (real IBKR, fake, etc.) must implement this interface.
    This ensures consistent behavior and easy testing.
    """

    def get_accounts(self) -> list[Account]:
        """Get list of accounts.

        Returns:
            List of accounts accessible by current connection.
        """
        ...

    def get_portfolio(self, account_id: str) -> Portfolio:
        """Get complete portfolio snapshot.

        Args:
            account_id: Account identifier.

        Returns:
            Portfolio snapshot with positions and cash.

        Raises:
            ValueError: If account_id is invalid.
        """
        ...

    def get_open_orders(self, account_id: str) -> list[OpenOrder]:
        """Get open orders for account.

        Args:
            account_id: Account identifier.

        Returns:
            List of open orders.

        Raises:
            ValueError: If account_id is invalid.
        """
        ...

    def get_market_snapshot(self, instrument: Instrument) -> MarketSnapshot:
        """Get market data snapshot for instrument.

        Args:
            instrument: Instrument to get data for.

        Returns:
            Market data snapshot.

        Raises:
            ValueError: If instrument is invalid.
        """
        ...

    def connect(self) -> None:
        """Establish connection to broker.

        Raises:
            ConnectionError: If connection fails.
        """
        ...

    def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    def is_connected(self) -> bool:
        """Check if connected to broker.

        Returns:
            True if connected, False otherwise.
        """
        ...

    def submit_order(
        self,
        order_intent: "OrderIntent",
        approval_token: "ApprovalToken",
    ) -> OpenOrder:
        """Submit order to broker.

        Args:
            order_intent: Order intent to submit.
            approval_token: Valid approval token (must be validated before call).

        Returns:
            OpenOrder with broker order ID and initial status.

        Raises:
            ValueError: If order is invalid.
            ConnectionError: If broker connection fails.
        """
        ...

    def get_order_status(self, broker_order_id: str) -> OpenOrder:
        """Get current order status from broker.

        Args:
            broker_order_id: Broker's order identifier.

        Returns:
            OpenOrder with current status.

        Raises:
            ValueError: If order ID is invalid.
        """
        ...
