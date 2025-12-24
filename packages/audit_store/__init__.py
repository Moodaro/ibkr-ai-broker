"""
Audit store package for event sourcing and compliance logging.

This package provides an append-only audit log for all system events,
enabling full reconstruction of system state and decision history.
"""

from .middleware import (
    CorrelationIdMiddleware,
    get_correlation_id,
    set_correlation_id,
)
from .models import (
    AuditEvent,
    AuditEventCreate,
    AuditQuery,
    AuditStats,
    EventType,
)
from .store import AuditStore

__all__ = [
    "AuditEvent",
    "AuditEventCreate",
    "AuditQuery",
    "AuditStats",
    "CorrelationIdMiddleware",
    "EventType",
    "AuditStore",
    "get_correlation_id",
    "set_correlation_id",
]
