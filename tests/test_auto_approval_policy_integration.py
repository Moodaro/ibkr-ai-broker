"""
Integration tests for ApprovalService with PolicyChecker.

Tests auto-approval with advanced policy rules.
"""

from datetime import datetime, time, timezone
import json
import pytest

from packages.approval_service import ApprovalService
from packages.approval_service.policy import (
    AutoApprovalPolicy,
    PolicyChecker,
    TimeWindow,
    DCASchedule,
    DayOfWeek,
)
from packages.feature_flags import FeatureFlags
from packages.kill_switch import KillSwitch
from packages.schemas.approval import OrderProposal, OrderState


# Fixtures

@pytest.fixture
def approval_service():
    """Create approval service."""
    return ApprovalService()


@pytest.fixture
def feature_flags():
    """Feature flags with auto-approval enabled."""
    return FeatureFlags(auto_approval=True, auto_approval_max_notional=1000.0)


@pytest.fixture
def kill_switch_inactive():
    """Kill switch inactive."""
    ks = KillSwitch()
    if ks.is_enabled():
        ks.deactivate("test")
    return ks


@pytest.fixture
def whitelist_policy():
    """Policy with SPY/QQQ whitelist and market hours."""
    return AutoApprovalPolicy(
        enabled=True,
        symbol_whitelist=["SPY", "QQQ", "VTI"],
        time_windows=[
            TimeWindow(
                start_time=time(9, 30, 0),
                end_time=time(16, 0, 0),
                days=[DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY, DayOfWeek.THURSDAY, DayOfWeek.FRIDAY],
            )
        ],
        allowed_order_types=["MKT", "LMT"],
    )


@pytest.fixture
def dca_policy():
    """Policy with DCA schedule for SPY."""
    return AutoApprovalPolicy(
        enabled=True,
        dca_schedules=[
            DCASchedule(
                symbols=["SPY", "QQQ"],
                max_order_size=200.0,
                side="BUY",
                order_type="MKT",
            )
        ],
    )


def create_proposal(symbol="SPY", notional=500.0, order_type="MKT", side="BUY", sec_type="ETF"):
    """Helper to create test proposal."""
    intent_json = json.dumps({
        "account_id": "DU123456",
        "symbol": symbol,
        "side": side,
        "quantity": 2,
        "order_type": order_type,
        "sec_type": sec_type,
    })
    
    simulation_json = json.dumps({
        "status": "SUCCESS",
        "gross_notional": str(notional),
        "execution_price": "250.00",
    })
    
    risk_decision_json = json.dumps({
        "decision": "APPROVE",
        "reason": "All checks passed",
    })
    
    return OrderProposal(
        proposal_id=f"test-{symbol}-{notional}",
        correlation_id="test-corr",
        intent_json=intent_json,
        simulation_json=simulation_json,
        risk_decision_json=risk_decision_json,
        state=OrderState.RISK_APPROVED,
    )


# Tests

def test_policy_whitelist_auto_approve(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    whitelist_policy,
):
    """Test auto-approval with whitelisted symbol during market hours."""
    proposal = create_proposal(symbol="SPY", notional=500.0)
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(whitelist_policy)
    
    # Monday 10 AM
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_GRANTED
    assert token is not None
    assert "policy passed" in updated.approval_reason


def test_policy_whitelist_manual_approval(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    whitelist_policy,
):
    """Test manual approval required for non-whitelisted symbol."""
    proposal = create_proposal(symbol="AAPL", notional=500.0)
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(whitelist_policy)
    
    # Monday 10 AM
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "not in whitelist" in updated.approval_reason


def test_policy_time_window_outside_hours(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    whitelist_policy,
):
    """Test manual approval required outside market hours."""
    proposal = create_proposal(symbol="SPY", notional=500.0)
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(whitelist_policy)
    
    # Monday 8 AM (before market open)
    current_time = datetime(2025, 12, 29, 8, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "time windows" in updated.approval_reason


def test_policy_weekend_trading_denied(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    whitelist_policy,
):
    """Test weekend trading denied."""
    proposal = create_proposal(symbol="SPY", notional=500.0)
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(whitelist_policy)
    
    # Saturday 10 AM
    current_time = datetime(2025, 12, 27, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "time windows" in updated.approval_reason


def test_policy_order_type_denied(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    whitelist_policy,
):
    """Test order type not allowed."""
    proposal = create_proposal(symbol="SPY", notional=500.0, order_type="STP")
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(whitelist_policy)
    
    # Monday 10 AM
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "not allowed" in updated.approval_reason


def test_policy_dca_within_limit(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    dca_policy,
):
    """Test DCA order within schedule limit."""
    proposal = create_proposal(symbol="SPY", notional=150.0, order_type="MKT", side="BUY")
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(dca_policy)
    
    # Monday 10 AM
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_GRANTED
    assert token is not None


def test_policy_dca_exceeds_limit(
    approval_service,
    feature_flags,
    kill_switch_inactive,
    dca_policy,
):
    """Test DCA order exceeds schedule limit."""
    proposal = create_proposal(symbol="SPY", notional=250.0, order_type="MKT", side="BUY")
    approval_service.store_proposal(proposal)
    
    policy_checker = PolicyChecker(dca_policy)
    
    # Monday 10 AM
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "exceeds limit" in updated.approval_reason


def test_policy_no_policy_checker_fallback(
    approval_service,
    feature_flags,
    kill_switch_inactive,
):
    """Test auto-approval works without policy checker (backward compat)."""
    proposal = create_proposal(symbol="SPY", notional=500.0)
    approval_service.store_proposal(proposal)
    
    # No policy_checker provided
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=None,  # No policy
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_GRANTED
    assert token is not None
    assert "below threshold" in updated.approval_reason


def test_policy_disabled_requires_manual(
    approval_service,
    feature_flags,
    kill_switch_inactive,
):
    """Test disabled policy requires manual approval."""
    proposal = create_proposal(symbol="SPY", notional=500.0)
    approval_service.store_proposal(proposal)
    
    disabled_policy = AutoApprovalPolicy(enabled=False)
    policy_checker = PolicyChecker(disabled_policy)
    
    current_time = datetime(2025, 12, 29, 10, 0, 0, tzinfo=timezone.utc)
    
    updated, token = approval_service.request_approval(
        proposal.proposal_id,
        feature_flags=feature_flags,
        kill_switch=kill_switch_inactive,
        policy_checker=policy_checker,
        current_time=current_time,
    )
    
    assert updated.state == OrderState.APPROVAL_REQUESTED
    assert token is None
    assert "Policy disabled" in updated.approval_reason
