"""
Unit tests for audit store models and storage.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from packages.audit_store import (
    AuditEvent,
    AuditEventCreate,
    AuditQuery,
    AuditStore,
    EventType,
)


class TestAuditEventModel:
    """Tests for AuditEvent Pydantic model."""

    def test_audit_event_creation(self) -> None:
        """Test creating a valid audit event."""
        event = AuditEvent(
            event_type=EventType.ORDER_PROPOSED,
            correlation_id="test-123",
            data={"symbol": "AAPL", "quantity": 100},
            metadata={"user": "test_user"},
        )

        assert event.id is not None
        assert event.event_type == EventType.ORDER_PROPOSED
        assert event.correlation_id == "test-123"
        assert event.timestamp is not None
        assert event.data["symbol"] == "AAPL"
        assert event.metadata["user"] == "test_user"

    def test_audit_event_immutability(self) -> None:
        """Test that audit events are immutable."""
        event = AuditEvent(
            event_type=EventType.ORDER_PROPOSED,
            correlation_id="test-123",
        )

        with pytest.raises(Exception):  # Pydantic raises ValidationError or TypeError
            event.event_type = EventType.ORDER_FILLED  # type: ignore

    def test_audit_event_correlation_id_validation(self) -> None:
        """Test correlation ID validation."""
        from pydantic import ValidationError

        # Empty correlation ID should raise error
        with pytest.raises(ValidationError):
            AuditEvent(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="",
            )

        # Whitespace-only should raise error
        with pytest.raises(ValueError, match="correlation_id cannot be empty"):
            AuditEvent(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="   ",
            )

    def test_audit_event_create_model(self) -> None:
        """Test AuditEventCreate model for input validation."""
        event_create = AuditEventCreate(
            event_type=EventType.PORTFOLIO_SNAPSHOT_TAKEN,
            correlation_id="corr-456",
            data={"positions": []},
        )

        assert event_create.event_type == EventType.PORTFOLIO_SNAPSHOT_TAKEN
        assert event_create.correlation_id == "corr-456"
        assert event_create.data["positions"] == []


class TestAuditStore:
    """Tests for AuditStore implementation."""

    @pytest.fixture
    def temp_db(self) -> Path:
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            db_path = Path(f.name)
        yield db_path
        # Cleanup
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def audit_store(self, temp_db: Path) -> AuditStore:
        """Create an audit store instance for testing."""
        return AuditStore(db_path=temp_db)

    def test_store_initialization(self, audit_store: AuditStore) -> None:
        """Test that store initializes correctly."""
        assert audit_store.db_path.exists()

    def test_append_event(self, audit_store: AuditStore) -> None:
        """Test appending an event to the store."""
        event_create = AuditEventCreate(
            event_type=EventType.ORDER_PROPOSED,
            correlation_id="test-correlation-1",
            data={"symbol": "TSLA", "side": "BUY", "quantity": 50},
            metadata={"user": "trader_1"},
        )

        event = audit_store.append_event(event_create)

        assert event.id is not None
        assert event.event_type == EventType.ORDER_PROPOSED
        assert event.correlation_id == "test-correlation-1"
        assert event.data["symbol"] == "TSLA"
        assert event.metadata["user"] == "trader_1"

    def test_get_event(self, audit_store: AuditStore) -> None:
        """Test retrieving an event by ID."""
        # Create and append event
        event_create = AuditEventCreate(
            event_type=EventType.RISK_GATE_EVALUATED,
            correlation_id="test-corr-2",
            data={"decision": "APPROVE"},
        )
        created_event = audit_store.append_event(event_create)

        # Retrieve event
        retrieved_event = audit_store.get_event(str(created_event.id))

        assert retrieved_event is not None
        assert retrieved_event.id == created_event.id
        assert retrieved_event.event_type == EventType.RISK_GATE_EVALUATED
        assert retrieved_event.data["decision"] == "APPROVE"

    def test_get_nonexistent_event(self, audit_store: AuditStore) -> None:
        """Test retrieving non-existent event returns None."""
        fake_id = str(uuid4())
        event = audit_store.get_event(fake_id)
        assert event is None

    def test_query_events_by_type(self, audit_store: AuditStore) -> None:
        """Test querying events by type."""
        # Append multiple events
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="corr-1",
            )
        )
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_SIMULATED,
                correlation_id="corr-1",
            )
        )
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="corr-2",
            )
        )

        # Query for ORDER_PROPOSED events
        query = AuditQuery(event_types=[EventType.ORDER_PROPOSED])
        results = audit_store.query_events(query)

        assert len(results) == 2
        assert all(e.event_type == EventType.ORDER_PROPOSED for e in results)

    def test_query_events_by_correlation_id(self, audit_store: AuditStore) -> None:
        """Test querying events by correlation ID."""
        correlation_id = "unique-corr-123"

        # Append events with same correlation ID
        for event_type in [
            EventType.ORDER_PROPOSED,
            EventType.ORDER_SIMULATED,
            EventType.RISK_GATE_EVALUATED,
        ]:
            audit_store.append_event(
                AuditEventCreate(
                    event_type=event_type,
                    correlation_id=correlation_id,
                )
            )

        # Query by correlation ID
        query = AuditQuery(correlation_id=correlation_id)
        results = audit_store.query_events(query)

        assert len(results) == 3
        assert all(e.correlation_id == correlation_id for e in results)

    def test_query_events_with_time_range(self, audit_store: AuditStore) -> None:
        """Test querying events within a time range."""
        now = datetime.utcnow()
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        # Append event
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.KILL_SWITCH_ACTIVATED,
                correlation_id="time-test",
            )
        )

        # Query with time range that includes event
        query = AuditQuery(start_time=past, end_time=future)
        results = audit_store.query_events(query)

        assert len(results) == 1

    def test_query_events_with_pagination(self, audit_store: AuditStore) -> None:
        """Test pagination in query results."""
        # Append 5 events
        for i in range(5):
            audit_store.append_event(
                AuditEventCreate(
                    event_type=EventType.MCP_TOOL_CALLED,
                    correlation_id=f"page-test-{i}",
                )
            )

        # Query first page
        query = AuditQuery(limit=2, offset=0)
        page1 = audit_store.query_events(query)
        assert len(page1) == 2

        # Query second page
        query = AuditQuery(limit=2, offset=2)
        page2 = audit_store.query_events(query)
        assert len(page2) == 2

        # Verify different results
        assert page1[0].id != page2[0].id

    def test_get_stats(self, audit_store: AuditStore) -> None:
        """Test getting audit statistics."""
        # Append events of different types
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="stats-1",
            )
        )
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_PROPOSED,
                correlation_id="stats-1",
            )
        )
        audit_store.append_event(
            AuditEventCreate(
                event_type=EventType.ORDER_FILLED,
                correlation_id="stats-2",
            )
        )

        stats = audit_store.get_stats()

        assert stats.total_events == 3
        assert stats.event_type_counts["OrderProposed"] == 2
        assert stats.event_type_counts["OrderFilled"] == 1
        assert stats.correlation_id_count == 2
        assert stats.earliest_event is not None
        assert stats.latest_event is not None

    def test_empty_store_stats(self, audit_store: AuditStore) -> None:
        """Test statistics on empty store."""
        stats = audit_store.get_stats()

        assert stats.total_events == 0
        assert stats.event_type_counts == {}
        assert stats.earliest_event is None
        assert stats.latest_event is None
        assert stats.correlation_id_count == 0

    def test_append_event_thread_safety(self, audit_store: AuditStore) -> None:
        """Test that multiple events can be appended safely."""
        # This is a basic test; true thread safety would require concurrent testing
        events = []
        for i in range(10):
            event = audit_store.append_event(
                AuditEventCreate(
                    event_type=EventType.MCP_TOOL_COMPLETED,
                    correlation_id=f"thread-test-{i}",
                )
            )
            events.append(event)

        # Verify all events were stored
        assert len(events) == 10
        assert len(set(e.id for e in events)) == 10  # All unique IDs
