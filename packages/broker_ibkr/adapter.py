"""Broker adapter protocol for IBKR AI Broker.

This module defines the interface that all broker adapters must implement.
"""

from datetime import datetime
from typing import Optional, Protocol, TYPE_CHECKING, List

if TYPE_CHECKING:
    from packages.schemas.approval import ApprovalToken
    from packages.schemas.order_intent import OrderIntent

from packages.schemas.market_data import (
    MarketSnapshot as MarketSnapshotV2,
    MarketBar,
    TimeframeType,
)
from packages.schemas.instrument import (
    InstrumentContract,
    SearchCandidate,
    InstrumentTypeEnum,
)
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

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order on broker.

        Args:
            broker_order_id: Broker's order identifier to cancel.

        Returns:
            True if cancellation request was successful.

        Raises:
            ValueError: If order ID is invalid or order cannot be cancelled.
            ConnectionError: If broker connection fails.
        """
        ...
    
    def get_market_snapshot_v2(
        self,
        instrument: str,
        fields: Optional[List[str]] = None
    ) -> MarketSnapshotV2:
        """Get current market snapshot for an instrument (v2 schema).
        
        Args:
            instrument: Instrument identifier (symbol)
            fields: Optional list of specific fields to retrieve
        
        Returns:
            MarketSnapshotV2 with current market data
        
        Raises:
            ValueError: If instrument is invalid or not found
        """
        ...
    
    def get_market_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        rth_only: bool = True
    ) -> List[MarketBar]:
        """Get historical OHLCV bars for an instrument.
        
        Args:
            instrument: Instrument identifier (symbol)
            timeframe: Bar timeframe (e.g., "1m", "1h", "1d")
            start: Start time (UTC), default: 24 hours ago
            end: End time (UTC), default: now
            limit: Maximum number of bars to return (1-5000)
            rth_only: Regular trading hours only
        
        Returns:
            List of MarketBar sorted by timestamp (oldest first)
        
        Raises:
            ValueError: If parameters are invalid
        """
        ...
    
    def search_instruments(
        self,
        query: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchCandidate]:
        """Search for instruments matching a query.
        
        Args:
            query: Search query (symbol, name, partial match)
            type: Optional instrument type filter (STK, OPT, FUT, etc.)
            exchange: Optional exchange filter (NASDAQ, NYSE, etc.)
            currency: Optional currency filter (USD, EUR, etc.)
            limit: Maximum number of results (1-100)
        
        Returns:
            List of SearchCandidate sorted by match_score (descending)
        
        Raises:
            ValueError: If query is empty or limit is invalid
        """
        ...
    
    def resolve_instrument(
        self,
        symbol: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        con_id: Optional[int] = None
    ) -> InstrumentContract:
        """Resolve instrument to exact contract specification.
        
        Args:
            symbol: Instrument symbol
            type: Optional instrument type
            exchange: Optional exchange
            currency: Optional currency
            con_id: Optional explicit contract ID (highest priority)
        
        Returns:
            Fully resolved InstrumentContract
        
        Raises:
            ValueError: If symbol is invalid
            InstrumentResolutionError: If resolution is ambiguous or not found
        """
        ...
    
    def get_contract_by_id(self, con_id: int) -> Optional[InstrumentContract]:
        """Get instrument contract by IBKR contract ID.
        
        Args:
            con_id: IBKR contract ID
        
        Returns:
            InstrumentContract if found, None otherwise
        
        Raises:
            ValueError: If con_id is invalid (<= 0)
        """
        ...
