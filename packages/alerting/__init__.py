"""Alerting System for IBKR AI Broker.

This module provides alerting for critical events:
- Broker disconnect
- Order rejection
- Daily loss threshold
- Kill switch activation

Supports:
- Email notifications (SMTP)
- Webhook notifications (HTTP POST)
- Rate limiting to prevent alert spam

Usage:
    from packages.alerting import get_alert_manager, AlertManager, AlertConfig
    
    manager = get_alert_manager()
    
    manager.send_alert(
        alert_type="broker_disconnect",
        severity="critical",
        message="Broker connection lost",
        details={"broker": "IBKR", "error": "timeout"}
    )
"""

import json
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from threading import Lock
from typing import Optional
from urllib import request
from urllib.error import URLError

__all__ = ["AlertManager", "AlertConfig", "AlertSeverity", "get_alert_manager", "set_alert_manager"]


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertConfig:
    """Alert configuration."""
    
    # Email settings
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    email_recipients: list[str] = field(default_factory=list)
    
    # Webhook settings
    webhook_url: str = ""
    webhook_headers: dict[str, str] = field(default_factory=dict)
    
    # Rate limiting (seconds between alerts of same type)
    rate_limit_seconds: int = 300  # 5 minutes
    
    # Alert thresholds
    daily_loss_threshold: float = 5000.0  # Alert if daily loss exceeds $5k
    
    @classmethod
    def from_env(cls) -> "AlertConfig":
        """Load alert configuration from environment variables.
        
        Env vars:
            SMTP_HOST: SMTP server host
            SMTP_PORT: SMTP server port
            SMTP_USER: SMTP username
            SMTP_PASSWORD: SMTP password
            SMTP_FROM: From email address
            EMAIL_RECIPIENTS: Comma-separated list of email addresses
            WEBHOOK_URL: Webhook URL for notifications
            ALERT_RATE_LIMIT: Rate limit in seconds
            DAILY_LOSS_THRESHOLD: Daily loss threshold for alerts
            
        Returns:
            AlertConfig instance
        """
        import os
        
        email_recipients = []
        if os.getenv("EMAIL_RECIPIENTS"):
            email_recipients = [e.strip() for e in os.getenv("EMAIL_RECIPIENTS", "").split(",") if e.strip()]
        
        webhook_headers = {}
        if os.getenv("WEBHOOK_AUTH_TOKEN"):
            webhook_headers["Authorization"] = f"Bearer {os.getenv('WEBHOOK_AUTH_TOKEN')}"
        
        return cls(
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", ""),
            email_recipients=email_recipients,
            webhook_url=os.getenv("WEBHOOK_URL", ""),
            webhook_headers=webhook_headers,
            rate_limit_seconds=int(os.getenv("ALERT_RATE_LIMIT", "300")),
            daily_loss_threshold=float(os.getenv("DAILY_LOSS_THRESHOLD", "5000.0")),
        )


