"""Broker adapter with audit logging.

This module provides a wrapper around broker adapters that automatically
emits audit events for all broker operations.
"""

from typing import Any

from packages.audit_store import (
    AuditStore,
    EventType,
    get_correlation_id,
)

from .adapter import BrokerAdapter
from .models import (
    Account,
    Instrument,
    MarketSnapshot,
    OpenOrder,
    Portfolio,
)


class AuditedBrokerAdapter:
    """Wrapper that adds audit logging to any broker adapter.

    This class wraps a broker adapter and automatically emits audit events
    for all operations, enabling full traceability.
    """

    def __init__(
        self,
        adapter: BrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Initialize audited adapter.

        Args:
            adapter: Underlying broker adapter.
            audit_store: Audit store for logging events.
        """
        self._adapter = adapter
        self._audit = audit_store

    def connect(self) -> None:
        """Connect with audit."""
        self._adapter.connect()
        self._emit_event(
            EventType.BROKER_CONNECTED,
            {"message": "Broker connection established"},
        )

    def disconnect(self) -> None:
        """Disconnect with audit."""
        self._adapter.disconnect()
        self._emit_event(
            EventType.BROKER_DISCONNECTED,
            {"message": "Broker connection closed"},
        )

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._adapter.is_connected()

    def get_accounts(self) -> list[Account]:
        """Get accounts with audit."""
        accounts = self._adapter.get_accounts()

        self._emit_event(
            EventType.PORTFOLIO_SNAPSHOT_TAKEN,
            {
                "operation": "get_accounts",
                "account_count": len(accounts),
                "account_ids": [acc.account_id for acc in accounts],
            },
        )

        return accounts

    def get_portfolio(self, account_id: str) -> Portfolio:
        """Get portfolio with audit."""
        portfolio = self._adapter.get_portfolio(account_id)

        self._emit_event(
            EventType.PORTFOLIO_SNAPSHOT_TAKEN,
            {
                "operation": "get_portfolio",
                "account_id": account_id,
                "position_count": len(portfolio.positions),
                "total_value": str(portfolio.total_value),
                "timestamp": portfolio.timestamp.isoformat(),
            },
        )

        return portfolio

    def get_open_orders(self, account_id: str) -> list[OpenOrder]:
        """Get open orders with audit."""
        orders = self._adapter.get_open_orders(account_id)

        self._emit_event(
            EventType.PORTFOLIO_SNAPSHOT_TAKEN,
            {
                "operation": "get_open_orders",
                "account_id": account_id,
                "order_count": len(orders),
                "order_ids": [order.order_id for order in orders],
            },
        )

        return orders

    def get_market_snapshot(self, instrument: Instrument) -> MarketSnapshot:
        """Get market snapshot with audit."""
        snapshot = self._adapter.get_market_snapshot(instrument)

        self._emit_event(
            EventType.MARKET_SNAPSHOT_TAKEN,
            {
                "operation": "get_market_snapshot",
                "symbol": instrument.symbol,
                "instrument_type": instrument.type.value,
                "bid": str(snapshot.bid) if snapshot.bid else None,
                "ask": str(snapshot.ask) if snapshot.ask else None,
                "last": str(snapshot.last) if snapshot.last else None,
                "timestamp": snapshot.timestamp.isoformat(),
            },
        )

        return snapshot

    def _emit_event(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit audit event.

        Args:
            event_type: Type of event.
            data: Event data.
        """
        from packages.audit_store import AuditEventCreate

        correlation_id = get_correlation_id() or "no-correlation-id"

        event_create = AuditEventCreate(
            event_type=event_type,
            correlation_id=correlation_id,
            data=data,
        )

        self._audit.append_event(event_create)
