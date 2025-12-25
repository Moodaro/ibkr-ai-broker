"""
Reconciliation module for comparing internal state with broker state.

This module provides functionality to detect discrepancies between:
- Internal order tracking vs broker open orders
- Internal position tracking vs broker positions
- Internal cash balance vs broker cash

Critical for ensuring system integrity before live trading.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class DiscrepancyType(Enum):
    """Type of reconciliation discrepancy."""
    MISSING_ORDER = "missing_order"  # Order in system but not in broker
    UNKNOWN_ORDER = "unknown_order"  # Order in broker but not in system
    POSITION_MISMATCH = "position_mismatch"  # Position quantity differs
    CASH_MISMATCH = "cash_mismatch"  # Cash balance differs
    MISSING_POSITION = "missing_position"  # Position in system but not in broker
    UNKNOWN_POSITION = "unknown_position"  # Position in broker but not in system


class DiscrepancySeverity(Enum):
    """Severity level of discrepancy."""
    LOW = "low"  # Small difference, likely timing/rounding
    MEDIUM = "medium"  # Significant difference requiring attention
    HIGH = "high"  # Critical difference requiring immediate action
    CRITICAL = "critical"  # System-broker state completely out of sync


@dataclass
class Discrepancy:
    """Represents a single reconciliation discrepancy."""
    type: DiscrepancyType
    severity: DiscrepancySeverity
    description: str
    internal_value: Optional[any] = None
    broker_value: Optional[any] = None
    difference: Optional[float] = None
    symbol: Optional[str] = None
    order_id: Optional[str] = None
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        """Convert to dictionary for API/logging."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "description": self.description,
            "internal_value": str(self.internal_value) if self.internal_value is not None else None,
            "broker_value": str(self.broker_value) if self.broker_value is not None else None,
            "difference": self.difference,
            "symbol": self.symbol,
            "order_id": self.order_id,
            "detected_at": self.detected_at.isoformat()
        }


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""
    timestamp: datetime
    is_reconciled: bool
    discrepancies: List[Discrepancy]
    internal_orders_count: int
    broker_orders_count: int
    internal_positions_count: int
    broker_positions_count: int
    internal_cash: float
    broker_cash: float
    duration_ms: float

    @property
    def has_critical_discrepancies(self) -> bool:
        """Check if any critical discrepancies exist."""
        return any(d.severity == DiscrepancySeverity.CRITICAL for d in self.discrepancies)

    @property
    def discrepancy_count(self) -> int:
        """Total number of discrepancies."""
        return len(self.discrepancies)

    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "is_reconciled": self.is_reconciled,
            "discrepancy_count": self.discrepancy_count,
            "has_critical_discrepancies": self.has_critical_discrepancies,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "summary": {
                "internal_orders_count": self.internal_orders_count,
                "broker_orders_count": self.broker_orders_count,
                "internal_positions_count": self.internal_positions_count,
                "broker_positions_count": self.broker_positions_count,
                "internal_cash": self.internal_cash,
                "broker_cash": self.broker_cash
            },
            "duration_ms": self.duration_ms
        }


