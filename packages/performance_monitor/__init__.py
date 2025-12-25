"""Performance monitoring module for tracking system performance metrics.

This module provides comprehensive performance monitoring including:
- Latency tracking for critical operations
- Memory and CPU usage monitoring
- Historical performance data storage
- Performance degradation detection
- Real-time metrics collection
"""

import time
import psutil
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from threading import Lock

from packages.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class OperationMetrics:
    """Metrics for a single operation execution.
    
    Attributes:
        operation_name: Name of the operation
        latency_ms: Execution time in milliseconds
        timestamp: When operation was executed
        success: Whether operation succeeded
        error: Error message if failed
        metadata: Additional context
    """
    operation_name: str
    latency_ms: float
    timestamp: datetime
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """System-wide resource usage metrics.
    
    Attributes:
        timestamp: When metrics were collected
        cpu_percent: CPU usage percentage
        memory_percent: Memory usage percentage
        memory_mb: Memory usage in MB
        process_threads: Number of active threads
        open_files: Number of open file descriptors
    """
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    process_threads: int
    open_files: int


@dataclass
class PerformanceStats:
    """Aggregated performance statistics for an operation.
    
    Attributes:
        operation_name: Name of the operation
        count: Number of executions
        success_count: Number of successful executions
        failure_count: Number of failed executions
        avg_latency_ms: Average latency in milliseconds
        min_latency_ms: Minimum latency
        max_latency_ms: Maximum latency
        p50_latency_ms: 50th percentile (median)
        p95_latency_ms: 95th percentile
        p99_latency_ms: 99th percentile
    """
    operation_name: str
    count: int
    success_count: int
    failure_count: int
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "operation_name": self.operation_name,
            "count": self.count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_count / self.count * 100, 2) if self.count > 0 else 0,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
        }


