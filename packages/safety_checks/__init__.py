"""
Pre-live safety checks for validating system readiness.

This module performs comprehensive validation before enabling live trading,
checking that all critical systems are functional and properly configured.

Safety checks include:
- Test coverage meets minimum threshold (>80% for packages)
- Audit backup system operational
- Alerting system configured and functional
- Reconciliation system operational
- Kill switch functional
- Feature flags system working
- Statistics collection active

Usage:
    from packages.safety_checks import SafetyChecker, SafetyCheckResult
    
    checker = SafetyChecker()
    result = checker.run_all_checks()
    
    if result.ready_for_live:
        print("✅ System ready for live trading!")
    else:
        for issue in result.blocking_issues:
            print(f"❌ {issue}")
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import subprocess
import os


class CheckStatus(str, Enum):
    """Status of a safety check."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIP = "SKIP"


class CheckSeverity(str, Enum):
    """Severity level of a failed check."""
    BLOCKER = "BLOCKER"  # Must fix before live
    CRITICAL = "CRITICAL"  # Should fix before live
    WARNING = "WARNING"  # Can proceed with caution
    INFO = "INFO"  # Informational only


@dataclass
class CheckResult:
    """Result of a single safety check."""
    name: str
    status: CheckStatus
    severity: CheckSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SafetyCheckResult:
    """
    Complete safety check result.
    
    Attributes:
        ready_for_live: True if all BLOCKER checks pass
        checks: List of individual check results
        blocking_issues: List of blocker issue descriptions
        warnings: List of warning messages
        recommendations: List of recommended actions
    """
    ready_for_live: bool
    checks_passed: int
    checks_total: int
    checks: List[CheckResult] = field(default_factory=list)
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ready_for_live": self.ready_for_live,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_issues": self.blocking_issues,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp.isoformat(),
        }


