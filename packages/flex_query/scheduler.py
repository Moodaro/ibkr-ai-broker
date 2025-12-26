"""
Background scheduler for automated Flex Query execution.

Uses APScheduler to run queries on cron schedules defined in configuration.
"""

from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.audit_store import AuditEvent, AuditStore, EventType
from packages.flex_query.service import FlexQueryService
from packages.structured_logging import get_logger

logger = get_logger(__name__)


class FlexQueryScheduler:
    """
    Background scheduler for automated Flex Query execution.
    
    Manages cron-based scheduling for queries with auto_schedule=True.
    Each query runs independently on its configured schedule.
    
    **Safety**:
    - Only schedules enabled queries with auto_schedule=True
    - Validates cron expressions before scheduling
    - Emits audit events for all scheduled executions
    - Handles execution failures gracefully
    
    **Usage**:
    ```python
    scheduler = FlexQueryScheduler(flex_query_service)
    scheduler.start()  # Start background scheduler
    
    # ... application runs ...
    
    scheduler.stop()  # Cleanup on shutdown
    ```
    """
    
    def __init__(
        self,
        service: FlexQueryService,
        audit_store: AuditStore,
        timezone: str = "UTC"
    ):
        """
        Initialize scheduler with FlexQueryService and AuditStore.
        
        Args:
            service: FlexQueryService instance for executing queries
            audit_store: AuditStore instance for logging events
            timezone: Timezone for cron schedules (default: UTC)
        """
        self.service = service
        self.audit_store = audit_store
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._scheduled_job_ids: set[str] = set()
        
        logger.info(
            "FlexQueryScheduler initialized",
            extra={"timezone": timezone}
        )
    
    def start(self) -> None:
        """
        Start the background scheduler.
        
        Schedules all auto-enabled queries and starts the scheduler loop.
        Safe to call multiple times (idempotent).
        """
        if self.scheduler.running:
            logger.warning("Scheduler already running")
            return
        
        # Schedule all auto-enabled queries
        scheduled_count = self.schedule_auto_queries()
        
        # Start scheduler
        self.scheduler.start()
        
        logger.info(
            "FlexQueryScheduler started",
            extra={
                "scheduled_queries": scheduled_count,
                "running": self.scheduler.running
            }
        )
        
        # Emit audit event
        self.audit_store.append_event(AuditEvent(
            event_type=EventType.SYSTEM_STARTED,
            correlation_id=f"scheduler_start_{datetime.now(timezone.utc).isoformat()}",
            timestamp=datetime.now(timezone.utc),
            data={
                "component": "FlexQueryScheduler",
                "scheduled_queries": scheduled_count
            }
        ))
    
    def stop(self, wait: bool = True) -> None:
        """
        Stop the background scheduler.
        
        Args:
            wait: If True, wait for running jobs to complete
        """
        if not self.scheduler.running:
            logger.warning("Scheduler not running")
            return
        
        self.scheduler.shutdown(wait=wait)
        self._scheduled_job_ids.clear()
        
        logger.info(
            "FlexQueryScheduler stopped",
            extra={"wait_for_completion": wait}
        )
        
        # Emit audit event
        self.audit_store.append_event(AuditEvent(
            event_type=EventType.SYSTEM_STOPPED,
            correlation_id=f"scheduler_stop_{datetime.now(timezone.utc).isoformat()}",
            timestamp=datetime.now(timezone.utc),
            data={
                "component": "FlexQueryScheduler"
            }
        ))
    
    def schedule_auto_queries(self) -> int:
        """
        Schedule all queries with auto_schedule=True.
        
        Only schedules enabled queries with valid cron expressions.
        Skips queries already scheduled.
        
        Returns:
            Number of queries scheduled
        """
        queries = self.service.list_queries(enabled_only=True)
        scheduled_count = 0
        
        for query in queries.queries:
            if not query.auto_schedule:
                continue
            
            if not query.schedule_cron:
                logger.warning(
                    "query_missing_cron_expression",
                    query_id=query.query_id,
                    query_name=query.name
                )
                continue
            
            try:
                was_scheduled = self._add_job(query)
                if was_scheduled:
                    scheduled_count += 1
            except Exception as e:
                logger.error(
                    "query_schedule_failed",
                    query_id=query.query_id,
                    query_name=query.name,
                    error=str(e),
                    exc_info=True
                )
        
        logger.info(
            "auto_scheduled_queries",
            total_queries=len(queries.queries),
            scheduled=scheduled_count
        )
        
        return scheduled_count
    
    def _add_job(self, query) -> bool:
        """
        Add a single query as a scheduled job.
        
        Args:
            query: FlexQueryConfig instance
        
        Returns:
            True if query was scheduled, False if already scheduled or skipped
        
        Raises:
            ValueError: If cron expression is invalid
        """
        job_id = f"flex_query_{query.query_id}"
        
        # Skip if already scheduled
        if job_id in self._scheduled_job_ids:
            logger.debug(
                "query_already_scheduled",
                query_id=query.query_id
            )
            return False
        
        # Parse cron expression (support 5 or 6 fields)
        try:
            fields = query.schedule_cron.strip().split()
            
            if len(fields) == 5:
                # Standard 5-field cron: minute hour day month weekday
                trigger = CronTrigger.from_crontab(
                    query.schedule_cron,
                    timezone=self.scheduler.timezone
                )
            elif len(fields) == 6:
                # 6-field cron: second minute hour day month weekday
                # APScheduler CronTrigger supports seconds in constructor
                second, minute, hour, day, month, day_of_week = fields
                trigger = CronTrigger(
                    second=second,
                    minute=minute,
                    hour=hour,
                    day=day,
                    month=month,
                    day_of_week=day_of_week,
                    timezone=self.scheduler.timezone
                )
            else:
                raise ValueError(f"Cron expression must have 5 or 6 fields, got {len(fields)}")
                
        except Exception as e:
            logger.error(
                "invalid_cron_expression",
                query_id=query.query_id,
                cron=query.schedule_cron,
                error=str(e)
            )
            raise ValueError(f"Invalid cron expression: {query.schedule_cron}") from e
        
        # Add job to scheduler
        self.scheduler.add_job(
            self._execute_scheduled_query,
            trigger=trigger,
            args=[query.query_id],
            id=job_id,
            name=f"Flex Query: {query.name}",
            replace_existing=True,
            max_instances=1  # Prevent concurrent runs of same query
        )
        
        self._scheduled_job_ids.add(job_id)
        
        logger.info(
            "Scheduled query",
            extra={
                "query_id": query.query_id,
                "name": query.name,
                "cron": query.schedule_cron,
                "next_run": trigger.get_next_fire_time(
                    None,
                    datetime.now(self.scheduler.timezone)
                )
            }
        )
        
        return True
    
    async def _execute_scheduled_query(self, query_id: str) -> None:
        """
        Execute a scheduled query.
        
        Called by APScheduler on cron trigger.
        Handles errors gracefully and emits audit events.
        
        Args:
            query_id: Flex Query ID to execute
        """
        correlation_id = f"scheduled_flex_{query_id}_{datetime.now(timezone.utc).isoformat()}"
        
        logger.info(
            "Executing scheduled query",
            extra={"query_id": query_id, "correlation_id": correlation_id}
        )
        
        # Emit start event
        self.audit_store.append_event(AuditEvent(
            event_type=EventType.FLEX_QUERY_SCHEDULED,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "query_id": query_id,
                "trigger": "cron_schedule"
            }
        ))
        
        try:
            # Execute query (no date range = default to recent)
            result = await self.service.execute_query(
                query_id=query_id,
                from_date=None,
                to_date=None
            )
            
            logger.info(
                "Scheduled query executed",
                extra={
                    "query_id": query_id,
                    "execution_id": result.execution_id,
                    "status": result.status,
                    "correlation_id": correlation_id
                }
            )
            
            # Emit completion event
            self.audit_store.append_event(AuditEvent(
                event_type=EventType.FLEX_QUERY_COMPLETED,
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
                data={
                    "query_id": query_id,
                    "execution_id": result.execution_id,
                    "status": result.status.value,
                    "trade_count": len(result.trades),
                    "pnl_count": len(result.realized_pnl),
                    "cash_count": len(result.cash_transactions)
                }
            ))
            
        except Exception as e:
            logger.error(
                "Scheduled query execution failed",
                extra={
                    "query_id": query_id,
                    "error": str(e),
                    "correlation_id": correlation_id
                },
                exc_info=True
            )
            
            # Emit failure event
            self.audit_store.append_event(AuditEvent(
                event_type=EventType.FLEX_QUERY_FAILED,
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
                data={
                    "query_id": query_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            ))
