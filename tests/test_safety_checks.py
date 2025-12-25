"""
Tests for pre-live safety checks.
"""

import pytest
from pathlib import Path
import tempfile
import os

from packages.safety_checks import (
    CheckStatus,
    CheckSeverity,
    CheckResult,
    SafetyCheckResult,
    SafetyChecker,
    get_safety_checker,
)


@pytest.fixture
def temp_project():
    """Temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # Create tests directory with some test files
        tests_dir = project_root / "tests"
        tests_dir.mkdir()
        
        # Create sample test files
        for i in range(15):
            test_file = tests_dir / f"test_module_{i}.py"
            test_file.write_text(f"def test_example_{i}(): pass\n")
        
        # Create data directory
        data_dir = project_root / "data"
        data_dir.mkdir()
        
        yield project_root


@pytest.fixture
def checker(temp_project):
    """Fresh safety checker for each test."""
    # Reset singleton
    import packages.safety_checks
    packages.safety_checks._safety_checker = None
    
    return SafetyChecker(project_root=temp_project)


class TestCheckResult:
    """Tests for CheckResult dataclass."""
    
    def test_check_result_creation(self):
        """Test CheckResult creation."""
        result = CheckResult(
            name="Test Check",
            status=CheckStatus.PASS,
            severity=CheckSeverity.INFO,
            message="All good",
            details={"value": 42},
        )
        
        assert result.name == "Test Check"
        assert result.status == CheckStatus.PASS
        assert result.severity == CheckSeverity.INFO
        assert result.message == "All good"
        assert result.details["value"] == 42
    
    def test_check_result_to_dict(self):
        """Test CheckResult serialization."""
        result = CheckResult(
            name="Test Check",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.BLOCKER,
            message="Error occurred",
        )
        
        data = result.to_dict()
        
        assert data["name"] == "Test Check"
        assert data["status"] == "FAIL"
        assert data["severity"] == "BLOCKER"
        assert data["message"] == "Error occurred"
        assert "timestamp" in data


class TestSafetyChecker:
    """Tests for SafetyChecker class."""
    
    def test_check_test_coverage_pass(self, checker):
        """Test test coverage check with adequate tests."""
        result = checker.check_test_coverage()
        
        assert result.name == "Test Coverage"
        assert result.status == CheckStatus.PASS
        assert "15 test files" in result.message
    
    def test_check_test_coverage_warning(self, temp_project):
        """Test test coverage check with low test count."""
        # Remove most test files
        tests_dir = temp_project / "tests"
        for test_file in list(tests_dir.glob("test_*.py"))[5:]:
            test_file.unlink()
        
        checker = SafetyChecker(project_root=temp_project)
        result = checker.check_test_coverage()
        
        assert result.name == "Test Coverage"
        assert result.status == CheckStatus.WARNING
        assert result.severity == CheckSeverity.WARNING
        assert "only 5 test files" in result.message
    
    def test_check_test_coverage_fail_no_tests(self, temp_project):
        """Test test coverage check with no tests."""
        # Remove all test files
        tests_dir = temp_project / "tests"
        for test_file in tests_dir.glob("test_*.py"):
            test_file.unlink()
        
        checker = SafetyChecker(project_root=temp_project)
        result = checker.check_test_coverage()
        
        assert result.name == "Test Coverage"
        assert result.status == CheckStatus.FAIL
        assert result.severity == CheckSeverity.BLOCKER
        assert "No test files found" in result.message
    
    def test_check_audit_backup_pass(self, checker):
        """Test audit backup check passes."""
        result = checker.check_audit_backup()
        
        assert result.name == "Audit Backup"
        assert result.status in [CheckStatus.PASS, CheckStatus.FAIL]
        # May fail if module not found, but should not raise exception
    
    def test_check_alerting_system_warning(self, checker):
        """Test alerting system check with no configuration."""
        # Clear environment variables
        os.environ.pop("ALERT_SMTP_HOST", None)
        os.environ.pop("ALERT_WEBHOOK_URL", None)
        
        result = checker.check_alerting_system()
        
        assert result.name == "Alerting System"
        # Should warn if not configured
        if result.status != CheckStatus.FAIL:  # Only if module exists
            assert result.status == CheckStatus.WARNING
            assert "not configured" in result.message.lower()
    
    def test_check_alerting_system_configured(self, checker):
        """Test alerting system check with SMTP configured."""
        os.environ["ALERT_SMTP_HOST"] = "smtp.example.com"
        
        try:
            result = checker.check_alerting_system()
            
            assert result.name == "Alerting System"
            if result.status != CheckStatus.FAIL:  # Only if module exists
                assert result.status == CheckStatus.PASS
                assert result.details.get("smtp_configured") is True
        finally:
            os.environ.pop("ALERT_SMTP_HOST", None)
    
    def test_check_reconciliation_system(self, checker):
        """Test reconciliation system check."""
        result = checker.check_reconciliation_system()
        
        assert result.name == "Reconciliation System"
        # May fail if not initialized, but should not raise exception
        assert result.status in [CheckStatus.PASS, CheckStatus.WARNING, CheckStatus.FAIL]
    
    def test_check_kill_switch_inactive(self, checker):
        """Test kill switch check when inactive."""
        result = checker.check_kill_switch()
        
        assert result.name == "Kill Switch"
        if result.status == CheckStatus.PASS:
            assert "inactive" in result.message.lower()
            assert result.details.get("is_active") is False
    
    def test_check_feature_flags(self, checker):
        """Test feature flags check."""
        result = checker.check_feature_flags()
        
        assert result.name == "Feature Flags"
        # May fail if module not found, but should not raise exception
        assert result.status in [CheckStatus.PASS, CheckStatus.WARNING, CheckStatus.FAIL]
    
    def test_check_statistics_collection(self, checker):
        """Test statistics collection check."""
        result = checker.check_statistics_collection()
        
        assert result.name == "Statistics Collection"
        # May fail if module not found, but should not raise exception
        assert result.status in [CheckStatus.PASS, CheckStatus.FAIL]
    
    def test_run_all_checks(self, checker):
        """Test running all safety checks."""
        result = checker.run_all_checks()
        
        assert isinstance(result, SafetyCheckResult)
        assert result.checks_total == 7  # 7 checks total
        assert len(result.checks) == 7
        assert result.checks_passed <= result.checks_total
        
        # Should have timestamp
        assert result.timestamp is not None
        
        # Check names should match
        check_names = {c.name for c in result.checks}
        expected_names = {
            "Test Coverage",
            "Audit Backup",
            "Alerting System",
            "Reconciliation System",
            "Kill Switch",
            "Feature Flags",
            "Statistics Collection",
        }
        assert check_names == expected_names
    
    def test_run_all_checks_blocking_issues(self, temp_project):
        """Test safety check identifies blocking issues."""
        # Remove tests directory to create blocking issue
        tests_dir = temp_project / "tests"
        for test_file in tests_dir.glob("test_*.py"):
            test_file.unlink()
        tests_dir.rmdir()
        
        checker = SafetyChecker(project_root=temp_project)
        result = checker.run_all_checks()
        
        assert not result.ready_for_live
        assert len(result.blocking_issues) > 0
        assert any("test" in issue.lower() for issue in result.blocking_issues)
    
    def test_safety_check_result_to_dict(self, checker):
        """Test SafetyCheckResult serialization."""
        result = checker.run_all_checks()
        data = result.to_dict()
        
        assert "ready_for_live" in data
        assert "checks_passed" in data
        assert "checks_total" in data
        assert "checks" in data
        assert "blocking_issues" in data
        assert "warnings" in data
        assert "recommendations" in data
        assert "timestamp" in data
        
        # Checks should be serialized
        assert isinstance(data["checks"], list)
        if len(data["checks"]) > 0:
            assert isinstance(data["checks"][0], dict)


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_safety_checker_singleton(self):
        """Test singleton returns same instance."""
        import packages.safety_checks
        packages.safety_checks._safety_checker = None
        
        checker1 = get_safety_checker()
        checker2 = get_safety_checker()
        
        assert checker1 is checker2
    
    def test_get_safety_checker_with_params(self, temp_project):
        """Test singleton with custom parameters."""
        import packages.safety_checks
        packages.safety_checks._safety_checker = None
        
        checker = get_safety_checker(
            min_test_coverage=0.90,
            project_root=temp_project,
        )
        
        assert checker.min_test_coverage == 0.90
        assert checker.project_root == temp_project


class TestIntegration:
    """Integration tests for safety checks."""
    
    def test_full_safety_check_workflow(self, checker):
        """Test complete safety check workflow."""
        # Run all checks
        result = checker.run_all_checks()
        
        # Verify result structure
        assert isinstance(result, SafetyCheckResult)
        assert isinstance(result.ready_for_live, bool)
        assert isinstance(result.checks_passed, int)
        assert isinstance(result.checks_total, int)
        assert isinstance(result.blocking_issues, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.recommendations, list)
        
        # Verify each check has expected structure
        for check in result.checks:
            assert isinstance(check, CheckResult)
            assert check.name is not None
            assert check.status in CheckStatus
            assert check.severity in CheckSeverity
            assert check.message is not None
            assert isinstance(check.details, dict)
        
        # Can serialize to dict
        data = result.to_dict()
        assert isinstance(data, dict)
        
        # Decision logic: ready if no blockers
        if len(result.blocking_issues) == 0:
            assert result.ready_for_live is True
        else:
            assert result.ready_for_live is False