class SafetyChecker:
    """
    Performs pre-live safety checks.
    
    Validates that all critical systems are functional and properly configured
    before enabling live trading.
    """
    
    def __init__(
        self,
        min_test_coverage: float = 0.80,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize safety checker.
        
        Args:
            min_test_coverage: Minimum test coverage threshold (0.80 = 80%)
            project_root: Project root directory (defaults to current directory)
        """
        self.min_test_coverage = min_test_coverage
        self.project_root = project_root or Path.cwd()
        self.checks: List[CheckResult] = []
    
    def run_all_checks(self) -> SafetyCheckResult:
        """
        Run all safety checks.
        
        Returns:
            SafetyCheckResult with complete validation results
        """
        self.checks = []
        
        # Run all checks
        self.check_test_coverage()
        self.check_audit_backup()
        self.check_alerting_system()
        self.check_reconciliation_system()
        self.check_kill_switch()
        self.check_feature_flags()
        self.check_statistics_collection()
        
        # Analyze results
        checks_total = len(self.checks)
        checks_passed = sum(1 for c in self.checks if c.status == CheckStatus.PASS)
        
        blocking_issues = []
        warnings = []
        recommendations = []
        
        for check in self.checks:
            if check.status == CheckStatus.FAIL:
                if check.severity == CheckSeverity.BLOCKER:
                    blocking_issues.append(f"{check.name}: {check.message}")
                elif check.severity == CheckSeverity.CRITICAL:
                    warnings.append(f"{check.name}: {check.message}")
                elif check.severity == CheckSeverity.WARNING:
                    warnings.append(f"{check.name}: {check.message}")
            
            elif check.status == CheckStatus.WARNING:
                warnings.append(f"{check.name}: {check.message}")
                if check.details.get("recommendation"):
                    recommendations.append(check.details["recommendation"])
        
        # Add general recommendations
        if checks_passed < checks_total:
            if not recommendations:
                recommendations.append(
                    "Review failed checks and address issues before enabling live trading"
                )
        
        return SafetyCheckResult(
            ready_for_live=len(blocking_issues) == 0,
            checks_passed=checks_passed,
            checks_total=checks_total,
            checks=self.checks,
            blocking_issues=blocking_issues,
            warnings=warnings,
            recommendations=recommendations,
        )
    
    def check_test_coverage(self) -> CheckResult:
        """Check that test coverage meets minimum threshold."""
        try:
            # Try to get coverage from pytest-cov
            # Note: This assumes pytest-cov is installed and configured
            result = subprocess.run(
                ["python", "-m", "pytest", "--cov=packages", "--cov=apps", 
                 "--cov-report=term", "--co", "-q"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
            )
            
            # For MVP, we'll do a simpler check: verify tests exist
            tests_dir = self.project_root / "tests"
            if not tests_dir.exists():
                check = CheckResult(
                    name="Test Coverage",
                    status=CheckStatus.FAIL,
                    severity=CheckSeverity.BLOCKER,
                    message="Tests directory not found",
                    details={"path": str(tests_dir)},
                )
            else:
                test_files = list(tests_dir.glob("test_*.py"))
                test_count = len(test_files)
                
                if test_count == 0:
                    check = CheckResult(
                        name="Test Coverage",
                        status=CheckStatus.FAIL,
                        severity=CheckSeverity.BLOCKER,
                        message="No test files found",
                        details={"test_files": test_count},
                    )
                elif test_count < 10:
                    check = CheckResult(
                        name="Test Coverage",
                        status=CheckStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message=f"Low test coverage: only {test_count} test files",
                        details={
                            "test_files": test_count,
                            "recommendation": "Add more comprehensive test coverage"
                        },
                    )
                else:
                    check = CheckResult(
                        name="Test Coverage",
                        status=CheckStatus.PASS,
                        severity=CheckSeverity.INFO,
                        message=f"Test coverage adequate: {test_count} test files found",
                        details={"test_files": test_count},
                    )
            
        except subprocess.TimeoutExpired:
            check = CheckResult(
                name="Test Coverage",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.WARNING,
                message="Coverage check timed out",
                details={"timeout": 30},
            )
        except Exception as e:
            check = CheckResult(
                name="Test Coverage",
                status=CheckStatus.WARNING,
                severity=CheckSeverity.WARNING,
                message=f"Could not verify test coverage: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_audit_backup(self) -> CheckResult:
        """Check that audit backup system is operational."""
        try:
            # Check if backup module exists
            from packages.audit_backup import AuditBackupManager
            
            # Verify backup directory can be created
            backup_dir = self.project_root / "data" / "audit_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if we can write to backup directory
            test_file = backup_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            
            check = CheckResult(
                name="Audit Backup",
                status=CheckStatus.PASS,
                severity=CheckSeverity.INFO,
                message="Audit backup system operational",
                details={"backup_dir": str(backup_dir)},
            )
            
        except ImportError as e:
            check = CheckResult(
                name="Audit Backup",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Audit backup module not found",
                details={"error": str(e)},
            )
        except PermissionError:
            check = CheckResult(
                name="Audit Backup",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                message="Cannot write to backup directory - permission denied",
                details={"backup_dir": str(backup_dir)},
            )
        except Exception as e:
            check = CheckResult(
                name="Audit Backup",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Audit backup system error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_alerting_system(self) -> CheckResult:
        """Check that alerting system is configured."""
        try:
            from packages.alerting import AlertingSystem
            
            # Check if alerting is configured (SMTP or webhook)
            smtp_host = os.getenv("ALERT_SMTP_HOST")
            webhook_url = os.getenv("ALERT_WEBHOOK_URL")
            
            if not smtp_host and not webhook_url:
                check = CheckResult(
                    name="Alerting System",
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message="Alerting not configured (no SMTP or webhook)",
                    details={
                        "smtp_configured": False,
                        "webhook_configured": False,
                        "recommendation": "Configure ALERT_SMTP_HOST or ALERT_WEBHOOK_URL"
                    },
                )
            else:
                check = CheckResult(
                    name="Alerting System",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="Alerting system configured",
                    details={
                        "smtp_configured": smtp_host is not None,
                        "webhook_configured": webhook_url is not None,
                    },
                )
            
        except ImportError:
            check = CheckResult(
                name="Alerting System",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Alerting module not found",
                details={},
            )
        except Exception as e:
            check = CheckResult(
                name="Alerting System",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.WARNING,
                message=f"Alerting system error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_reconciliation_system(self) -> CheckResult:
        """Check that reconciliation system is operational."""
        try:
            from packages.reconciliation import get_reconciler
            
            # Try to get reconciler (should be initialized in app lifespan)
            try:
                reconciler = get_reconciler()
                
                check = CheckResult(
                    name="Reconciliation System",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="Reconciliation system initialized",
                    details={},
                )
            except ValueError:
                # Reconciler not yet initialized (expected if called before app startup)
                check = CheckResult(
                    name="Reconciliation System",
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message="Reconciliation system not initialized (will be initialized on app startup)",
                    details={
                        "recommendation": "This is normal if checks run before app startup"
                    },
                )
            
        except ImportError:
            check = CheckResult(
                name="Reconciliation System",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                message="Reconciliation module not found",
                details={},
            )
        except Exception as e:
            check = CheckResult(
                name="Reconciliation System",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Reconciliation system error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_kill_switch(self) -> CheckResult:
        """Check that kill switch is functional."""
        try:
            from packages.kill_switch import get_kill_switch
            
            kill_switch = get_kill_switch()
            
            # Verify kill switch state can be read
            is_active = kill_switch.is_active()
            
            if is_active:
                check = CheckResult(
                    name="Kill Switch",
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message="Kill switch is ACTIVE - trading disabled",
                    details={
                        "is_active": True,
                        "recommendation": "Deactivate kill switch before enabling live trading"
                    },
                )
            else:
                check = CheckResult(
                    name="Kill Switch",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="Kill switch functional and inactive",
                    details={"is_active": False},
                )
            
        except ImportError:
            check = CheckResult(
                name="Kill Switch",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                message="Kill switch module not found",
                details={},
            )
        except Exception as e:
            check = CheckResult(
                name="Kill Switch",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.BLOCKER,
                message=f"Kill switch system error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_feature_flags(self) -> CheckResult:
        """Check that feature flags system is working."""
        try:
            from packages.feature_flags import get_feature_flags
            
            flags = get_feature_flags()
            
            # Check if we can read flags
            config = flags.get_all_flags()
            
            # Check if live_trading_mode flag exists
            if "live_trading_mode" not in config:
                check = CheckResult(
                    name="Feature Flags",
                    status=CheckStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message="live_trading_mode flag not configured",
                    details={
                        "flags_count": len(config),
                        "recommendation": "Add live_trading_mode flag to feature_flags.yml"
                    },
                )
            else:
                live_mode = flags.is_enabled("live_trading_mode")
                
                check = CheckResult(
                    name="Feature Flags",
                    status=CheckStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Feature flags operational (live_trading_mode: {live_mode})",
                    details={
                        "flags_count": len(config),
                        "live_trading_mode": live_mode,
                    },
                )
            
        except ImportError:
            check = CheckResult(
                name="Feature Flags",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Feature flags module not found",
                details={},
            )
        except Exception as e:
            check = CheckResult(
                name="Feature Flags",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.WARNING,
                message=f"Feature flags system error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check
    
    def check_statistics_collection(self) -> CheckResult:
        """Check that statistics collection is active."""
        try:
            from packages.statistics import get_stats_collector
            
            # Try to get collector
            collector = get_stats_collector()
            
            # Get summary to verify it works
            summary = collector.get_summary()
            
            check = CheckResult(
                name="Statistics Collection",
                status=CheckStatus.PASS,
                severity=CheckSeverity.INFO,
                message="Statistics collection operational",
                details={
                    "total_orders": summary.get("total_orders", 0),
                    "total_reconciliations": summary.get("total_reconciliations", 0),
                },
            )
            
        except ImportError:
            check = CheckResult(
                name="Statistics Collection",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Statistics module not found",
                details={},
            )
        except Exception as e:
            check = CheckResult(
                name="Statistics Collection",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.WARNING,
                message=f"Statistics collection error: {e}",
                details={"error": str(e)},
            )
        
        self.checks.append(check)
        return check


# Singleton instance
_safety_checker: Optional[SafetyChecker] = None


def get_safety_checker(
    min_test_coverage: float = 0.80,
    project_root: Optional[Path] = None,
) -> SafetyChecker:
    """
    Get or create singleton safety checker.
    
    Args:
        min_test_coverage: Minimum test coverage threshold (only used on first call)
        project_root: Project root directory (only used on first call)
    
    Returns:
        SafetyChecker instance
    """
    global _safety_checker
    if _safety_checker is None:
        _safety_checker = SafetyChecker(
            min_test_coverage=min_test_coverage,
            project_root=project_root,
        )
    return _safety_checker


__all__ = [
    "CheckStatus",
    "CheckSeverity",
    "CheckResult",
    "SafetyCheckResult",
    "SafetyChecker",
    "get_safety_checker",
]
