"""Metrics Collector for IBKR AI Broker.

This module provides Prometheus-style metrics collection for:
- Proposal count (by state, symbol)
- Risk rejection rate (by rule)
- Order latency (submission, fill)
- Broker errors
- Daily P&L

Usage:
    from packages.metrics_collector import get_metrics_collector, MetricsCollector
    
    collector = get_metrics_collector()
    collector.increment_proposal_count(symbol="AAPL", state="RISK_APPROVED")
    collector.record_risk_rejection(rule="R1")
    collector.record_order_latency("submission", 0.250)
    
    # Get Prometheus format
    metrics_text = collector.export_prometheus()
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from threading import Lock
from typing import Optional

__all__ = ["MetricsCollector", "get_metrics_collector", "set_metrics_collector"]


@dataclass
class MetricsCollector:
    """Collect and export metrics in Prometheus format."""
    
    # Counters (monotonic increasing)
    proposal_count: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))  # (symbol, state) -> count
    risk_rejection_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # rule_id -> count
    broker_error_count: int = 0
    
    # Gauges (current value)
    daily_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    
    # Histograms (latencies in seconds)
    submission_latencies: list[float] = field(default_factory=list)
    fill_latencies: list[float] = field(default_factory=list)
    
    # Lock for thread safety
    _lock: Lock = field(default_factory=Lock)
    
    # Start time for uptime
    _start_time: float = field(default_factory=time.time)
    
    def increment_proposal_count(self, symbol: str, state: str) -> None:
        """Increment proposal count for symbol and state.
        
        Args:
            symbol: Stock symbol (e.g., AAPL, TSLA)
            state: Proposal state (e.g., RISK_APPROVED, APPROVAL_GRANTED)
        """
        with self._lock:
            key = (symbol, state)
            self.proposal_count[key] += 1
    
    def record_risk_rejection(self, rule: str) -> None:
        """Record risk rejection by rule.
        
        Args:
            rule: Risk rule ID (e.g., R1, R2)
        """
        with self._lock:
            self.risk_rejection_count[rule] += 1
    
    def increment_broker_errors(self) -> None:
        """Increment broker error count."""
        with self._lock:
            self.broker_error_count += 1
    
    def set_daily_pnl(self, pnl: Decimal) -> None:
        """Set current daily P&L.
        
        Args:
            pnl: Daily P&L in USD
        """
        with self._lock:
            self.daily_pnl = pnl
    
    def record_order_latency(self, operation: str, latency_seconds: float) -> None:
        """Record order operation latency.
        
        Args:
            operation: "submission" or "fill"
            latency_seconds: Latency in seconds
        """
        with self._lock:
            if operation == "submission":
                self.submission_latencies.append(latency_seconds)
            elif operation == "fill":
                self.fill_latencies.append(latency_seconds)
    
    def reset_daily_metrics(self) -> None:
        """Reset daily metrics (call at midnight)."""
        with self._lock:
            self.daily_pnl = Decimal("0")
    
    def get_uptime_seconds(self) -> float:
        """Get uptime in seconds since collector started."""
        return time.time() - self._start_time
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format.
        
        Returns:
            Prometheus-formatted metrics string
        """
        with self._lock:
            lines = []
            
            # Metadata
            lines.append("# HELP ibkr_broker_info Broker information")
            lines.append("# TYPE ibkr_broker_info gauge")
            lines.append('ibkr_broker_info{version="1.0.0"} 1')
            lines.append("")
            
            # Uptime
            lines.append("# HELP ibkr_uptime_seconds Uptime in seconds")
            lines.append("# TYPE ibkr_uptime_seconds gauge")
            lines.append(f"ibkr_uptime_seconds {self.get_uptime_seconds():.2f}")
            lines.append("")
            
            # Proposal count by symbol and state
            lines.append("# HELP ibkr_proposal_total Total number of proposals by symbol and state")
            lines.append("# TYPE ibkr_proposal_total counter")
            for (symbol, state), count in sorted(self.proposal_count.items()):
                lines.append(f'ibkr_proposal_total{{symbol="{symbol}",state="{state}"}} {count}')
            lines.append("")
            
            # Risk rejection count by rule
            lines.append("# HELP ibkr_risk_rejection_total Total risk rejections by rule")
            lines.append("# TYPE ibkr_risk_rejection_total counter")
            for rule, count in sorted(self.risk_rejection_count.items()):
                lines.append(f'ibkr_risk_rejection_total{{rule="{rule}"}} {count}')
            lines.append("")
            
            # Broker errors
            lines.append("# HELP ibkr_broker_error_total Total broker errors")
            lines.append("# TYPE ibkr_broker_error_total counter")
            lines.append(f"ibkr_broker_error_total {self.broker_error_count}")
            lines.append("")
            
            # Daily P&L
            lines.append("# HELP ibkr_daily_pnl_usd Current daily P&L in USD")
            lines.append("# TYPE ibkr_daily_pnl_usd gauge")
            lines.append(f"ibkr_daily_pnl_usd {float(self.daily_pnl):.2f}")
            lines.append("")
            
            # Submission latency stats
            if self.submission_latencies:
                lines.append("# HELP ibkr_submission_latency_seconds Order submission latency")
                lines.append("# TYPE ibkr_submission_latency_seconds summary")
                sorted_latencies = sorted(self.submission_latencies)
                count = len(sorted_latencies)
                total = sum(sorted_latencies)
                lines.append(f"ibkr_submission_latency_seconds_count {count}")
                lines.append(f"ibkr_submission_latency_seconds_sum {total:.4f}")
                # Quantiles
                if count > 0:
                    p50_idx = int(count * 0.50)
                    p95_idx = int(count * 0.95)
                    p99_idx = int(count * 0.99)
                    lines.append(f'ibkr_submission_latency_seconds{{quantile="0.5"}} {sorted_latencies[p50_idx]:.4f}')
                    lines.append(f'ibkr_submission_latency_seconds{{quantile="0.95"}} {sorted_latencies[p95_idx]:.4f}')
                    lines.append(f'ibkr_submission_latency_seconds{{quantile="0.99"}} {sorted_latencies[p99_idx]:.4f}')
                lines.append("")
            
            # Fill latency stats
            if self.fill_latencies:
                lines.append("# HELP ibkr_fill_latency_seconds Order fill latency")
                lines.append("# TYPE ibkr_fill_latency_seconds summary")
                sorted_latencies = sorted(self.fill_latencies)
                count = len(sorted_latencies)
                total = sum(sorted_latencies)
                lines.append(f"ibkr_fill_latency_seconds_count {count}")
                lines.append(f"ibkr_fill_latency_seconds_sum {total:.4f}")
                # Quantiles
                if count > 0:
                    p50_idx = int(count * 0.50)
                    p95_idx = int(count * 0.95)
                    p99_idx = int(count * 0.99)
                    lines.append(f'ibkr_fill_latency_seconds{{quantile="0.5"}} {sorted_latencies[p50_idx]:.4f}')
                    lines.append(f'ibkr_fill_latency_seconds{{quantile="0.95"}} {sorted_latencies[p95_idx]:.4f}')
                    lines.append(f'ibkr_fill_latency_seconds{{quantile="0.99"}} {sorted_latencies[p99_idx]:.4f}')
                lines.append("")
            
            return "\n".join(lines)


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None
_collector_lock = Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance.
    
    Returns:
        Global MetricsCollector instance (creates if not exists)
    """
    global _metrics_collector
    
    if _metrics_collector is None:
        with _collector_lock:
            if _metrics_collector is None:
                _metrics_collector = MetricsCollector()
    
    return _metrics_collector


def set_metrics_collector(collector: MetricsCollector) -> None:
    """Set global metrics collector (for testing).
    
    Args:
        collector: MetricsCollector instance to use
    """
    global _metrics_collector
    
    with _collector_lock:
        _metrics_collector = collector
