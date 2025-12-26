"""
Tests for live trading readiness validation.

These tests verify that the system is properly configured for live trading.
"""

import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from packages.audit_store import AuditStore
from packages.broker_ibkr import FakeBrokerAdapter
from packages.health_monitor import (
    AlertCondition,
    AlertSeverity,
    HealthMonitor,
    HealthStatus,
    create_broker_connection_check,
    create_disk_space_check,
    create_kill_switch_check,
)
from packages.kill_switch import KillSwitch


class TestLiveReadiness:
    """Tests for live trading environment validation."""

    def test_env_validation_paper_mode(self):
        """ENV=paper should not allow live trading."""
        env = os.getenv("ENV", "dev")
        assert env in ["dev", "paper"], f"ENV={env} - do not run these tests in live mode"

    def test_env_variables_present(self):
        """Required environment variables must be set."""
        # Critical env vars for live trading
        required = ["IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID"]
        missing = [var for var in required if not os.getenv(var)]
        
        # In dev/paper, we allow defaults, but document what's needed
        if missing:
            pytest.skip(f"Missing env vars (OK in dev): {missing}")

    def test_kill_switch_exists_and_works(self, tmp_path):
        """Kill switch must be functional."""
        # Clear singleton
        KillSwitch._instance = None
        
        kill_switch = KillSwitch(state_file=str(tmp_path / "kill_switch.txt"))

        # Should start disabled (not enabled)
        assert not kill_switch.is_enabled()

        # Should activate successfully
        kill_switch.activate(
            reason="Test trigger",
            activated_by="test",
        )
        assert kill_switch.is_enabled()

        # Should persist state
        KillSwitch._instance = None  # Reset singleton
        kill_switch2 = KillSwitch(state_file=str(tmp_path / "kill_switch.txt"))
        assert kill_switch2.is_enabled()

        # Should deactivate successfully
        kill_switch2.deactivate(deactivated_by="test")
        assert not kill_switch2.is_enabled()

    def test_risk_limits_configured(self):
        """Risk limits must be explicitly configured (not defaults)."""
        from pathlib import Path
        
        risk_policy_path = Path("risk_policy.yml")
        if not risk_policy_path.exists():
            pytest.fail("risk_policy.yml not found")

        content = risk_policy_path.read_text()
        
        # Check critical limits are present (use actual field names from risk_policy.yml)
        assert "max_notional:" in content, "Missing max_notional"
        assert "max_position_pct:" in content, "Missing max_position_pct"
        assert "max_drawdown_pct:" in content, "Missing max_drawdown_pct"

    def test_no_hardcoded_credentials(self):
        """No credentials should be hardcoded in source."""
        # Check common patterns (basic check, not exhaustive)
        patterns = ["password=", "secret=", "api_key=", "token="]
        
        # Check main packages (skip tests, this file would match)
        packages_dir = Path("packages")
        if packages_dir.exists():
            for py_file in packages_dir.rglob("*.py"):
                if "test_" in py_file.name:
                    continue  # Skip test files
                content = py_file.read_text().lower()
                for pattern in patterns:
                    if pattern in content and "env" not in content[content.index(pattern):content.index(pattern)+50]:
                        pytest.fail(f"Potential hardcoded credential in {py_file}: {pattern}")

    def test_audit_store_writable(self, tmp_path):
        """Audit store must be writable."""
        from packages.audit_store import AuditEvent, EventType
        from datetime import datetime, timezone

        audit_store = AuditStore(str(tmp_path / "audit.db"))
        
        # Should be able to write events
        event = AuditEvent(
            event_type=EventType.SYSTEM_EVENT,
            correlation_id="test",
            timestamp=datetime.now(tz=timezone.utc),
            data={"test": "data"},
        )
        audit_store.append_event(event)

        # Should be able to read back
        events = audit_store.query_events(correlation_id="test")
        assert len(events) >= 1

    def test_health_monitor_kill_switch_check(self, tmp_path):
        """Health monitor should detect kill switch status."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        
        # Clear singleton
        KillSwitch._instance = None
        kill_switch = KillSwitch(state_file=str(tmp_path / "kill_switch.txt"))
        monitor = HealthMonitor(audit_store)

        # Register kill switch health check
        monitor.register_health_check(
            "kill_switch",
            create_kill_switch_check(kill_switch),
        )

        # Should be healthy when not enabled
        checks = monitor.run_health_checks()
        assert len(checks) == 1
        assert checks[0].status == HealthStatus.HEALTHY

        # Should be unhealthy when activated
        kill_switch.activate(
            reason="Test",
            activated_by="test",
        )
        checks = monitor.run_health_checks()
        assert len(checks) == 1
        assert checks[0].status == HealthStatus.UNHEALTHY

    def test_health_monitor_broker_connection(self, tmp_path):
        """Health monitor should check broker connection."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        broker = FakeBrokerAdapter()
        monitor = HealthMonitor(audit_store)

        # Register broker connection check
        monitor.register_health_check(
            "broker_connection",
            create_broker_connection_check(broker, "DU12345"),
        )

        # Should be healthy with working broker
        checks = monitor.run_health_checks()
        assert len(checks) == 1
        assert checks[0].status == HealthStatus.HEALTHY

    def test_health_monitor_disk_space(self, tmp_path):
        """Health monitor should check disk space."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        monitor = HealthMonitor(audit_store)

        # Register disk space check (with very low threshold for testing)
        monitor.register_health_check(
            "disk_space",
            create_disk_space_check(str(tmp_path), min_gb=0.001),  # 1 MB
        )

        # Should be healthy (we have more than 1MB)
        checks = monitor.run_health_checks()
        assert len(checks) == 1
        assert checks[0].status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]

    def test_alert_condition_triggers(self, tmp_path):
        """Alert conditions should trigger when condition met."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        monitor = HealthMonitor(audit_store)

        # Create alert condition that always triggers
        condition = AlertCondition(
            name="test_alert",
            check_function=lambda: True,  # Always true
            severity=AlertSeverity.WARNING,
            message_template="Test alert triggered",
            cooldown_seconds=1,
        )
        monitor.register_alert_condition(condition)

        # Should trigger alert
        alerts = monitor.check_alerts()
        assert len(alerts) == 1
        assert alerts[0].condition_name == "test_alert"
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_alert_cooldown_prevents_spam(self, tmp_path):
        """Alert cooldown should prevent repeated alerts."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        monitor = HealthMonitor(audit_store)

        # Create alert with short cooldown
        condition = AlertCondition(
            name="test_alert",
            check_function=lambda: True,
            severity=AlertSeverity.WARNING,
            message_template="Test alert",
            cooldown_seconds=3600,  # 1 hour cooldown
        )
        monitor.register_alert_condition(condition)

        # First check triggers
        alerts1 = monitor.check_alerts()
        assert len(alerts1) == 1

        # Second check immediately should not trigger (cooldown)
        alerts2 = monitor.check_alerts()
        assert len(alerts2) == 0

    def test_overall_health_status(self, tmp_path):
        """Overall health should reflect worst individual check."""
        audit_store = AuditStore(str(tmp_path / "audit.db"))
        monitor = HealthMonitor(audit_store)

        # All healthy
        from packages.health_monitor import HealthCheck
        monitor.register_health_check(
            "check1",
            lambda: HealthCheck("check1", HealthStatus.HEALTHY, "OK"),
        )
        assert monitor.get_overall_status() == HealthStatus.HEALTHY

        # One degraded
        monitor.register_health_check(
            "check2",
            lambda: HealthCheck("check2", HealthStatus.DEGRADED, "Warning"),
        )
        assert monitor.get_overall_status() == HealthStatus.DEGRADED

        # One unhealthy (worst)
        monitor.register_health_check(
            "check3",
            lambda: HealthCheck("check3", HealthStatus.UNHEALTHY, "Error"),
        )
        assert monitor.get_overall_status() == HealthStatus.UNHEALTHY


class TestLiveConfigValidation:
    """Tests for live configuration validation."""

    def test_volatility_provider_not_mock_for_live(self):
        """Volatility provider should be 'historical' for live, not 'mock'."""
        from pathlib import Path
        import yaml

        risk_policy_path = Path("risk_policy.yml")
        if not risk_policy_path.exists():
            pytest.skip("risk_policy.yml not found")

        config = yaml.safe_load(risk_policy_path.read_text())
        
        # In live mode, volatility_provider should be 'historical'
        # In paper/dev, 'mock' is acceptable
        env = os.getenv("ENV", "dev")
        if env == "live":
            vol_config = config.get("volatility_provider", {})
            provider_type = vol_config.get("provider_type", "mock")
            assert provider_type == "historical", \
                f"Live mode should use 'historical' volatility provider, not '{provider_type}'"

    def test_trading_hours_configured(self):
        """Trading hours must be explicitly configured."""
        from pathlib import Path
        import yaml

        risk_policy_path = Path("risk_policy.yml")
        if not risk_policy_path.exists():
            pytest.skip("risk_policy.yml not found")

        config = yaml.safe_load(risk_policy_path.read_text())
        
        # Should have trading hours section
        assert "trading_hours" in config, "Missing trading_hours configuration"
        
        trading_hours = config["trading_hours"]
        assert "start_time" in trading_hours, "Missing start_time"
        assert "end_time" in trading_hours, "Missing end_time"

    def test_risk_limits_appropriate_for_account_size(self):
        """Risk limits should be reasonable for live trading."""
        from pathlib import Path
        import yaml

        risk_policy_path = Path("risk_policy.yml")
        if not risk_policy_path.exists():
            pytest.skip("risk_policy.yml not found")

        config = yaml.safe_load(risk_policy_path.read_text())
        
        # Max position should be < 20% (reasonable for most accounts)
        limits = config.get("limits", {})
        max_position_pct = limits.get("max_position_pct", 100)
        assert max_position_pct <= 20.0, \
            f"max_position_pct too high for live: {max_position_pct}% (recommended < 20%)"
        
        # Max notional should exist
        max_notional = limits.get("max_notional", 0)
        assert max_notional > 0, "max_notional must be configured"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
