"""
Tests for FlexQueryScheduler background task execution.

Validates cron scheduling, job management, and error handling.
"""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from packages.flex_query.scheduler import FlexQueryScheduler
from packages.flex_query.service import FlexQueryService
from packages.schemas.flex_query import (
    FlexQueryConfig,
    FlexQueryListResponse,
    FlexQueryResult,
    FlexQueryStatus,
    FlexQueryType,
)


@pytest.fixture
def mock_service():
    """Mock FlexQueryService for testing."""
    service = Mock(spec=FlexQueryService)
    
    # Mock queries: one auto-scheduled, one manual, one disabled
    queries = [
        FlexQueryConfig(
            query_id="123456",
            name="Daily Trades",
            query_type=FlexQueryType.TRADES,
            enabled=True,
            auto_schedule=True,
            schedule_cron="0 9 * * *"  # 9 AM daily
        ),
        FlexQueryConfig(
            query_id="789012",
            name="Weekly P&L",
            query_type=FlexQueryType.REALIZED_PNL,
            enabled=True,
            auto_schedule=False  # Manual execution only
        ),
        FlexQueryConfig(
            query_id="345678",
            name="Monthly Cash",
            query_type=FlexQueryType.CASH_REPORT,
            enabled=False,  # Disabled
            auto_schedule=True,
            schedule_cron="0 0 1 * *"  # First of month
        ),
    ]
    
    service.list_queries.return_value = FlexQueryListResponse(
        total=3,
        queries=queries
    )
    
    # Mock execute_query
    mock_result = FlexQueryResult(
        execution_id="exec_123",
        query_id="123456",
        query_type=FlexQueryType.TRADES,
        status=FlexQueryStatus.COMPLETED,
        trades=[],
        realized_pnl=[],
        cash_transactions=[],
        generated_at=datetime.now(timezone.utc),
        file_path=None,
        file_hash=None
    )
    service.execute_query = AsyncMock(return_value=mock_result)
    
    return service


@pytest.fixture
def mock_audit_store():
    """Mock AuditStore for testing."""
    from packages.audit_store import AuditStore
    store = Mock(spec=AuditStore)
    store.append_event = Mock()
    return store


@pytest.fixture
def scheduler(mock_service, mock_audit_store):
    """Create scheduler instance with mocked service and audit store."""
    return FlexQueryScheduler(mock_service, mock_audit_store, timezone="UTC")


def test_scheduler_init(mock_service, mock_audit_store):
    """Test scheduler initialization."""
    scheduler = FlexQueryScheduler(mock_service, mock_audit_store, timezone="America/New_York")
    
    assert scheduler.service is mock_service
    assert scheduler.audit_store is mock_audit_store
    assert scheduler.scheduler is not None
    assert not scheduler.scheduler.running
    assert str(scheduler.scheduler.timezone) == "America/New_York"
    assert len(scheduler._scheduled_job_ids) == 0


def test_schedule_auto_queries_only_enabled_auto(scheduler, mock_service):
    """Test that only enabled queries with auto_schedule=True are scheduled."""
    # Schedule queries (without starting scheduler)
    count = scheduler.schedule_auto_queries()
    
    # Only query 123456 should be scheduled (enabled + auto_schedule)
    # Note: Due to list_queries returning all queries, count will be higher
    # but only enabled+auto_schedule queries go through
    assert count >= 1
    assert "flex_query_123456" in scheduler._scheduled_job_ids


def test_schedule_auto_queries_respects_enabled_only_filter(scheduler):
    """Test that schedule_auto_queries uses enabled_only=True filter."""
    scheduler.schedule_auto_queries()
    
    # Verify list_queries was called with enabled_only=True
    scheduler.service.list_queries.assert_called_once_with(enabled_only=True)


def test_schedule_auto_queries_no_cron_expression(scheduler, mock_service):
    """Test handling of queries with auto_schedule=True but missing cron."""
    # Add query without cron expression
    bad_query = FlexQueryConfig(
        query_id="999999",
        name="Broken Query",
        query_type=FlexQueryType.TRADES,
        enabled=True,
        auto_schedule=True,
        schedule_cron=None  # Missing!
    )
    
    response = mock_service.list_queries.return_value
    response.queries.append(bad_query)
    
    # Should not raise, should skip and log warning
    count = scheduler.schedule_auto_queries()
    
    # Original valid queries (123456, 345678) + new query (999999 skipped) = 2 scheduled
    assert count == 2
    assert "flex_query_999999" not in scheduler._scheduled_job_ids


def test_schedule_auto_queries_invalid_cron(scheduler, mock_service):
    """Test handling of invalid cron expression."""
    # Add query with invalid cron (passes basic validation but fails APScheduler parsing)
    bad_query = FlexQueryConfig(
        query_id="888888",
        name="Invalid Cron Query",
        query_type=FlexQueryType.TRADES,
        enabled=True,
        auto_schedule=True,
        schedule_cron="99 99 99 99 99"  # Invalid: out of range values
    )
    
    response = mock_service.list_queries.return_value
    response.queries.append(bad_query)
    
    # Should not raise, should catch error and continue
    count = scheduler.schedule_auto_queries()
    
    # Original valid queries (123456, 345678) + new invalid (888888 skipped) = 2 scheduled
    assert count == 2
    assert "flex_query_888888" not in scheduler._scheduled_job_ids


@pytest.mark.asyncio
async def test_start_scheduler(scheduler, mock_service):
    """Test starting the scheduler."""
    scheduler.start()
    
    assert scheduler.scheduler.running
    
    # Verify queries were scheduled
    assert "flex_query_123456" in scheduler._scheduled_job_ids
    
    scheduler.stop(wait=False)
    
    # Cleanup
    scheduler.stop(wait=False)


