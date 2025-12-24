"""Broker adapter protocol for IBKR AI Broker.

This module defines the interface that all broker adapters must implement.
"""

from typing import Protocol

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
