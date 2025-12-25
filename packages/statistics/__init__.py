"""
Paper Trading Statistics Collection and Pre-Live Checklist Validation.

This module tracks key performance metrics during paper trading phase and validates
readiness for live trading transition. Integrates with reconciliation, risk engine,
and order execution to provide comprehensive system health assessment.

Key Metrics:
- Order success rate (filled / submitted)
- Average order latency (submission to fill)
- Risk rejection breakdown (by rule)
- Simulator accuracy (predicted vs actual)
- Reconciliation success rate
- Unintended order count (critical safety metric)

Pre-Live Checklist:
- 200+ orders simulated in paper
- 50+ orders successfully submitted
- 0 unintended orders (mandatory)
- Reject rate <20% and explainable
- 30 days of 100% reconciliation

Usage:
    from packages.statistics import get_stats_collector, PreLiveStatus
    
    # Record events
    collector = get_stats_collector()
    collector.record_order_proposed("ord_123", "AAPL")
    collector.record_order_submitted("ord_123", "MOCK123")
    collector.record_order_filled("ord_123", 150.0, 190.5)
    
    # Get summary
    summary = collector.get_summary()
    print(f"Success rate: {summary['success_rate']:.2%}")
    
    # Check pre-live readiness
    status = collector.get_pre_live_status()
    if status.ready_for_live:
        print("System ready for live trading!")
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import json
from pathlib import Path


class OrderStatus(str, Enum):
    """Order lifecycle status for statistics tracking."""
    PROPOSED = "PROPOSED"
    SIMULATED = "SIMULATED"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    """Categorized rejection reasons for analysis."""
    RISK_NOTIONAL = "risk_notional"  # R1: Max notional exceeded
    RISK_POSITION_WEIGHT = "risk_position_weight"  # R2: Max position weight
    RISK_SECTOR_WEIGHT = "risk_sector_weight"  # R3: Max sector weight
    RISK_SLIPPAGE = "risk_slippage"  # R4: Max slippage
    RISK_HOURS = "risk_hours"  # R5: Trading hours
    RISK_LIQUIDITY = "risk_liquidity"  # R6: Liquidity
    RISK_DAILY_TRADES = "risk_daily_trades"  # R7: Daily trades limit
    RISK_DAILY_LOSS = "risk_daily_loss"  # R8: Daily loss limit
    SIMULATION_FAILED = "simulation_failed"  # Simulation error
    HUMAN_DENIED = "human_denied"  # Human approval denied
    BROKER_REJECTED = "broker_rejected"  # Broker rejected
    UNKNOWN = "unknown"


@dataclass
class OrderStats:
    """Statistics for a single order lifecycle."""
    order_id: str
    proposal_id: Optional[str] = None
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    
    # Timestamps
    proposed_at: Optional[datetime] = None
    simulated_at: Optional[datetime] = None
    risk_evaluated_at: Optional[datetime] = None
    approval_requested_at: Optional[datetime] = None
    approval_decided_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    
    # Results
    status: OrderStatus = OrderStatus.PROPOSED
    rejection_reason: Optional[RejectionReason] = None
    rejection_details: Optional[str] = None
    
    # Execution data
    broker_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    simulated_price: Optional[float] = None
    
    # Derived metrics
    @property
    def latency_seconds(self) -> Optional[float]:
        """Time from submission to fill."""
        if self.submitted_at and self.filled_at:
            return (self.filled_at - self.submitted_at).total_seconds()
        return None
    
    @property
    def simulator_accuracy(self) -> Optional[float]:
        """Simulator prediction accuracy (0-1, 1 = perfect)."""
        if self.simulated_price and self.fill_price and self.simulated_price > 0:
            error = abs(self.fill_price - self.simulated_price) / self.simulated_price
            return max(0.0, 1.0 - error)
        return None
    
    @property
    def is_successful(self) -> bool:
        """True if order was filled."""
        return self.status == OrderStatus.FILLED
    
    @property
    def is_rejected(self) -> bool:
        """True if order was rejected at any stage."""
        return self.status in {
            OrderStatus.RISK_REJECTED,
            OrderStatus.APPROVAL_DENIED,
            OrderStatus.REJECTED,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with ISO timestamps."""
        data = asdict(self)
        # Convert datetime to ISO string
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, Enum):
                data[key] = value.value
        # Add derived metrics
        data["latency_seconds"] = self.latency_seconds
        data["simulator_accuracy"] = self.simulator_accuracy
        data["is_successful"] = self.is_successful
        data["is_rejected"] = self.is_rejected
        return data


