"""
Tests for auto-approval policy checker.

Tests cover:
- Symbol whitelist/blacklist
- Security type restrictions
- Time window checks
- Order type restrictions
- DCA schedule matching
- Position size limits
- Combined policy checks
"""

from datetime import time
import pytest

from packages.approval_service.policy import (
    AutoApprovalPolicy,
    PolicyChecker,
    TimeWindow,
    DCASchedule,
    DayOfWeek,
)


# Fixtures

@pytest.fixture
def basic_policy():
    """Basic policy with symbol whitelist and time windows."""
    return AutoApprovalPolicy(
        enabled=True,
        symbol_whitelist=["SPY", "QQQ", "VTI"],
        symbol_blacklist=["TSLA"],
        allowed_sec_types=["STK", "ETF"],
        time_windows=[
            TimeWindow(
                start_time=time(9, 30, 0),
                end_time=time(16, 0, 0),
                days=[DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY, DayOfWeek.THURSDAY, DayOfWeek.FRIDAY],
                timezone="America/New_York",
            )
        ],
        allowed_order_types=["MKT", "LMT"],
        max_position_pct=5.0,
    )


@pytest.fixture
def dca_policy():
    """Policy with DCA schedules."""
    return AutoApprovalPolicy(
        enabled=True,
        symbol_whitelist=None,  # All symbols allowed
        dca_schedules=[
            DCASchedule(
                symbols=["SPY", "QQQ"],
                max_order_size=200.0,
                side="BUY",
                order_type="MKT",
            ),
            DCASchedule(
                symbols=["VTI", "AGG"],
                max_order_size=150.0,
                side="BUY",
                order_type="MKT",
            ),
        ],
    )


@pytest.fixture
def disabled_policy():
    """Policy with enabled=False."""
    return AutoApprovalPolicy(enabled=False)


# Symbol checks

def test_symbol_whitelist_allowed(basic_policy):
    """Test symbol in whitelist is allowed."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_symbol("SPY")
    assert ok is True
    assert reason == ""


def test_symbol_whitelist_denied(basic_policy):
    """Test symbol not in whitelist is denied."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_symbol("AAPL")
    assert ok is False
    assert "not in whitelist" in reason


def test_symbol_blacklist_denied(basic_policy):
    """Test blacklisted symbol is denied (takes precedence over whitelist)."""
    # Add TSLA to whitelist (but it's in blacklist)
    basic_policy.symbol_whitelist.append("TSLA")
    
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_symbol("TSLA")
    assert ok is False
    assert "blacklisted" in reason


def test_symbol_no_whitelist():
    """Test all symbols allowed when no whitelist configured."""
    policy = AutoApprovalPolicy(
        enabled=True,
        symbol_whitelist=None,  # No whitelist
        symbol_blacklist=[],
    )
    
    checker = PolicyChecker(policy)
    ok, reason = checker.check_symbol("AAPL")
    assert ok is True


# Security type checks

def test_security_type_allowed(basic_policy):
    """Test allowed security type."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_security_type("ETF")
    assert ok is True


def test_security_type_denied(basic_policy):
    """Test forbidden security type."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_security_type("OPT")
    assert ok is False
    assert "not allowed" in reason


# Time window checks

def test_time_window_allowed(basic_policy):
    """Test time within allowed window."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_time_window(time(10, 0, 0), DayOfWeek.MONDAY)
    assert ok is True


def test_time_window_before_open(basic_policy):
    """Test time before market open."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_time_window(time(9, 0, 0), DayOfWeek.MONDAY)
    assert ok is False
    assert "Outside allowed time windows" in reason


def test_time_window_after_close(basic_policy):
    """Test time after market close."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_time_window(time(17, 0, 0), DayOfWeek.MONDAY)
    assert ok is False
    assert "Outside allowed time windows" in reason


def test_time_window_weekend(basic_policy):
    """Test trading on weekend."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_time_window(time(10, 0, 0), DayOfWeek.SATURDAY)
    assert ok is False
    assert "Outside allowed time windows" in reason


def test_time_window_no_restrictions():
    """Test no time windows = always allowed."""
    policy = AutoApprovalPolicy(enabled=True, time_windows=[])
    
    checker = PolicyChecker(policy)
    ok, reason = checker.check_time_window(time(2, 0, 0), DayOfWeek.SUNDAY)
    assert ok is True


# Order type checks

def test_order_type_allowed(basic_policy):
    """Test allowed order type."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_order_type("MKT")
    assert ok is True


def test_order_type_denied(basic_policy):
    """Test forbidden order type."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_order_type("STP")
    assert ok is False
    assert "not allowed" in reason


# DCA schedule checks

def test_dca_schedule_match_within_limit(dca_policy):
    """Test DCA order within size limit."""
    checker = PolicyChecker(dca_policy)
    ok, reason = checker.check_dca_schedule("SPY", "BUY", "MKT", 150.0)
    assert ok is True
    assert "DCA schedule" in reason


