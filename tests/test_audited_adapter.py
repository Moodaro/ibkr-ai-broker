"""Tests for audited broker adapter.

This module tests the AuditedBrokerAdapter wrapper that adds
audit logging to broker operations.
"""

import pytest

from packages.audit_store import (
    AuditQuery,
    AuditStore,
    EventType,
    set_correlation_id,
)
from packages.broker_ibkr import (
    AuditedBrokerAdapter,
    FakeBrokerAdapter,
    Instrument,
    InstrumentType,
)


@pytest.fixture
def audit_store(tmp_path) -> AuditStore:
    """Create temporary audit store."""
    db_path = tmp_path / "test_audit.db"
    return AuditStore(str(db_path))


@pytest.fixture
def fake_adapter() -> FakeBrokerAdapter:
    """Create fake broker adapter."""
    return FakeBrokerAdapter(account_id="DU123456")


@pytest.fixture
def audited_adapter(
    fake_adapter: FakeBrokerAdapter,
    audit_store: AuditStore,
) -> AuditedBrokerAdapter:
    """Create audited adapter."""
    return AuditedBrokerAdapter(fake_adapter, audit_store)


class TestAuditedBrokerAdapter:
    """Tests for AuditedBrokerAdapter."""

    def test_connect_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test connect emits audit event."""
        set_correlation_id("test-connect-123")

        audited_adapter.connect()

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.BROKER_CONNECTED],
            correlation_id="test-connect-123",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].event_type == EventType.BROKER_CONNECTED
        assert "message" in events[0].data

    def test_disconnect_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test disconnect emits audit event."""
        set_correlation_id("test-disconnect-456")

        audited_adapter.connect()
        audited_adapter.disconnect()

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.BROKER_DISCONNECTED],
            correlation_id="test-disconnect-456",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].event_type == EventType.BROKER_DISCONNECTED

    def test_get_accounts_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test get_accounts emits audit event."""
        set_correlation_id("test-accounts-789")

        accounts = audited_adapter.get_accounts()

        assert len(accounts) == 1

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.PORTFOLIO_SNAPSHOT_TAKEN],
            correlation_id="test-accounts-789",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].data["operation"] == "get_accounts"
        assert events[0].data["account_count"] == 1

    def test_get_portfolio_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test get_portfolio emits audit event."""
        set_correlation_id("test-portfolio-101")

        portfolio = audited_adapter.get_portfolio("DU123456")

        assert portfolio.account_id == "DU123456"

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.PORTFOLIO_SNAPSHOT_TAKEN],
            correlation_id="test-portfolio-101",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].data["operation"] == "get_portfolio"
        assert events[0].data["account_id"] == "DU123456"
        assert "total_value" in events[0].data

    def test_get_market_snapshot_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test get_market_snapshot emits audit event."""
        set_correlation_id("test-market-202")

        instrument = Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
        )

        snapshot = audited_adapter.get_market_snapshot(instrument)

        assert snapshot.instrument.symbol == "AAPL"

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.MARKET_SNAPSHOT_TAKEN],
            correlation_id="test-market-202",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].data["operation"] == "get_market_snapshot"
        assert events[0].data["symbol"] == "AAPL"
        assert "bid" in events[0].data
        assert "ask" in events[0].data

    def test_get_open_orders_emits_audit_event(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test get_open_orders emits audit event."""
        set_correlation_id("test-orders-303")

        orders = audited_adapter.get_open_orders("DU123456")

        assert len(orders) == 0  # No orders in fake adapter initially

        # Query audit events
        query = AuditQuery(
            event_types=[EventType.PORTFOLIO_SNAPSHOT_TAKEN],
            correlation_id="test-orders-303",
        )
        events = audit_store.query_events(query)

        assert len(events) == 1
        assert events[0].data["operation"] == "get_open_orders"
        assert events[0].data["order_count"] == 0

    def test_correlation_id_propagated(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test correlation ID is propagated to all events."""
        correlation_id = "test-correlation-999"
        set_correlation_id(correlation_id)

        # Perform multiple operations
        audited_adapter.connect()
        audited_adapter.get_accounts()
        audited_adapter.get_portfolio("DU123456")

        # All events should have same correlation ID
        query = AuditQuery(correlation_id=correlation_id)
        events = audit_store.query_events(query)

        assert len(events) >= 3
        for event in events:
            assert event.correlation_id == correlation_id

    def test_audit_without_correlation_id(
        self,
        audited_adapter: AuditedBrokerAdapter,
        audit_store: AuditStore,
    ) -> None:
        """Test audit works even without correlation ID set."""
        set_correlation_id("")  # Clear correlation ID

        audited_adapter.connect()

        # Should use fallback correlation ID
        query = AuditQuery(event_types=[EventType.BROKER_CONNECTED])
        events = audit_store.query_events(query)

        assert len(events) >= 1
        assert events[-1].correlation_id == "no-correlation-id"