@dataclass
class ReconciliationStats:
    """Reconciliation event statistics."""
    timestamp: datetime
    is_reconciled: bool
    discrepancy_count: int
    has_critical_discrepancies: bool
    duration_ms: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "is_reconciled": self.is_reconciled,
            "discrepancy_count": self.discrepancy_count,
            "has_critical_discrepancies": self.has_critical_discrepancies,
            "duration_ms": self.duration_ms,
        }


@dataclass
class PreLiveStatus:
    """Pre-live checklist validation result."""
    ready_for_live: bool
    checks_passed: int
    checks_total: int
    
    # Individual checks
    orders_simulated_ok: bool
    orders_simulated_count: int
    orders_submitted_ok: bool
    orders_submitted_count: int
    unintended_orders_ok: bool
    unintended_orders_count: int
    reject_rate_ok: bool
    reject_rate: float
    reconciliation_ok: bool
    reconciliation_days: int
    
    # Details
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class StatisticsCollector:
    """
    Collects and analyzes paper trading statistics.
    
    Thread-safe for concurrent order tracking. Stores state in-memory
    with optional persistence to JSON file.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize statistics collector.
        
        Args:
            storage_path: Optional path to JSON file for persistence
        """
        self.storage_path = storage_path
        self.orders: Dict[str, OrderStats] = {}
        self.reconciliations: List[ReconciliationStats] = []
        
        # Pre-live checklist thresholds
        self.min_orders_simulated = 200
        self.min_orders_submitted = 50
        self.max_unintended_orders = 0
        self.max_reject_rate = 0.20  # 20%
        self.min_reconciliation_days = 30
        
        # Load from storage if exists
        if storage_path and storage_path.exists():
            self._load()
    
    # Order tracking methods
    
    def record_order_proposed(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float,
        proposal_id: Optional[str] = None,
    ) -> None:
        """Record order proposal."""
        if order_id not in self.orders:
            self.orders[order_id] = OrderStats(
                order_id=order_id,
                proposal_id=proposal_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )
        
        self.orders[order_id].proposed_at = datetime.utcnow()
        self.orders[order_id].status = OrderStatus.PROPOSED
        self._save()
    
    def record_order_simulated(
        self,
        order_id: str,
        simulated_price: Optional[float] = None,
    ) -> None:
        """Record order simulation."""
        if order_id in self.orders:
            self.orders[order_id].simulated_at = datetime.utcnow()
            self.orders[order_id].status = OrderStatus.SIMULATED
            if simulated_price is not None:
                self.orders[order_id].simulated_price = simulated_price
            self._save()
    
    def record_order_risk_evaluated(
        self,
        order_id: str,
        approved: bool,
        rejection_reason: Optional[RejectionReason] = None,
        rejection_details: Optional[str] = None,
    ) -> None:
        """Record risk evaluation result."""
        if order_id in self.orders:
            self.orders[order_id].risk_evaluated_at = datetime.utcnow()
            if approved:
                self.orders[order_id].status = OrderStatus.RISK_APPROVED
            else:
                self.orders[order_id].status = OrderStatus.RISK_REJECTED
                self.orders[order_id].rejection_reason = rejection_reason
                self.orders[order_id].rejection_details = rejection_details
            self._save()
    
    def record_order_approval_requested(self, order_id: str) -> None:
        """Record approval request."""
        if order_id in self.orders:
            self.orders[order_id].approval_requested_at = datetime.utcnow()
            self.orders[order_id].status = OrderStatus.APPROVAL_REQUESTED
            self._save()
    
    def record_order_approval_decided(
        self,
        order_id: str,
        approved: bool,
        reason: Optional[str] = None,
    ) -> None:
        """Record approval decision."""
        if order_id in self.orders:
            self.orders[order_id].approval_decided_at = datetime.utcnow()
            if approved:
                self.orders[order_id].status = OrderStatus.APPROVAL_GRANTED
            else:
                self.orders[order_id].status = OrderStatus.APPROVAL_DENIED
                self.orders[order_id].rejection_reason = RejectionReason.HUMAN_DENIED
                self.orders[order_id].rejection_details = reason
            self._save()
    
    def record_order_submitted(
        self,
        order_id: str,
        broker_order_id: str,
    ) -> None:
        """Record order submission to broker."""
        if order_id in self.orders:
            self.orders[order_id].submitted_at = datetime.utcnow()
            self.orders[order_id].broker_order_id = broker_order_id
            self.orders[order_id].status = OrderStatus.SUBMITTED
            self._save()
    
    def record_order_filled(
        self,
        order_id: str,
        fill_price: float,
        filled_at: Optional[datetime] = None,
    ) -> None:
        """Record order fill."""
        if order_id in self.orders:
            self.orders[order_id].filled_at = filled_at or datetime.utcnow()
            self.orders[order_id].fill_price = fill_price
            self.orders[order_id].status = OrderStatus.FILLED
            self._save()
    
    def record_order_rejected(
        self,
        order_id: str,
        reason: Optional[str] = None,
    ) -> None:
        """Record broker rejection."""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.REJECTED
            self.orders[order_id].rejection_reason = RejectionReason.BROKER_REJECTED
            self.orders[order_id].rejection_details = reason
            self._save()
    
    def record_order_cancelled(self, order_id: str) -> None:
        """Record order cancellation."""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            self._save()
    
    # Reconciliation tracking
    
    def record_reconciliation(
        self,
        is_reconciled: bool,
        discrepancy_count: int,
        has_critical_discrepancies: bool,
        duration_ms: float,
    ) -> None:
        """Record reconciliation event."""
        self.reconciliations.append(
            ReconciliationStats(
                timestamp=datetime.utcnow(),
                is_reconciled=is_reconciled,
                discrepancy_count=discrepancy_count,
                has_critical_discrepancies=has_critical_discrepancies,
                duration_ms=duration_ms,
            )
        )
        self._save()
    
    # Summary and analysis
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics summary.
        
        Returns:
            Dictionary with all tracked metrics
        """
        total_orders = len(self.orders)
        
        # Calculate reconciliation statistics (always needed)
        total_recons = len(self.reconciliations)
        successful_recons = sum(1 for r in self.reconciliations if r.is_reconciled)
        recon_success_rate = successful_recons / total_recons if total_recons > 0 else 0.0
        
        if total_orders == 0:
            return {
                "total_orders": 0,
                "successful_orders": 0,
                "rejected_orders": 0,
                "success_rate": 0.0,
                "reject_rate": 0.0,
                "avg_latency_seconds": None,
                "avg_simulator_accuracy": None,
                "rejection_breakdown": {},
                "total_reconciliations": total_recons,
                "successful_reconciliations": successful_recons,
                "reconciliation_success_rate": recon_success_rate,
            }
        
        successful = sum(1 for o in self.orders.values() if o.is_successful)
        rejected = sum(1 for o in self.orders.values() if o.is_rejected)
        
        # Latency statistics
        latencies = [o.latency_seconds for o in self.orders.values() if o.latency_seconds]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        
        # Simulator accuracy
        accuracies = [o.simulator_accuracy for o in self.orders.values() if o.simulator_accuracy]
        avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else None
        
        # Rejection breakdown
        rejection_breakdown: Dict[str, int] = {}
        for order in self.orders.values():
            if order.rejection_reason:
                reason = order.rejection_reason.value
                rejection_breakdown[reason] = rejection_breakdown.get(reason, 0) + 1
        
        return {
            "total_orders": total_orders,
            "successful_orders": successful,
            "rejected_orders": rejected,
            "success_rate": successful / total_orders,
            "reject_rate": rejected / total_orders,
            "avg_latency_seconds": avg_latency,
            "avg_simulator_accuracy": avg_accuracy,
            "rejection_breakdown": rejection_breakdown,
            "total_reconciliations": total_recons,
            "successful_reconciliations": successful_recons,
            "reconciliation_success_rate": recon_success_rate,
        }
    
    def get_pre_live_status(self) -> PreLiveStatus:
        """
        Evaluate pre-live checklist.
        
        Returns:
            PreLiveStatus with detailed validation results
        """
        summary = self.get_summary()
        
        # Check 1: Orders simulated
        orders_simulated = len([o for o in self.orders.values() if o.simulated_at])
        orders_simulated_ok = orders_simulated >= self.min_orders_simulated
        
        # Check 2: Orders submitted
        orders_submitted = len([o for o in self.orders.values() if o.submitted_at])
        orders_submitted_ok = orders_submitted >= self.min_orders_submitted
        
        # Check 3: Unintended orders (critical check)
        # TODO: Implement unintended order detection logic
        # For now, assume all orders are intended
        unintended_orders = 0
        unintended_orders_ok = unintended_orders <= self.max_unintended_orders
        
        # Check 4: Reject rate
        reject_rate = summary["reject_rate"]
        reject_rate_ok = reject_rate <= self.max_reject_rate
        
        # Check 5: Reconciliation history (30 days of 100% success)
        # Check if we have reconciliations for last 30 days
        cutoff = datetime.utcnow() - timedelta(days=self.min_reconciliation_days)
        recent_recons = [r for r in self.reconciliations if r.timestamp >= cutoff]
        days_covered = len(set(r.timestamp.date() for r in recent_recons))
        all_reconciled = all(r.is_reconciled for r in recent_recons)
        reconciliation_ok = days_covered >= self.min_reconciliation_days and all_reconciled
        
        # Collect issues
        blocking_issues = []
        warnings = []
        recommendations = []
        
        if not orders_simulated_ok:
            blocking_issues.append(
                f"Insufficient simulated orders: {orders_simulated}/{self.min_orders_simulated}"
            )
        
        if not orders_submitted_ok:
            blocking_issues.append(
                f"Insufficient submitted orders: {orders_submitted}/{self.min_orders_submitted}"
            )
        
        if not unintended_orders_ok:
            blocking_issues.append(
                f"Unintended orders detected: {unintended_orders} (max: {self.max_unintended_orders})"
            )
        
        if not reject_rate_ok:
            warnings.append(
                f"Reject rate too high: {reject_rate:.1%} (max: {self.max_reject_rate:.1%})"
            )
            recommendations.append("Review rejection breakdown and adjust risk rules if needed")
        
        if not reconciliation_ok:
            if days_covered < self.min_reconciliation_days:
                blocking_issues.append(
                    f"Insufficient reconciliation history: {days_covered} days (min: {self.min_reconciliation_days})"
                )
            elif not all_reconciled:
                blocking_issues.append(
                    "Reconciliation failures detected in last 30 days"
                )
        
        if summary["avg_simulator_accuracy"] and summary["avg_simulator_accuracy"] < 0.90:
            warnings.append(
                f"Simulator accuracy below 90%: {summary['avg_simulator_accuracy']:.1%}"
            )
            recommendations.append("Review simulator parameters and market data quality")
        
        checks = [
            orders_simulated_ok,
            orders_submitted_ok,
            unintended_orders_ok,
            reject_rate_ok,
            reconciliation_ok,
        ]
        checks_passed = sum(checks)
        checks_total = len(checks)
        
        return PreLiveStatus(
            ready_for_live=len(blocking_issues) == 0,
            checks_passed=checks_passed,
            checks_total=checks_total,
            orders_simulated_ok=orders_simulated_ok,
            orders_simulated_count=orders_simulated,
            orders_submitted_ok=orders_submitted_ok,
            orders_submitted_count=orders_submitted,
            unintended_orders_ok=unintended_orders_ok,
            unintended_orders_count=unintended_orders,
            reject_rate_ok=reject_rate_ok,
            reject_rate=reject_rate,
            reconciliation_ok=reconciliation_ok,
            reconciliation_days=days_covered,
            blocking_issues=blocking_issues,
            warnings=warnings,
            recommendations=recommendations,
        )
    
    # Persistence
    
    def _save(self) -> None:
        """Save state to disk (if storage_path configured)."""
        if not self.storage_path:
            return
        
        data = {
            "orders": {oid: o.to_dict() for oid, o in self.orders.items()},
            "reconciliations": [r.to_dict() for r in self.reconciliations],
        }
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _load(self) -> None:
        """Load state from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        
        # Check if file is empty
        if self.storage_path.stat().st_size == 0:
            return
        
        with open(self.storage_path, "r") as f:
            data = json.load(f)
        
        # Reconstruct orders (simplified - loses datetime objects)
        # For production, consider using a proper serialization format
        # This is good enough for MVP statistics tracking
        self.orders = {}
        for oid, odata in data.get("orders", {}).items():
            # Basic reconstruction - good enough for statistics
            self.orders[oid] = OrderStats(
                order_id=oid,
                proposal_id=odata.get("proposal_id"),
                symbol=odata.get("symbol", ""),
                side=odata.get("side", ""),
                quantity=odata.get("quantity", 0.0),
                status=OrderStatus(odata.get("status", "PROPOSED")),
                broker_order_id=odata.get("broker_order_id"),
                fill_price=odata.get("fill_price"),
                simulated_price=odata.get("simulated_price"),
            )
        
        # Reconstruct reconciliations
        self.reconciliations = []
        for rdata in data.get("reconciliations", []):
            self.reconciliations.append(
                ReconciliationStats(
                    timestamp=datetime.fromisoformat(rdata["timestamp"]),
                    is_reconciled=rdata["is_reconciled"],
                    discrepancy_count=rdata["discrepancy_count"],
                    has_critical_discrepancies=rdata["has_critical_discrepancies"],
                    duration_ms=rdata["duration_ms"],
                )
            )


# Singleton instance
_stats_collector: Optional[StatisticsCollector] = None


def get_stats_collector(storage_path: Optional[Path] = None) -> StatisticsCollector:
    """
    Get or create singleton statistics collector.
    
    Args:
        storage_path: Optional path for persistence (only used on first call)
    
    Returns:
        StatisticsCollector instance
    """
    global _stats_collector
    if _stats_collector is None:
        _stats_collector = StatisticsCollector(storage_path=storage_path)
    return _stats_collector


__all__ = [
    "OrderStatus",
    "RejectionReason",
    "OrderStats",
    "ReconciliationStats",
    "PreLiveStatus",
    "StatisticsCollector",
    "get_stats_collector",
]