class PerformanceMonitor:
    """Monitor and track system and operation performance.
    
    Features:
    - Automatic latency tracking for operations
    - System resource monitoring (CPU, memory)
    - Historical data with configurable retention
    - Performance statistics and percentiles
    - Degradation detection and alerting
    """
    
    def __init__(
        self,
        max_history_size: int = 10000,
        retention_hours: int = 24
    ):
        """Initialize performance monitor.
        
        Args:
            max_history_size: Maximum number of operation metrics to retain
            retention_hours: How long to retain historical data
        """
        self._lock = Lock()
        
        # Operation metrics storage (per operation name)
        self._operation_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history_size))
        
        # System metrics storage
        self._system_history: deque = deque(maxlen=1000)
        
        # Configuration
        self._max_history_size = max_history_size
        self._retention_hours = retention_hours
        
        # Performance thresholds (operation_name -> threshold_ms)
        self._latency_thresholds: Dict[str, float] = {
            "broker_connect": 5000.0,
            "broker_get_portfolio": 2000.0,
            "broker_submit_order": 3000.0,
            "simulate_order": 100.0,
            "evaluate_risk": 50.0,
            "database_query": 500.0,
        }
        
        # Current process handle for resource monitoring
        self._process = psutil.Process()
        
        logger.info("performance_monitor_initialized", 
                   max_history=max_history_size,
                   retention_hours=retention_hours)
    
    def record_operation(
        self,
        operation_name: str,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        **metadata
    ) -> None:
        """Record metrics for an operation execution.
        
        Args:
            operation_name: Name of the operation
            latency_ms: Execution time in milliseconds
            success: Whether operation succeeded
            error: Error message if failed
            **metadata: Additional context
        """
        with self._lock:
            metrics = OperationMetrics(
                operation_name=operation_name,
                latency_ms=latency_ms,
                timestamp=datetime.utcnow(),
                success=success,
                error=error,
                metadata=metadata
            )
            
            self._operation_history[operation_name].append(metrics)
            
            # Check for threshold violations
            threshold = self._latency_thresholds.get(operation_name)
            if threshold and latency_ms > threshold:
                logger.warning("operation_slow",
                             operation=operation_name,
                             latency_ms=latency_ms,
                             threshold_ms=threshold)
            
            logger.debug("operation_recorded",
                        operation=operation_name,
                        latency_ms=latency_ms,
                        success=success)
    
    def collect_system_metrics(self) -> SystemMetrics:
        """Collect current system resource metrics.
        
        Returns:
            SystemMetrics with current resource usage
        """
        try:
            cpu_percent = self._process.cpu_percent(interval=0.1)
            memory_info = self._process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            memory_percent = self._process.memory_percent()
            num_threads = self._process.num_threads()
            
            # Open files (may not be available on all platforms)
            try:
                open_files = len(self._process.open_files())
            except (psutil.AccessDenied, AttributeError):
                open_files = 0
            
            metrics = SystemMetrics(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_mb=memory_mb,
                process_threads=num_threads,
                open_files=open_files
            )
            
            with self._lock:
                self._system_history.append(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error("system_metrics_collection_failed", error=str(e))
            raise
    
    def get_operation_stats(
        self,
        operation_name: str,
        since: Optional[datetime] = None
    ) -> Optional[PerformanceStats]:
        """Get aggregated statistics for an operation.
        
        Args:
            operation_name: Name of the operation
            since: Only include metrics after this time
        
        Returns:
            PerformanceStats or None if no data
        """
        with self._lock:
            if operation_name not in self._operation_history:
                return None
            
            history = self._operation_history[operation_name]
            
            # Filter by time if specified
            if since:
                metrics_list = [m for m in history if m.timestamp >= since]
            else:
                metrics_list = list(history)
            
            if not metrics_list:
                return None
            
            # Calculate statistics
            latencies = [m.latency_ms for m in metrics_list]
            latencies.sort()
            
            count = len(metrics_list)
            success_count = sum(1 for m in metrics_list if m.success)
            failure_count = count - success_count
            
            avg_latency = sum(latencies) / count
            min_latency = latencies[0]
            max_latency = latencies[-1]
            
            # Calculate percentiles
            p50_idx = int(count * 0.50)
            p95_idx = int(count * 0.95)
            p99_idx = int(count * 0.99)
            
            p50_latency = latencies[p50_idx]
            p95_latency = latencies[min(p95_idx, count - 1)]
            p99_latency = latencies[min(p99_idx, count - 1)]
            
            return PerformanceStats(
                operation_name=operation_name,
                count=count,
                success_count=success_count,
                failure_count=failure_count,
                avg_latency_ms=avg_latency,
                min_latency_ms=min_latency,
                max_latency_ms=max_latency,
                p50_latency_ms=p50_latency,
                p95_latency_ms=p95_latency,
                p99_latency_ms=p99_latency
            )
    
    def get_all_operation_stats(
        self,
        since: Optional[datetime] = None
    ) -> List[PerformanceStats]:
        """Get statistics for all tracked operations.
        
        Args:
            since: Only include metrics after this time
        
        Returns:
            List of PerformanceStats
        """
        with self._lock:
            operation_names = list(self._operation_history.keys())
        
        stats = []
        for name in operation_names:
            op_stats = self.get_operation_stats(name, since)
            if op_stats:
                stats.append(op_stats)
        
        return stats
    
    def get_system_metrics_history(
        self,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[SystemMetrics]:
        """Get historical system metrics.
        
        Args:
            since: Only include metrics after this time
            limit: Maximum number of metrics to return
        
        Returns:
            List of SystemMetrics
        """
        with self._lock:
            history = list(self._system_history)
        
        # Filter by time if specified
        if since:
            history = [m for m in history if m.timestamp >= since]
        
        # Limit results
        if len(history) > limit:
            history = history[-limit:]
        
        return history
    
    def get_current_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics summary.
        
        Returns:
            Dictionary with current metrics
        """
        metrics = self.collect_system_metrics()
        
        return {
            "timestamp": metrics.timestamp.isoformat(),
            "cpu_percent": round(metrics.cpu_percent, 2),
            "memory_percent": round(metrics.memory_percent, 2),
            "memory_mb": round(metrics.memory_mb, 2),
            "process_threads": metrics.process_threads,
            "open_files": metrics.open_files
        }
    
    def check_degradation(
        self,
        operation_name: str,
        window_minutes: int = 15
    ) -> Dict[str, Any]:
        """Check if operation performance has degraded recently.
        
        Args:
            operation_name: Name of the operation to check
            window_minutes: Time window for comparison
        
        Returns:
            Dictionary with degradation analysis
        """
        since = datetime.utcnow() - timedelta(minutes=window_minutes)
        
        # Get recent stats
        recent_stats = self.get_operation_stats(operation_name, since=since)
        if not recent_stats:
            return {
                "operation": operation_name,
                "degraded": False,
                "reason": "No recent data"
            }
        
        # Compare to threshold
        threshold = self._latency_thresholds.get(operation_name)
        if not threshold:
            return {
                "operation": operation_name,
                "degraded": False,
                "reason": "No threshold configured"
            }
        
        # Check if p95 latency exceeds threshold
        degraded = recent_stats.p95_latency_ms > threshold
        
        return {
            "operation": operation_name,
            "degraded": degraded,
            "p95_latency_ms": round(recent_stats.p95_latency_ms, 2),
            "threshold_ms": threshold,
            "ratio": round(recent_stats.p95_latency_ms / threshold, 2),
            "sample_count": recent_stats.count
        }
    
    def set_latency_threshold(
        self,
        operation_name: str,
        threshold_ms: float
    ) -> None:
        """Set latency threshold for an operation.
        
        Args:
            operation_name: Name of the operation
            threshold_ms: Threshold in milliseconds
        """
        with self._lock:
            self._latency_thresholds[operation_name] = threshold_ms
        
        logger.info("latency_threshold_set",
                   operation=operation_name,
                   threshold_ms=threshold_ms)
    
    def cleanup_old_data(self) -> int:
        """Remove data older than retention period.
        
        Returns:
            Number of metrics removed
        """
        cutoff = datetime.utcnow() - timedelta(hours=self._retention_hours)
        removed = 0
        
        with self._lock:
            # Clean operation history
            for operation_name in list(self._operation_history.keys()):
                history = self._operation_history[operation_name]
                original_len = len(history)
                
                # Filter out old metrics
                filtered = deque(
                    (m for m in history if m.timestamp >= cutoff),
                    maxlen=self._max_history_size
                )
                
                self._operation_history[operation_name] = filtered
                removed += original_len - len(filtered)
            
            # Clean system history
            original_sys_len = len(self._system_history)
            self._system_history = deque(
                (m for m in self._system_history if m.timestamp >= cutoff),
                maxlen=1000
            )
            removed += original_sys_len - len(self._system_history)
        
        if removed > 0:
            logger.info("old_metrics_cleaned", removed=removed)
        
        return removed


# Singleton instance
_performance_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor() -> PerformanceMonitor:
    """Get singleton performance monitor instance."""
    global _performance_monitor
    
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    
    return _performance_monitor


# Timing decorator
def track_performance(operation_name: str):
    """Decorator to automatically track operation performance.
    
    Usage:
        @track_performance("my_operation")
        def my_function():
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            error = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                monitor = get_performance_monitor()
                monitor.record_operation(
                    operation_name=operation_name,
                    latency_ms=latency_ms,
                    success=success,
                    error=error
                )
        
        return wrapper
    return decorator