class Reconciler:
    """
    Reconciliation engine for comparing internal state with broker state.
    
    Performs checks on:
    - Open orders
    - Positions
    - Cash balance
    
    Generates discrepancy reports with severity levels.
    """

    def __init__(
        self,
        broker_adapter,
        cash_tolerance: float = 0.01,  # $0.01 tolerance
        position_tolerance: int = 0,  # 0 shares tolerance (exact match)
    ):
        """
        Initialize reconciler.
        
        Args:
            broker_adapter: Broker adapter instance for fetching broker state
            cash_tolerance: Maximum acceptable cash difference (USD)
            position_tolerance: Maximum acceptable position quantity difference
        """
        self.broker_adapter = broker_adapter
        self.cash_tolerance = cash_tolerance
        self.position_tolerance = position_tolerance

    def reconcile(
        self,
        account_id: str,
        internal_orders: List[Dict],
        internal_positions: Dict[str, int],
        internal_cash: float
    ) -> ReconciliationResult:
        """
        Perform full reconciliation check.
        
        Args:
            account_id: Broker account ID
            internal_orders: List of internal open orders (dicts with keys: order_id, symbol, quantity, side)
            internal_positions: Internal positions {symbol: quantity}
            internal_cash: Internal cash balance
            
        Returns:
            ReconciliationResult with discrepancies
        """
        start_time = datetime.utcnow()
        discrepancies = []

        # Fetch broker state
        try:
            broker_orders = self.broker_adapter.get_open_orders(account_id)
            broker_positions_list = self.broker_adapter.get_positions(account_id)
            broker_cash = self.broker_adapter.get_cash(account_id)
        except Exception as e:
            logger.error(f"Failed to fetch broker state: {e}")
            # Critical discrepancy if cannot fetch broker state
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.CASH_MISMATCH,
                severity=DiscrepancySeverity.CRITICAL,
                description=f"Cannot fetch broker state: {e}",
                internal_value=None,
                broker_value=None
            ))
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            return ReconciliationResult(
                timestamp=start_time,
                is_reconciled=False,
                discrepancies=discrepancies,
                internal_orders_count=len(internal_orders),
                broker_orders_count=0,
                internal_positions_count=len(internal_positions),
                broker_positions_count=0,
                internal_cash=internal_cash,
                broker_cash=0.0,
                duration_ms=duration_ms
            )

        # Convert broker positions list to dict
        broker_positions = {pos["symbol"]: pos["quantity"] for pos in broker_positions_list}

        # Check orders
        discrepancies.extend(self._reconcile_orders(internal_orders, broker_orders))

        # Check positions
        discrepancies.extend(self._reconcile_positions(internal_positions, broker_positions))

        # Check cash
        cash_discrepancy = self._reconcile_cash(internal_cash, broker_cash)
        if cash_discrepancy:
            discrepancies.append(cash_discrepancy)

        duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        is_reconciled = len(discrepancies) == 0

        return ReconciliationResult(
            timestamp=start_time,
            is_reconciled=is_reconciled,
            discrepancies=discrepancies,
            internal_orders_count=len(internal_orders),
            broker_orders_count=len(broker_orders),
            internal_positions_count=len(internal_positions),
            broker_positions_count=len(broker_positions),
            internal_cash=internal_cash,
            broker_cash=broker_cash,
            duration_ms=duration_ms
        )

    def _reconcile_orders(
        self,
        internal_orders: List[Dict],
        broker_orders: List[Dict]
    ) -> List[Discrepancy]:
        """Compare internal orders with broker orders."""
        discrepancies = []

        # Create lookup sets
        internal_order_ids = {order["order_id"] for order in internal_orders}
        broker_order_ids = {order["order_id"] for order in broker_orders}

        # Missing orders (in system but not in broker)
        for order_id in internal_order_ids - broker_order_ids:
            order = next(o for o in internal_orders if o["order_id"] == order_id)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.MISSING_ORDER,
                severity=DiscrepancySeverity.HIGH,
                description=f"Order {order_id} in system but not in broker",
                internal_value=order,
                broker_value=None,
                symbol=order.get("symbol"),
                order_id=order_id
            ))

        # Unknown orders (in broker but not in system)
        for order_id in broker_order_ids - internal_order_ids:
            order = next(o for o in broker_orders if o["order_id"] == order_id)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.UNKNOWN_ORDER,
                severity=DiscrepancySeverity.CRITICAL,
                description=f"Order {order_id} in broker but not in system (untracked order!)",
                internal_value=None,
                broker_value=order,
                symbol=order.get("symbol"),
                order_id=order_id
            ))

        return discrepancies

    def _reconcile_positions(
        self,
        internal_positions: Dict[str, int],
        broker_positions: Dict[str, int]
    ) -> List[Discrepancy]:
        """Compare internal positions with broker positions."""
        discrepancies = []

        all_symbols = set(internal_positions.keys()) | set(broker_positions.keys())

        for symbol in all_symbols:
            internal_qty = internal_positions.get(symbol, 0)
            broker_qty = broker_positions.get(symbol, 0)
            diff = abs(internal_qty - broker_qty)

            if diff > self.position_tolerance:
                # Determine severity based on difference
                if diff > 100:
                    severity = DiscrepancySeverity.CRITICAL
                elif diff > 10:
                    severity = DiscrepancySeverity.HIGH
                elif diff > 1:
                    severity = DiscrepancySeverity.MEDIUM
                else:
                    severity = DiscrepancySeverity.LOW

                if internal_qty == 0:
                    disc_type = DiscrepancyType.UNKNOWN_POSITION
                    desc = f"Position {symbol} in broker ({broker_qty}) but not in system"
                elif broker_qty == 0:
                    disc_type = DiscrepancyType.MISSING_POSITION
                    desc = f"Position {symbol} in system ({internal_qty}) but not in broker"
                else:
                    disc_type = DiscrepancyType.POSITION_MISMATCH
                    desc = f"Position {symbol} mismatch: system={internal_qty}, broker={broker_qty}"

                discrepancies.append(Discrepancy(
                    type=disc_type,
                    severity=severity,
                    description=desc,
                    internal_value=internal_qty,
                    broker_value=broker_qty,
                    difference=float(diff),
                    symbol=symbol
                ))

        return discrepancies

    def _reconcile_cash(
        self,
        internal_cash: float,
        broker_cash: float
    ) -> Optional[Discrepancy]:
        """Compare internal cash with broker cash."""
        diff = abs(internal_cash - broker_cash)

        if diff > self.cash_tolerance:
            # Determine severity based on difference
            if diff > 10000:  # $10k
                severity = DiscrepancySeverity.CRITICAL
            elif diff > 1000:  # $1k
                severity = DiscrepancySeverity.HIGH
            elif diff > 100:  # $100
                severity = DiscrepancySeverity.MEDIUM
            else:
                severity = DiscrepancySeverity.LOW

            return Discrepancy(
                type=DiscrepancyType.CASH_MISMATCH,
                severity=severity,
                description=f"Cash mismatch: system=${internal_cash:.2f}, broker=${broker_cash:.2f} (diff=${diff:.2f})",
                internal_value=internal_cash,
                broker_value=broker_cash,
                difference=diff
            )

        return None


# Global reconciler instance (singleton pattern)
_reconciler_instance: Optional[Reconciler] = None


def get_reconciler(broker_adapter=None) -> Reconciler:
    """
    Get or create global reconciler instance.
    
    Args:
        broker_adapter: Broker adapter (required on first call)
        
    Returns:
        Reconciler instance
    """
    global _reconciler_instance
    if _reconciler_instance is None:
        if broker_adapter is None:
            raise ValueError("broker_adapter required for first call to get_reconciler()")
        _reconciler_instance = Reconciler(broker_adapter=broker_adapter)
    return _reconciler_instance