def test_dca_schedule_match_exceeds_limit(dca_policy):
    """Test DCA order exceeds size limit."""
    checker = PolicyChecker(dca_policy)
    ok, reason = checker.check_dca_schedule("SPY", "BUY", "MKT", 250.0)
    assert ok is False
    assert "exceeds limit" in reason


def test_dca_schedule_no_match_symbol(dca_policy):
    """Test non-DCA symbol (not a blocking condition)."""
    checker = PolicyChecker(dca_policy)
    ok, reason = checker.check_dca_schedule("AAPL", "BUY", "MKT", 500.0)
    assert ok is True  # No matching schedule = N/A


def test_dca_schedule_no_match_side(dca_policy):
    """Test DCA symbol but wrong side (SELL instead of BUY)."""
    checker = PolicyChecker(dca_policy)
    ok, reason = checker.check_dca_schedule("SPY", "SELL", "MKT", 100.0)
    assert ok is True  # No matching schedule = N/A


def test_dca_schedule_no_match_order_type(dca_policy):
    """Test DCA symbol but wrong order type (LMT instead of MKT)."""
    checker = PolicyChecker(dca_policy)
    ok, reason = checker.check_dca_schedule("SPY", "BUY", "LMT", 100.0)
    assert ok is True  # No matching schedule = N/A


# Position size checks

def test_position_size_within_limit(basic_policy):
    """Test position size within portfolio % limit."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_position_size(5000.0, 100000.0)  # 5% of $100k
    assert ok is True


def test_position_size_exceeds_limit(basic_policy):
    """Test position size exceeds portfolio % limit."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_position_size(6000.0, 100000.0)  # 6% of $100k
    assert ok is False
    assert "exceeds limit" in reason


def test_position_size_no_limit():
    """Test no position size limit configured."""
    policy = AutoApprovalPolicy(enabled=True, max_position_pct=None)
    
    checker = PolicyChecker(policy)
    ok, reason = checker.check_position_size(50000.0, 100000.0)  # 50% of portfolio
    assert ok is True


def test_position_size_no_portfolio_nav(basic_policy):
    """Test fail-safe when portfolio NAV unavailable."""
    checker = PolicyChecker(basic_policy)
    ok, reason = checker.check_position_size(5000.0, None)
    assert ok is False
    assert "NAV unavailable" in reason


# Combined checks

def test_check_all_passes(basic_policy):
    """Test all checks pass."""
    checker = PolicyChecker(basic_policy)
    
    ok, reasons = checker.check_all(
        symbol="SPY",
        sec_type="ETF",
        side="BUY",
        order_type="MKT",
        notional=4000.0,
        current_time=time(10, 0, 0),
        current_day=DayOfWeek.MONDAY,
        portfolio_nav=100000.0,
    )
    
    assert ok is True
    assert len(reasons) == 0


def test_check_all_multiple_failures(basic_policy):
    """Test multiple check failures."""
    checker = PolicyChecker(basic_policy)
    
    ok, reasons = checker.check_all(
        symbol="AAPL",  # Not in whitelist
        sec_type="OPT",  # Not allowed
        side="BUY",
        order_type="STP",  # Not allowed
        notional=7000.0,  # Exceeds position % limit
        current_time=time(8, 0, 0),  # Before market open
        current_day=DayOfWeek.MONDAY,
        portfolio_nav=100000.0,
    )
    
    assert ok is False
    assert len(reasons) == 5  # 5 failures
    assert any("whitelist" in r for r in reasons)
    assert any("not allowed" in r for r in reasons)
    assert any("time windows" in r for r in reasons)
    assert any("exceeds limit" in r for r in reasons)


def test_check_all_disabled_policy(disabled_policy):
    """Test disabled policy rejects all checks."""
    checker = PolicyChecker(disabled_policy)
    
    ok, reasons = checker.check_all(
        symbol="SPY",
        sec_type="ETF",
        side="BUY",
        order_type="MKT",
        notional=100.0,
        current_time=time(10, 0, 0),
        current_day=DayOfWeek.MONDAY,
        portfolio_nav=100000.0,
    )
    
    assert ok is False
    assert "Policy disabled" in reasons


def test_check_all_with_dca(dca_policy):
    """Test all checks with DCA schedule."""
    checker = PolicyChecker(dca_policy)
    
    ok, reasons = checker.check_all(
        symbol="SPY",
        sec_type="ETF",
        side="BUY",
        order_type="MKT",
        notional=150.0,  # Within DCA limit ($200)
        current_time=time(10, 0, 0),
        current_day=DayOfWeek.MONDAY,
        portfolio_nav=None,  # No position % check
    )
    
    assert ok is True
    assert len(reasons) == 0


def test_check_all_dca_exceeds_limit(dca_policy):
    """Test DCA order exceeds schedule limit."""
    checker = PolicyChecker(dca_policy)
    
    ok, reasons = checker.check_all(
        symbol="SPY",
        sec_type="ETF",
        side="BUY",
        order_type="MKT",
        notional=250.0,  # Exceeds DCA limit ($200)
        current_time=time(10, 0, 0),
        current_day=DayOfWeek.MONDAY,
        portfolio_nav=None,
    )
    
    assert ok is False
    assert any("exceeds limit" in r for r in reasons)