@dataclass
class AlertManager:
    """Manage and send alerts for critical events."""
    
    config: AlertConfig
    
    # Rate limiting state
    _last_alert_time: dict[str, datetime] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    
    def send_alert(
        self,
        alert_type: str,
        severity: AlertSeverity,
        message: str,
        details: Optional[dict] = None,
        bypass_rate_limit: bool = False,
    ) -> bool:
        """Send alert via configured channels.
        
        Args:
            alert_type: Type of alert (e.g., "broker_disconnect")
            severity: Alert severity level
            message: Human-readable alert message
            details: Optional additional details
            bypass_rate_limit: Skip rate limiting check
            
        Returns:
            True if alert was sent, False if rate-limited or failed
        """
        # Check rate limit
        if not bypass_rate_limit and not self._check_rate_limit(alert_type):
            return False
        
        # Build alert payload
        alert_data = {
            "alert_type": alert_type,
            "severity": severity.value,
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        success = False
        
        # Send via email
        if self.config.email_recipients:
            try:
                self._send_email(alert_data)
                success = True
            except Exception:
                pass  # Continue to webhook
        
        # Send via webhook
        if self.config.webhook_url:
            try:
                self._send_webhook(alert_data)
                success = True
            except Exception:
                pass
        
        return success
    
    def _check_rate_limit(self, alert_type: str) -> bool:
        """Check if alert is rate-limited.
        
        Args:
            alert_type: Type of alert
            
        Returns:
            True if alert can be sent, False if rate-limited
        """
        with self._lock:
            now = datetime.utcnow()
            last_time = self._last_alert_time.get(alert_type)
            
            if last_time is None:
                # First alert of this type
                self._last_alert_time[alert_type] = now
                return True
            
            # Check if enough time has passed
            time_since_last = (now - last_time).total_seconds()
            
            if time_since_last >= self.config.rate_limit_seconds:
                self._last_alert_time[alert_type] = now
                return True
            
            return False
    
    def _send_email(self, alert_data: dict) -> None:
        """Send alert via email.
        
        Args:
            alert_data: Alert payload
            
        Raises:
            Exception: If email sending fails
        """
        if not self.config.smtp_host or not self.config.email_recipients:
            return
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{alert_data['severity'].upper()}] IBKR AI Broker Alert: {alert_data['alert_type']}"
        msg["From"] = self.config.smtp_from
        msg["To"] = ", ".join(self.config.email_recipients)
        
        # Email body
        text = f"""
IBKR AI Broker Alert

Alert Type: {alert_data['alert_type']}
Severity: {alert_data['severity']}
Time: {alert_data['timestamp']}

Message:
{alert_data['message']}

Details:
{json.dumps(alert_data['details'], indent=2)}
"""
        
        html = f"""
<html>
<body>
<h2 style="color: {'red' if alert_data['severity'] == 'critical' else 'orange'};">
    IBKR AI Broker Alert
</h2>
<table>
<tr><td><strong>Alert Type:</strong></td><td>{alert_data['alert_type']}</td></tr>
<tr><td><strong>Severity:</strong></td><td>{alert_data['severity']}</td></tr>
<tr><td><strong>Time:</strong></td><td>{alert_data['timestamp']}</td></tr>
</table>
<h3>Message:</h3>
<p>{alert_data['message']}</p>
<h3>Details:</h3>
<pre>{json.dumps(alert_data['details'], indent=2)}</pre>
</body>
</html>
"""
        
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        
        # Send email
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
            server.starttls()
            if self.config.smtp_user and self.config.smtp_password:
                server.login(self.config.smtp_user, self.config.smtp_password)
            server.send_message(msg)
    
    def _send_webhook(self, alert_data: dict) -> None:
        """Send alert via webhook.
        
        Args:
            alert_data: Alert payload
            
        Raises:
            Exception: If webhook request fails
        """
        if not self.config.webhook_url:
            return
        
        # Prepare request
        data = json.dumps(alert_data).encode("utf-8")
        req = request.Request(
            self.config.webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                **self.config.webhook_headers,
            },
            method="POST",
        )
        
        # Send request
        with request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                raise URLError(f"Webhook returned {response.status}")
    
    # Convenience methods for common alerts
    
    def alert_broker_disconnect(self, error: str) -> bool:
        """Alert for broker connection loss.
        
        Args:
            error: Error message
            
        Returns:
            True if alert was sent
        """
        return self.send_alert(
            alert_type="broker_disconnect",
            severity=AlertSeverity.CRITICAL,
            message="Broker connection lost - trading operations may be impacted",
            details={"error": error},
        )
    
    def alert_order_rejection(self, proposal_id: str, reason: str, violated_rules: list[str]) -> bool:
        """Alert for order rejection.
        
        Args:
            proposal_id: Proposal ID that was rejected
            reason: Rejection reason
            violated_rules: List of violated rule IDs
            
        Returns:
            True if alert was sent
        """
        return self.send_alert(
            alert_type="order_rejection",
            severity=AlertSeverity.WARNING,
            message=f"Order proposal {proposal_id} rejected by risk engine",
            details={
                "proposal_id": proposal_id,
                "reason": reason,
                "violated_rules": violated_rules,
            },
        )
    
    def alert_daily_loss_threshold(self, daily_pnl: float, threshold: float) -> bool:
        """Alert for daily loss threshold breach.
        
        Args:
            daily_pnl: Current daily P&L
            threshold: Threshold value
            
        Returns:
            True if alert was sent
        """
        return self.send_alert(
            alert_type="daily_loss_threshold",
            severity=AlertSeverity.ERROR,
            message=f"Daily loss threshold breached: ${daily_pnl:,.2f} (threshold: -${threshold:,.2f})",
            details={
                "daily_pnl": daily_pnl,
                "threshold": threshold,
                "breach_amount": abs(daily_pnl) - threshold,
            },
        )
    
    def alert_kill_switch_activated(self, reason: str, activated_by: str) -> bool:
        """Alert for kill switch activation.
        
        Args:
            reason: Activation reason
            activated_by: Who/what activated the kill switch
            
        Returns:
            True if alert was sent
        """
        return self.send_alert(
            alert_type="kill_switch_activated",
            severity=AlertSeverity.CRITICAL,
            message="KILL SWITCH ACTIVATED - All trading operations halted",
            details={
                "reason": reason,
                "activated_by": activated_by,
                "timestamp": datetime.utcnow().isoformat(),
            },
            bypass_rate_limit=True,  # Always send kill switch alerts
        )


# Global alert manager instance
_alert_manager: Optional[AlertManager] = None
_manager_lock = Lock()


def get_alert_manager() -> AlertManager:
    """Get global alert manager instance.
    
    Loads configuration from environment variables on first call.
    
    Returns:
        Global AlertManager instance
    """
    global _alert_manager
    
    if _alert_manager is None:
        with _manager_lock:
            if _alert_manager is None:
                config = AlertConfig.from_env()
                _alert_manager = AlertManager(config=config)
    
    return _alert_manager


def set_alert_manager(manager: AlertManager) -> None:
    """Set global alert manager (for testing).
    
    Args:
        manager: AlertManager instance to use
    """
    global _alert_manager
    
    with _manager_lock:
        _alert_manager = manager
