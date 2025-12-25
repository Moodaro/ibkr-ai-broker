"""
Tests for reconciliation module.
"""

import pytest
from datetime import datetime
from packages.reconciliation import (
    Reconciler,
    ReconciliationResult,
    Discrepancy,
    DiscrepancyType,
    DiscrepancySeverity,
    get_reconciler
)


class FakeBrokerForRecon:
    """Fake broker adapter for reconciliation testing."""

    def __init__(self):
        self.open_orders = []
        self.positions = []
        self.cash = 10000.0

    def get_open_orders(self, account_id: str):
        return self.open_orders

    def get_positions(self, account_id: str):
        return self.positions

    def get_cash(self, account_id: str):
        return self.cash


class TestReconciler:
    """Test suite for Reconciler class."""

    def setup_method(self):
        """Setup for each test."""
        self.broker = FakeBrokerForRecon()
        self.reconciler = Reconciler(broker_adapter=self.broker)

    def test_perfect_reconciliation(self):
        """Test when internal state matches broker exactly."""
        # Setup matching state
        self.broker.open_orders = [
            {"order_id": "order1", "symbol": "AAPL", "quantity": 100, "side": "BUY"}
        ]
        self.broker.positions = [
            {"symbol": "AAPL", "quantity": 100}
        ]
        self.broker.cash = 5000.0

        internal_orders = [
            {"order_id": "order1", "symbol": "AAPL", "quantity": 100, "side": "BUY"}
        ]
        internal_positions = {"AAPL": 100}
        internal_cash = 5000.0

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=internal_orders,
            internal_positions=internal_positions,
            internal_cash=internal_cash
        )

        assert result.is_reconciled is True
        assert result.discrepancy_count == 0
        assert result.has_critical_discrepancies is False
        assert result.internal_orders_count == 1
        assert result.broker_orders_count == 1

    def test_missing_order_discrepancy(self):
        """Test when order exists in system but not in broker."""
        self.broker.open_orders = []
        
        internal_orders = [
            {"order_id": "order1", "symbol": "AAPL", "quantity": 100, "side": "BUY"}
        ]

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=internal_orders,
            internal_positions={},
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        assert result.discrepancies[0].type == DiscrepancyType.MISSING_ORDER
        assert result.discrepancies[0].severity == DiscrepancySeverity.HIGH
        assert result.discrepancies[0].order_id == "order1"

    def test_unknown_order_discrepancy(self):
        """Test when order exists in broker but not in system (CRITICAL)."""
        self.broker.open_orders = [
            {"order_id": "unknown1", "symbol": "TSLA", "quantity": 50, "side": "SELL"}
        ]

        internal_orders = []

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=internal_orders,
            internal_positions={},
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        assert result.discrepancies[0].type == DiscrepancyType.UNKNOWN_ORDER
        assert result.discrepancies[0].severity == DiscrepancySeverity.CRITICAL
        assert result.discrepancies[0].order_id == "unknown1"

    def test_position_mismatch_discrepancy(self):
        """Test when position quantities differ."""
        self.broker.positions = [
            {"symbol": "AAPL", "quantity": 100}
        ]

        internal_positions = {"AAPL": 105}  # 5 share difference

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions=internal_positions,
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        disc = result.discrepancies[0]
        assert disc.type == DiscrepancyType.POSITION_MISMATCH
        assert disc.symbol == "AAPL"
        assert disc.internal_value == 105
        assert disc.broker_value == 100
        assert disc.difference == 5.0

    def test_missing_position_discrepancy(self):
        """Test when position exists in system but not in broker."""
        self.broker.positions = []
        
        internal_positions = {"MSFT": 50}

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions=internal_positions,
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        disc = result.discrepancies[0]
        assert disc.type == DiscrepancyType.MISSING_POSITION
        assert disc.symbol == "MSFT"

    def test_unknown_position_discrepancy(self):
        """Test when position exists in broker but not in system."""
        self.broker.positions = [
            {"symbol": "GOOGL", "quantity": 20}
        ]

        internal_positions = {}

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions=internal_positions,
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        disc = result.discrepancies[0]
        assert disc.type == DiscrepancyType.UNKNOWN_POSITION
        assert disc.symbol == "GOOGL"

    def test_cash_mismatch_discrepancy(self):
        """Test when cash balances differ."""
        self.broker.cash = 10000.0

        internal_cash = 9500.0  # $500 difference

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions={},
            internal_cash=internal_cash
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        disc = result.discrepancies[0]
        assert disc.type == DiscrepancyType.CASH_MISMATCH
        assert disc.severity == DiscrepancySeverity.MEDIUM  # $500 = MEDIUM
        assert disc.difference == 500.0

    def test_cash_within_tolerance(self):
        """Test that small cash differences within tolerance are ignored."""
        self.broker.cash = 10000.00

        internal_cash = 10000.005  # $0.005 difference (< $0.01 tolerance)

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions={},
            internal_cash=internal_cash
        )

        assert result.is_reconciled is True
        assert result.discrepancy_count == 0

    def test_position_severity_levels(self):
        """Test that position discrepancies have appropriate severity."""
        test_cases = [
            (1, DiscrepancySeverity.LOW),
            (5, DiscrepancySeverity.MEDIUM),
            (15, DiscrepancySeverity.HIGH),
            (150, DiscrepancySeverity.CRITICAL)
        ]

        for diff, expected_severity in test_cases:
            self.broker.positions = [{"symbol": "TEST", "quantity": 100}]
            internal_positions = {"TEST": 100 + diff}

            result = self.reconciler.reconcile(
                account_id="DU12345",
                internal_orders=[],
                internal_positions=internal_positions,
                internal_cash=10000.0
            )

            assert result.discrepancy_count == 1
            assert result.discrepancies[0].severity == expected_severity, \
                f"Expected severity {expected_severity} for diff={diff}"

    def test_cash_severity_levels(self):
        """Test that cash discrepancies have appropriate severity."""
        test_cases = [
            (50, DiscrepancySeverity.LOW),      # $50
            (500, DiscrepancySeverity.MEDIUM),  # $500
            (5000, DiscrepancySeverity.HIGH),   # $5k
            (50000, DiscrepancySeverity.CRITICAL)  # $50k
        ]

        for diff, expected_severity in test_cases:
            self.broker.cash = 10000.0
            internal_cash = 10000.0 + diff

            result = self.reconciler.reconcile(
                account_id="DU12345",
                internal_orders=[],
                internal_positions={},
                internal_cash=internal_cash
            )

            assert result.discrepancy_count == 1
            assert result.discrepancies[0].severity == expected_severity, \
                f"Expected severity {expected_severity} for diff=${diff}"

    def test_multiple_discrepancies(self):
        """Test reconciliation with multiple types of discrepancies."""
        self.broker.open_orders = [
            {"order_id": "unknown1", "symbol": "TSLA", "quantity": 10, "side": "BUY"}
        ]
        self.broker.positions = [
            {"symbol": "AAPL", "quantity": 100},
            {"symbol": "GOOGL", "quantity": 50}
        ]
        self.broker.cash = 15000.0

        internal_orders = [
            {"order_id": "order1", "symbol": "AAPL", "quantity": 100, "side": "BUY"}
        ]
        internal_positions = {
            "AAPL": 95,  # 5 share difference
            "MSFT": 20   # Missing in broker
        }
        internal_cash = 14000.0  # $1000 difference

        result = self.reconciler.reconcile(
            account_id="DU12345",
            internal_orders=internal_orders,
            internal_positions=internal_positions,
            internal_cash=internal_cash
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 6  # unknown order, missing order, 3 position issues, cash
        assert result.has_critical_discrepancies is True  # unknown order is CRITICAL

        # Verify we have all types
        types = {d.type for d in result.discrepancies}
        assert DiscrepancyType.UNKNOWN_ORDER in types
        assert DiscrepancyType.MISSING_ORDER in types
        assert DiscrepancyType.POSITION_MISMATCH in types
        assert DiscrepancyType.MISSING_POSITION in types
        assert DiscrepancyType.UNKNOWN_POSITION in types
        assert DiscrepancyType.CASH_MISMATCH in types

    def test_reconciliation_result_to_dict(self):
        """Test that ReconciliationResult can be serialized to dict."""
        result = ReconciliationResult(
            timestamp=datetime(2025, 12, 25, 10, 0, 0),
            is_reconciled=False,
            discrepancies=[
                Discrepancy(
                    type=DiscrepancyType.CASH_MISMATCH,
                    severity=DiscrepancySeverity.HIGH,
                    description="Test discrepancy",
                    internal_value=1000.0,
                    broker_value=1100.0,
                    difference=100.0
                )
            ],
            internal_orders_count=1,
            broker_orders_count=1,
            internal_positions_count=2,
            broker_positions_count=2,
            internal_cash=10000.0,
            broker_cash=10100.0,
            duration_ms=123.45
        )

        result_dict = result.to_dict()

        assert result_dict["is_reconciled"] is False
        assert result_dict["discrepancy_count"] == 1
        assert result_dict["has_critical_discrepancies"] is False
        assert len(result_dict["discrepancies"]) == 1
        assert result_dict["summary"]["internal_cash"] == 10000.0
        assert result_dict["duration_ms"] == 123.45

    def test_discrepancy_to_dict(self):
        """Test that Discrepancy can be serialized to dict."""
        disc = Discrepancy(
            type=DiscrepancyType.POSITION_MISMATCH,
            severity=DiscrepancySeverity.MEDIUM,
            description="Position mismatch",
            internal_value=100,
            broker_value=95,
            difference=5.0,
            symbol="AAPL",
            order_id="order123"
        )

        disc_dict = disc.to_dict()

        assert disc_dict["type"] == "position_mismatch"
        assert disc_dict["severity"] == "medium"
        assert disc_dict["description"] == "Position mismatch"
        assert disc_dict["internal_value"] == "100"
        assert disc_dict["broker_value"] == "95"
        assert disc_dict["difference"] == 5.0
        assert disc_dict["symbol"] == "AAPL"
        assert disc_dict["order_id"] == "order123"
        assert "detected_at" in disc_dict

    def test_broker_fetch_error(self):
        """Test handling when broker state cannot be fetched."""
        
        class FailingBroker:
            def get_open_orders(self, account_id):
                raise Exception("Broker API error")
            
            def get_positions(self, account_id):
                raise Exception("Broker API error")
            
            def get_cash(self, account_id):
                raise Exception("Broker API error")

        reconciler = Reconciler(broker_adapter=FailingBroker())

        result = reconciler.reconcile(
            account_id="DU12345",
            internal_orders=[],
            internal_positions={},
            internal_cash=10000.0
        )

        assert result.is_reconciled is False
        assert result.discrepancy_count == 1
        assert result.has_critical_discrepancies is True
        disc = result.discrepancies[0]
        assert disc.severity == DiscrepancySeverity.CRITICAL
        assert "Cannot fetch broker state" in disc.description

    def test_get_reconciler_singleton(self):
        """Test that get_reconciler returns singleton instance."""
        broker = FakeBrokerForRecon()
        
        # Clear global state
        import packages.reconciliation
        packages.reconciliation._reconciler_instance = None

        recon1 = get_reconciler(broker_adapter=broker)
        recon2 = get_reconciler()  # Should return same instance

        assert recon1 is recon2

    def test_get_reconciler_requires_adapter_first_time(self):
        """Test that get_reconciler requires broker_adapter on first call."""
        # Clear global state
        import packages.reconciliation
        packages.reconciliation._reconciler_instance = None

        with pytest.raises(ValueError, match="broker_adapter required"):
            get_reconciler()
