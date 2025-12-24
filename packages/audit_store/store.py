"""
Audit store implementation using SQLite for development and PostgreSQL for production.

This module provides append-only storage for audit events with efficient querying.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import AuditEvent, AuditEventCreate, AuditQuery, AuditStats, EventType


class AuditStore:
    """
    Append-only audit event store with SQLite backend.

    Thread-safe for concurrent writes. Events cannot be modified or deleted.
    """

    def __init__(self, db_path: str | Path = "audit.db") -> None:
        """
        Initialize audit store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create database schema if it doesn't exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

            # Create indexes for efficient queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_type 
                ON audit_events(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_correlation_id 
                ON audit_events(correlation_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON audit_events(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON audit_events(created_at DESC)
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get database connection with proper error handling."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def append_event(self, event_create: AuditEventCreate) -> AuditEvent:
        """
        Append a new audit event to the store.

        Args:
            event_create: Event data to append

        Returns:
            The created audit event with generated ID and timestamp

        Raises:
            RuntimeError: If event cannot be persisted
        """
        # Create full event with generated fields
        event = AuditEvent(
            event_type=event_create.event_type,
            correlation_id=event_create.correlation_id,
            data=event_create.data,
            metadata=event_create.metadata,
        )

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_events 
                    (id, event_type, correlation_id, timestamp, data, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.id),
                        event.event_type.value,
                        event.correlation_id,
                        event.timestamp.isoformat(),
                        json.dumps(event.data),
                        json.dumps(event.metadata),
                        datetime.utcnow().isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:
            raise RuntimeError(f"Failed to append audit event: {e}") from e

        return event

    def get_event(self, event_id: str) -> AuditEvent | None:
        """
        Retrieve a specific event by ID.

        Args:
            event_id: UUID of the event

        Returns:
            The event if found, None otherwise
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM audit_events WHERE id = ?", (event_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_event(row)

    def query_events(self, query: AuditQuery) -> list[AuditEvent]:
        """
        Query audit events with filters.

        Args:
            query: Query parameters

        Returns:
            List of matching events, ordered by timestamp descending
        """
        conditions = []
        params: list[str | int] = []

        if query.event_types:
            placeholders = ",".join("?" * len(query.event_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend(et.value for et in query.event_types)

        if query.correlation_id:
            conditions.append("correlation_id = ?")
            params.append(query.correlation_id)

        if query.start_time:
            conditions.append("timestamp >= ?")
            params.append(query.start_time.isoformat())

        if query.end_time:
            conditions.append("timestamp <= ?")
            params.append(query.end_time.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT * FROM audit_events
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([query.limit, query.offset])

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_stats(self) -> AuditStats:
        """
        Get statistics about stored audit events.

        Returns:
            Statistics summary
        """
        with self._get_connection() as conn:
            # Total events
            total = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]

            # Event type counts
            type_counts_rows = conn.execute("""
                SELECT event_type, COUNT(*) as count 
                FROM audit_events 
                GROUP BY event_type
            """).fetchall()
            type_counts = {row["event_type"]: row["count"] for row in type_counts_rows}

            # Time range
            time_range = conn.execute("""
                SELECT 
                    MIN(timestamp) as earliest,
                    MAX(timestamp) as latest
                FROM audit_events
            """).fetchone()

            earliest = (
                datetime.fromisoformat(time_range["earliest"])
                if time_range["earliest"]
                else None
            )
            latest = (
                datetime.fromisoformat(time_range["latest"])
                if time_range["latest"]
                else None
            )

            # Unique correlation IDs
            corr_count = conn.execute("""
                SELECT COUNT(DISTINCT correlation_id) 
                FROM audit_events
            """).fetchone()[0]

            return AuditStats(
                total_events=total,
                event_type_counts=type_counts,
                earliest_event=earliest,
                latest_event=latest,
                correlation_id_count=corr_count,
            )

    def _row_to_event(self, row: sqlite3.Row) -> AuditEvent:
        """Convert database row to AuditEvent model."""
        return AuditEvent(
            id=row["id"],
            event_type=EventType(row["event_type"]),
            correlation_id=row["correlation_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            data=json.loads(row["data"]),
            metadata=json.loads(row["metadata"]),
        )
