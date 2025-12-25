"""Tests for alerting system."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from packages.alerting import AlertConfig, AlertManager, AlertSeverity, get_alert_manager, set_alert_manager


class TestAlertConfig:
    """Test alert configuration."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = AlertConfig()
        
        assert config.smtp_host == ""
        assert config.smtp_port == 587
        assert config.email_recipients == []
        assert config.webhook_url == ""
        assert config.rate_limit_seconds == 300
        assert config.daily_loss_threshold == 5000.0
    
    def test_from_env(self, monkeypatch):
        """Test loading from environment variables."""
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USER", "user@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "password")
        monkeypatch.setenv("SMTP_FROM", "alerts@example.com")
        monkeypatch.setenv("EMAIL_RECIPIENTS", "admin@example.com, ops@example.com")
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com/webhook")
        monkeypatch.setenv("WEBHOOK_AUTH_TOKEN", "secret-token")
        monkeypatch.setenv("ALERT_RATE_LIMIT", "600")
        monkeypatch.setenv("DAILY_LOSS_THRESHOLD", "10000.0")
        
        config = AlertConfig.from_env()
        
        assert config.smtp_host == "smtp.example.com"
        assert config.smtp_port == 465
        assert config.smtp_user == "user@example.com"
        assert config.smtp_password == "password"
        assert config.smtp_from == "alerts@example.com"
        assert len(config.email_recipients) == 2
        assert "admin@example.com" in config.email_recipients
        assert config.webhook_url == "https://example.com/webhook"
        assert "Authorization" in config.webhook_headers
        assert config.rate_limit_seconds == 600
        assert config.daily_loss_threshold == 10000.0


class TestAlertManager:
    """Test alert manager functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test alert config."""
        return AlertConfig(
            smtp_host="smtp.test.com",
            smtp_port=587,
            smtp_user="test@test.com",
            smtp_password="password",
            smtp_from="alerts@test.com",
            email_recipients=["admin@test.com"],
            webhook_url="https://test.com/webhook",
            rate_limit_seconds=60,
            daily_loss_threshold=1000.0,
        )
    
    @pytest.fixture
    def manager(self, config):
        """Create test alert manager."""
        return AlertManager(config=config)
    
    def test_rate_limiting(self, manager):
        """Test rate limiting prevents duplicate alerts."""
        # First alert should succeed
        with patch.object(manager, "_send_email"), patch.object(manager, "_send_webhook"):
            result1 = manager.send_alert(
                alert_type="test_alert",
                severity=AlertSeverity.INFO,
                message="Test",
            )
            assert result1 is True
        
        # Second alert (immediately after) should be rate-limited
        with patch.object(manager, "_send_email"), patch.object(manager, "_send_webhook"):
            result2 = manager.send_alert(
                alert_type="test_alert",
                severity=AlertSeverity.INFO,
                message="Test",
            )
            assert result2 is False
    
    def test_bypass_rate_limit(self, manager):
        """Test bypassing rate limit."""
        with patch.object(manager, "_send_email"), patch.object(manager, "_send_webhook"):
            # First alert
            manager.send_alert(
                alert_type="test_alert",
                severity=AlertSeverity.INFO,
                message="Test",
            )
            
            # Second alert with bypass
            result = manager.send_alert(
                alert_type="test_alert",
                severity=AlertSeverity.INFO,
                message="Test",
                bypass_rate_limit=True,
            )
            assert result is True
    
    def test_different_alert_types_not_rate_limited(self, manager):
        """Test different alert types are not rate-limited together."""
        with patch.object(manager, "_send_email"), patch.object(manager, "_send_webhook"):
            # Alert type 1
            result1 = manager.send_alert(
                alert_type="alert_type_1",
                severity=AlertSeverity.INFO,
                message="Test 1",
            )
            assert result1 is True
            
            # Alert type 2 (different type)
            result2 = manager.send_alert(
                alert_type="alert_type_2",
                severity=AlertSeverity.INFO,
                message="Test 2",
            )
            assert result2 is True
    
    @patch("smtplib.SMTP")
    def test_send_email(self, mock_smtp, manager):
        """Test sending email alert."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        alert_data = {
            "alert_type": "test_alert",
            "severity": "critical",
            "message": "Test message",
            "details": {"key": "value"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        manager._send_email(alert_data)
        
        # Verify SMTP was called
        mock_smtp.assert_called_once_with("smtp.test.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@test.com", "password")
        mock_server.send_message.assert_called_once()
    
    @patch("urllib.request.urlopen")
    def test_send_webhook(self, mock_urlopen, manager):
        """Test sending webhook alert."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        alert_data = {
            "alert_type": "test_alert",
            "severity": "warning",
            "message": "Test message",
            "details": {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        manager._send_webhook(alert_data)
        
        # Verify urlopen was called
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        assert call_args[0][0].full_url == "https://test.com/webhook"
    
    def test_alert_broker_disconnect(self, manager):
        """Test broker disconnect convenience method."""
        with patch.object(manager, "send_alert") as mock_send:
            manager.alert_broker_disconnect("Connection timeout")
            
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert args[1]["alert_type"] == "broker_disconnect"
            assert args[1]["severity"] == AlertSeverity.CRITICAL
            assert "timeout" in str(args[1]["details"])
    
    def test_alert_order_rejection(self, manager):
        """Test order rejection convenience method."""
        with patch.object(manager, "send_alert") as mock_send:
            manager.alert_order_rejection("proposal-123", "R1 violated", ["R1"])
            
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert args[1]["alert_type"] == "order_rejection"
            assert args[1]["severity"] == AlertSeverity.WARNING
    
    def test_alert_daily_loss_threshold(self, manager):
        """Test daily loss threshold convenience method."""
        with patch.object(manager, "send_alert") as mock_send:
            manager.alert_daily_loss_threshold(-1500.0, 1000.0)
            
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert args[1]["alert_type"] == "daily_loss_threshold"
            assert args[1]["severity"] == AlertSeverity.ERROR
            assert args[1]["details"]["daily_pnl"] == -1500.0
    
    def test_alert_kill_switch_activated(self, manager):
        """Test kill switch activation convenience method."""
        with patch.object(manager, "send_alert") as mock_send:
            manager.alert_kill_switch_activated("Manual activation", "admin")
            
            mock_send.assert_called_once()
            args = mock_send.call_args
            assert args[1]["alert_type"] == "kill_switch_activated"
            assert args[1]["severity"] == AlertSeverity.CRITICAL
            assert args[1]["bypass_rate_limit"] is True


class TestGlobalAlertManager:
    """Test global alert manager singleton."""
    
    def test_get_alert_manager_singleton(self):
        """Test get_alert_manager returns same instance."""
        manager1 = get_alert_manager()
        manager2 = get_alert_manager()
        
        assert manager1 is manager2
    
    def test_set_alert_manager(self):
        """Test setting custom alert manager."""
        custom_config = AlertConfig(smtp_host="custom.smtp.com")
        custom_manager = AlertManager(config=custom_config)
        
        set_alert_manager(custom_manager)
        
        retrieved = get_alert_manager()
        assert retrieved is custom_manager
        assert retrieved.config.smtp_host == "custom.smtp.com"