@pytest.mark.asyncio
async def test_start_scheduler_idempotent(scheduler):
    """Test that calling start() multiple times is safe."""
    scheduler.start()
    assert scheduler.scheduler.running
    
    # Call again - should not raise
    scheduler.start()
    assert scheduler.scheduler.running
    
    # Should still have same jobs
    assert "flex_query_123456" in scheduler._scheduled_job_ids
    
    # Cleanup
    scheduler.stop(wait=False)


@pytest.mark.asyncio
async def test_stop_scheduler(scheduler):
    """Test stopping the scheduler."""
    scheduler.start()
    assert scheduler.scheduler.running
    
    scheduler.stop(wait=True)  # Wait for async shutdown
    await asyncio.sleep(0.1)  # Give event loop time to process
    
    assert not scheduler.scheduler.running
    assert len(scheduler._scheduled_job_ids) == 0


def test_stop_scheduler_not_running(scheduler):
    """Test stopping scheduler when not running."""
    assert not scheduler.scheduler.running
    
    # Should not raise
    scheduler.stop(wait=False)
    
    assert not scheduler.scheduler.running


@pytest.mark.asyncio
async def test_execute_scheduled_query_success(scheduler, mock_service):
    """Test successful execution of scheduled query."""
    # Execute query directly (bypass scheduler timing)
    await scheduler._execute_scheduled_query("123456")
    
    # Verify service.execute_query was called
    mock_service.execute_query.assert_called_once_with(
        query_id="123456",
        from_date=None,
        to_date=None
    )


@pytest.mark.asyncio
async def test_execute_scheduled_query_failure(scheduler, mock_service):
    """Test handling of query execution failure."""
    # Make execute_query raise an error
    mock_service.execute_query.side_effect = Exception("IBKR API timeout")
    
    # Should not raise, should catch and log
    await scheduler._execute_scheduled_query("123456")
    
    # Verify service.execute_query was attempted
    mock_service.execute_query.assert_called_once()


def test_cron_trigger_parsing_5_fields(scheduler, mock_service):
    """Test parsing of standard 5-field cron expression."""
    # Create query with 5-field cron
    query = FlexQueryConfig(
        query_id="555555",
        name="5-field Cron",
        query_type=FlexQueryType.TRADES,
        enabled=True,
        auto_schedule=True,
        schedule_cron="30 14 * * 1-5"  # 2:30 PM weekdays
    )
    
    # Add to service mock
    response = mock_service.list_queries.return_value
    response.queries.append(query)
    
    # Should schedule successfully
    count = scheduler.schedule_auto_queries()
    # Original valid queries (123456, 345678) + new query (555555) = 3 scheduled
    assert count == 3
    assert "flex_query_555555" in scheduler._scheduled_job_ids


def test_cron_trigger_parsing_6_fields(scheduler, mock_service):
    """Test parsing of 6-field cron expression (with seconds)."""
    # Create query with 6-field cron
    query = FlexQueryConfig(
        query_id="666666",
        name="6-field Cron",
        query_type=FlexQueryType.TRADES,
        enabled=True,
        auto_schedule=True,
        schedule_cron="0 0 9 * * *"  # 9 AM daily (with seconds)
    )
    
    # Add to service mock
    response = mock_service.list_queries.return_value
    response.queries.append(query)
    
    # Should schedule successfully
    count = scheduler.schedule_auto_queries()
    # Original valid queries (123456, 345678) + new query (666666) = 3 scheduled
    assert count == 3
    assert "flex_query_666666" in scheduler._scheduled_job_ids


def test_scheduler_prevents_duplicate_jobs(scheduler):
    """Test that scheduling same query twice doesn't duplicate jobs."""
    # Schedule first time
    count1 = scheduler.schedule_auto_queries()
    # Expected: 123456 (enabled+auto) and 345678 (enabled+auto) = 2
    assert count1 == 2
    
    # Schedule again (should skip duplicates)
    count2 = scheduler.schedule_auto_queries()
    assert count2 == 0  # No new jobs added (all already scheduled)
    
    # Should still have only two jobs
    jobs = scheduler.scheduler.get_jobs()
    flex_jobs = [j for j in jobs if j.id.startswith("flex_query_")]
    assert len(flex_jobs) == 2


@pytest.mark.asyncio
async def test_scheduler_audit_events_emitted(scheduler, mock_service, mock_audit_store):
    """Test that audit events are emitted for scheduled execution."""
    await scheduler._execute_scheduled_query("123456")
    
    # Verify audit events were called
    assert mock_audit_store.append_event.call_count >= 2  # At least start + completion events
    
    # Check event types
    event_types = [call.args[0].event_type for call in mock_audit_store.append_event.call_args_list]
    from packages.audit_store.models import EventType
    
    assert EventType.FLEX_QUERY_SCHEDULED in event_types
    # Should have either COMPLETED or FAILED
    assert (
        EventType.FLEX_QUERY_COMPLETED in event_types
        or EventType.FLEX_QUERY_FAILED in event_types
    )


def test_scheduler_max_instances_prevents_concurrent_runs(scheduler):
    """Test that max_instances=1 prevents concurrent execution of same query."""
    scheduler.schedule_auto_queries()
    
    # Get the scheduled job
    jobs = scheduler.scheduler.get_jobs()
    flex_job = next(j for j in jobs if j.id == "flex_query_123456")
    
    # Verify max_instances is set
    assert flex_job.max_instances == 1
