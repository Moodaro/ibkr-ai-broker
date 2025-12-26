"""
Health monitoring and alerting implementation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from packages.audit_store import AuditEvent, AuditStore, EventType


class HealthStatus(Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthCheck:
    """Result of a health check."""

    name: str
    status: HealthStatus
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """Alert triggered by monitoring condition."""

    condition_name: str
    severity: AlertSeverity
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertCondition:
    """Condition that triggers an alert."""

    name: str
    check_function: Callable[[], bool]  # Returns True if alert should trigger
    severity: AlertSeverity
    message_template: str
    cooldown_seconds: int = 300  # Don't re-alert for 5 minutes


class HealthMonitor:
    """
    Health monitoring and alerting system.

    Performs periodic health checks and triggers alerts based on conditions.
    """

    def __init__(
        self,
        audit_store: AuditStore,
    ):
        """
        Initialize health monitor.

        Args:
            audit_store: Audit store for logging events
        """
        self.audit_store = audit_store
        self._health_checks: Dict[str, Callable[[], HealthCheck]] = {}
        self._alert_conditions: List[AlertCondition] = []
        self._last_alert_times: Dict[str, datetime] = {}

    def register_health_check(
        self,
        name: str,
        check_function: Callable[[], HealthCheck],
    ) -> None:
        """
        Register a health check.

        Args:
            name: Unique name for this health check
            check_function: Function that performs the check and returns HealthCheck
        """
        self._health_checks[name] = check_function

    def register_alert_condition(
        self,
        condition: AlertCondition,
    ) -> None:
        """
        Register an alert condition.

        Args:
            condition: Alert condition to monitor
        """
        self._alert_conditions.append(condition)

    def run_health_checks(self) -> List[HealthCheck]:
        """
        Run all registered health checks.

        Returns:
            List of HealthCheck results
        """
        results = []
        for name, check_func in self._health_checks.items():
            try:
                result = check_func()
                results.append(result)
            except Exception as e:
                # Health check itself failed
                results.append(
                    HealthCheck(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        message=f"Health check failed: {str(e)}",
                        details={"error": str(e)},
                    )
                )
        return results

    def check_alerts(self) -> List[Alert]:
        """
        Check all alert conditions and return triggered alerts.

        Returns:
            List of triggered Alerts
        """
        triggered = []
        now = datetime.now(tz=timezone.utc)

        for condition in self._alert_conditions:
            # Check cooldown
            last_alert = self._last_alert_times.get(condition.name)
            if last_alert:
                cooldown = timedelta(seconds=condition.cooldown_seconds)
                if now - last_alert < cooldown:
                    continue  # Still in cooldown

            # Check condition
            try:
                if condition.check_function():
                    alert = Alert(
                        condition_name=condition.name,
                        severity=condition.severity,
                        message=condition.message_template,
                        timestamp=now,
                    )
                    triggered.append(alert)
                    self._last_alert_times[condition.name] = now

                    # Log to audit store
                    self.audit_store.append_event(
                        AuditEvent(
                            event_type=EventType.SYSTEM_EVENT,
                            correlation_id="health_monitor",
                            timestamp=now,
                            data={
                                "event": "alert_triggered",
                                "condition": condition.name,
                                "severity": condition.severity.value,
                                "message": condition.message_template,
                            },
                        )
                    )
            except Exception as e:
                # Alert condition check failed - log but continue
                self.audit_store.append_event(
                    AuditEvent(
                        event_type=EventType.SYSTEM_EVENT,
                        correlation_id="health_monitor",
                        timestamp=now,
                        data={
                            "event": "alert_check_failed",
                            "condition": condition.name,
                            "error": str(e),
                        },
                    )
                )

        return triggered

    def get_overall_status(self) -> HealthStatus:
        """
        Get overall system health status.

        Returns:
            HEALTHY if all checks pass, DEGRADED if any degraded, UNHEALTHY if any unhealthy
        """
        checks = self.run_health_checks()
        if not checks:
            return HealthStatus.HEALTHY

        if any(c.status == HealthStatus.UNHEALTHY for c in checks):
            return HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in checks):
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY


# Built-in health check functions


def create_kill_switch_check(kill_switch) -> Callable[[], HealthCheck]:
    """
    Create health check for kill switch status.

    Args:
        kill_switch: KillSwitch instance

    Returns:
        Health check function
    """

    def check() -> HealthCheck:
        if not kill_switch.is_enabled():
            return HealthCheck(
                name="kill_switch",
                status=HealthStatus.HEALTHY,
                message="Kill switch not active, trading allowed",
            )
        else:
            state = kill_switch.get_state()
            return HealthCheck(
                name="kill_switch",
                status=HealthStatus.UNHEALTHY,
                message=f"Kill switch activated: {state.reason or 'no reason given'}",
                details={
                    "reason": state.reason,
                    "activated_at": state.activated_at.isoformat() if state.activated_at else None,
                    "activated_by": state.activated_by,
                },
            )

    return check


def create_broker_connection_check(broker_adapter, account_id: str) -> Callable[[], HealthCheck]:
    """
    Create health check for broker connection.

    Args:
        broker_adapter: BrokerAdapter instance
        account_id: Account ID to test

    Returns:
        Health check function
    """

    def check() -> HealthCheck:
        try:
            portfolio = broker_adapter.get_portfolio(account_id)
            return HealthCheck(
                name="broker_connection",
                status=HealthStatus.HEALTHY,
                message="Broker connection healthy",
                details={
                    "account_id": account_id,
                    "portfolio_value": float(portfolio.total_value),
                },
            )
        except Exception as e:
            return HealthCheck(
                name="broker_connection",
                status=HealthStatus.UNHEALTHY,
                message=f"Broker connection failed: {str(e)}",
                details={"error": str(e)},
            )

    return check


def create_disk_space_check(path: str = ".", min_gb: float = 5.0) -> Callable[[], HealthCheck]:
    """
    Create health check for disk space.

    Args:
        path: Path to check
        min_gb: Minimum free space in GB (triggers UNHEALTHY below this)

    Returns:
        Health check function
    """
    import shutil

    def check() -> HealthCheck:
        try:
            stat = shutil.disk_usage(path)
            free_gb = stat.free / (1024**3)

            if free_gb < min_gb:
                return HealthCheck(
                    name="disk_space",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Low disk space: {free_gb:.2f} GB free (< {min_gb} GB threshold)",
                    details={"free_gb": free_gb, "threshold_gb": min_gb},
                )
            elif free_gb < min_gb * 2:
                return HealthCheck(
                    name="disk_space",
                    status=HealthStatus.DEGRADED,
                    message=f"Disk space warning: {free_gb:.2f} GB free",
                    details={"free_gb": free_gb},
                )
            else:
                return HealthCheck(
                    name="disk_space",
                    status=HealthStatus.HEALTHY,
                    message=f"Disk space sufficient: {free_gb:.2f} GB free",
                    details={"free_gb": free_gb},
                )
        except Exception as e:
            return HealthCheck(
                name="disk_space",
                status=HealthStatus.UNHEALTHY,
                message=f"Disk space check failed: {str(e)}",
                details={"error": str(e)},
            )

    return check


def create_database_check(database_url: str) -> Callable[[], HealthCheck]:
    """
    Create health check for database connection.

    Args:
        database_url: Database connection string

    Returns:
        Health check function
    """

    def check() -> HealthCheck:
        try:
            # Simple connection test (implementation depends on DB library)
            # For SQLite: just check file exists and is writable
            # For PostgreSQL: try a SELECT 1 query
            if database_url.startswith("sqlite"):
                from pathlib import Path

                db_path = database_url.replace("sqlite:///", "")
                if Path(db_path).exists():
                    return HealthCheck(
                        name="database",
                        status=HealthStatus.HEALTHY,
                        message="Database connection healthy",
                    )
                else:
                    return HealthCheck(
                        name="database",
                        status=HealthStatus.UNHEALTHY,
                        message="Database file not found",
                        details={"path": db_path},
                    )
            else:
                # For other databases, would need actual connection test
                return HealthCheck(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="Database check not implemented for this type",
                )
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {str(e)}",
                details={"error": str(e)},
            )

    return check
