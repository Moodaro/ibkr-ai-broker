"""
Tests for advanced risk engine with volatility-aware sizing.

Tests R9-R12:
- R9: Volatility-adjusted position sizing
- R10: Correlation exposure (placeholder)
- R11: Drawdown protection
- R12: Time-of-day restrictions
"""

import pytest
from datetime import datetime, time, timedelta
from decimal import Decimal

from packages.broker_ibkr import Portfolio
from packages.broker_ibkr.models import Position, Cash, Instrument, OrderSide
from packages.schemas import OrderIntent
from packages.trade_sim import SimulationResult
from packages.trade_sim.models import SimulationStatus
from packages.risk_engine.advanced import (
    AdvancedRiskEngine,
    AdvancedRiskLimits,
    VolatilityMetrics,
)
from packages.risk_engine.models import Decision


@pytest.fixture
def default_limits():
    """Default advanced risk limits."""
    return AdvancedRiskLimits(
        max_position_volatility=0.02,  # 2% portfolio risk
        volatility_scaling_enabled=True,
        min_position_size=Decimal("100"),
        max_position_size=Decimal("50000"),
        max_correlated_exposure_pct=30.0,
        max_drawdown_pct=10.0,
        enable_drawdown_halt=True,
        avoid_market_open_minutes=10,
        avoid_market_close_minutes=10,
        enable_time_restrictions=True,
    )


@pytest.fixture
def engine(default_limits):
    """Advanced risk engine instance."""
    return AdvancedRiskEngine(
        limits=default_limits,
        high_water_mark=Decimal("100000"),
        market_open_time="09:30",
        market_close_time="16:00",
    )


@pytest.fixture
def portfolio():
    """Sample portfolio."""
    return Portfolio(
        account_id="DU12345",
        total_value=Decimal("100000"),
        cash=[
            Cash(
                currency="USD",
                available=Decimal("50000"),
                total=Decimal("50000"),
            )
        ],
        positions=[
            Position(
                instrument=Instrument(
                    type="STK",
                    symbol="SPY",
                    exchange="SMART",
                ),
                quantity=Decimal("100"),
                average_cost=Decimal("400"),
                market_value=Decimal("45000"),
                unrealized_pnl=Decimal("5000"),
            )
        ],
    )


def create_order_intent(
    symbol: str,
    quantity: Decimal,
    side: OrderSide,
    order_type: str = "MKT",
    reason: str = "Test order for risk engine validation",
    strategy_tag: str = "test_strategy",
    sec_type: str = "STK",
) -> OrderIntent:
    """Helper to create OrderIntent for tests."""
    return OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type=sec_type,
            symbol=symbol,
            exchange="SMART",
        ),
        side=side,
        quantity=quantity,
        order_type=order_type,
        reason=reason,
        strategy_tag=strategy_tag,
    )


@pytest.fixture
def low_vol_metrics():
    """Low volatility metrics (10% annual)."""
    return VolatilityMetrics(symbol_volatility=0.10)


@pytest.fixture
def high_vol_metrics():
    """High volatility metrics (50% annual)."""
    return VolatilityMetrics(symbol_volatility=0.50)


@pytest.fixture
def market_vol_with_beta():
    """Market volatility with beta (VIX-based)."""
    return VolatilityMetrics(
        market_volatility=0.20,  # 20% market vol
        beta=1.5,  # 1.5x market sensitivity
    )


# --- R9: Volatility-Adjusted Position Sizing ---


def test_r9_low_volatility_approved(engine, portfolio, low_vol_metrics):
    """R9: Low volatility position should be approved."""
    intent = create_order_intent(
        symbol="AAPL",
        quantity=Decimal("50"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("10000"),  # $10k position
        net_cash_impact=Decimal("-10000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("10"),
    )

    # 10% vol * $10k = ~$630 daily risk
    # $630 / $100k portfolio = 0.63% risk < 2% limit
    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, low_vol_metrics
    )

    assert decision.decision == Decision.APPROVE
    assert "R9" not in decision.violated_rules
    assert decision.metrics["symbol_volatility"] == 0.10
    assert decision.metrics["position_risk_pct"] < 2.0


def test_r9_high_volatility_rejected(engine, portfolio, high_vol_metrics):
    """R9: High volatility position should be rejected."""
    intent = create_order_intent(
        symbol="TSLA",
        quantity=Decimal("100"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("20000"),  # $20k position
        net_cash_impact=Decimal("-20000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("20"),
    )

    # 50% vol * $20k = $10,000 position risk
    # $10,000 / $100k portfolio = 10% risk > 2% limit
    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, high_vol_metrics
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules
    assert "Position risk 10" in decision.reason  # Approx 10%
    assert "suggested_position_size" in decision.metrics


def test_r9_volatility_scaling_calculates_suggested_size(
    engine, portfolio, high_vol_metrics
):
    """R9: Should calculate suggested position size when rejected."""
    intent = create_order_intent(
        symbol="GME",
        quantity=Decimal("500"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("30000"),
        net_cash_impact=Decimal("-30000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("30"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, high_vol_metrics
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules

    # Suggested size should be: portfolio * max_risk / volatility
    # $100k * 0.02 / 0.50 = $4,000
    suggested = decision.metrics["suggested_position_size"]
    assert 3800 < suggested < 4200  # Approx $4,000


def test_r9_beta_based_volatility(engine, portfolio, market_vol_with_beta):
    """R9: Should calculate volatility using beta when symbol vol unavailable."""
    intent = create_order_intent(
        symbol="NVDA",
        quantity=Decimal("50"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("15000"),
        net_cash_impact=Decimal("-15000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("15"),
    )

    # Effective vol = 1.5 * 0.20 = 0.30 (30%)
    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, market_vol_with_beta
    )

    # 30% vol * $15k = ~$2,840 daily risk
    # $2,840 / $100k = 2.84% > 2% limit
    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules
    assert decision.metrics["symbol_volatility"] == pytest.approx(0.30, abs=0.01)


def test_r9_no_volatility_data_skips_check(engine, portfolio):
    """R9: Should skip check when no volatility data available."""
    intent = create_order_intent(
        symbol="XYZ",
        quantity=Decimal("100"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("25000"),
        net_cash_impact=Decimal("-25000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("25"),
    )

    # No volatility metrics provided
    decision = engine.evaluate_advanced(intent, portfolio, simulation, None)

    # Should approve (other checks not violated)
    assert decision.decision == Decision.APPROVE
    assert "R9" not in decision.violated_rules


def test_r9_position_below_minimum_rejected(engine, portfolio, low_vol_metrics):
    """R9: Position below minimum size should be rejected."""
    intent = create_order_intent(
        symbol="PENNY",
        quantity=Decimal("10"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("50"),  # $50 < $100 minimum
        net_cash_impact=Decimal("-50"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("0.50"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, low_vol_metrics
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules
    assert "below minimum $100" in decision.reason


def test_r9_position_above_maximum_rejected(engine, portfolio, low_vol_metrics):
    """R9: Position above maximum size should be rejected."""
    intent = create_order_intent(
        symbol="BRK.A",
        quantity=Decimal("1"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("600000"),  # $600k > $50k maximum
        net_cash_impact=Decimal("-600000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("100"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, low_vol_metrics
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules
    assert "exceeds maximum $50,000" in decision.reason


def test_r9_high_volatility_warning_non_blocking(engine, portfolio):
    """R9: High volatility (>30%) should trigger warning but not block."""
    intent = create_order_intent(
        symbol="MEME",
        quantity=Decimal("10"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("1000"),  # Small position
        net_cash_impact=Decimal("-1000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("10"),
    )

    # 80% volatility but small size passes risk check
    extreme_vol = VolatilityMetrics(symbol_volatility=0.80)

    decision = engine.evaluate_advanced(intent, portfolio, simulation, extreme_vol)

    # Should approve (position is small enough)
    assert decision.decision == Decision.APPROVE
    assert "R9" not in decision.violated_rules

    # But should have warning
    assert len(decision.warnings) > 0
    assert "High volatility" in decision.warnings[0]


# --- R11: Drawdown Protection ---


def test_r11_within_drawdown_limit_approved(default_limits, portfolio):
    """R11: Portfolio within drawdown limit should be approved."""
    # Portfolio at $100k, high water mark at $105k = 4.76% drawdown
    engine = AdvancedRiskEngine(
        limits=default_limits,
        high_water_mark=Decimal("105000"),
    )

    intent = create_order_intent(
        symbol="SPY",
        quantity=Decimal("10"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(intent, portfolio, simulation)

    assert decision.decision == Decision.APPROVE
    assert "R11" not in decision.violated_rules
    assert decision.metrics["drawdown_pct"] < 10.0


def test_r11_exceeds_drawdown_limit_rejected(default_limits, portfolio):
    """R11: Portfolio exceeding drawdown limit should be rejected."""
    # Portfolio at $100k, high water mark at $120k = 16.67% drawdown
    engine = AdvancedRiskEngine(
        limits=default_limits,
        high_water_mark=Decimal("120000"),
    )

    intent = create_order_intent(
        symbol="SPY",
        quantity=Decimal("10"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(intent, portfolio, simulation)

    assert decision.decision == Decision.REJECT
    assert "R11" in decision.violated_rules
    assert "drawdown 16.67% exceeds limit 10.0%" in decision.reason
    assert decision.metrics["drawdown_pct"] == pytest.approx(16.67, abs=0.01)


def test_r11_updates_high_water_mark(default_limits):
    """R11: Should update high water mark when portfolio value increases."""
    # Start with $100k HWM
    engine = AdvancedRiskEngine(
        limits=default_limits,
        high_water_mark=Decimal("100000"),
    )

    # Portfolio now at $110k (new high)
    portfolio = Portfolio(
        account_id="DU12345",
        total_value=Decimal("110000"),
        cash=[
            Cash(
                currency="USD",
                available=Decimal("110000"),
                total=Decimal("110000"),
            )
        ],
        positions=[],
    )

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(intent, portfolio, simulation)

    assert decision.decision == Decision.APPROVE
    assert "R11" not in decision.violated_rules
    assert engine.high_water_mark == Decimal("110000")  # Updated
    assert decision.metrics["drawdown_pct"] == 0.0


def test_r11_no_high_water_mark_initializes(default_limits, portfolio):
    """R11: Should initialize high water mark from current portfolio."""
    # No HWM provided
    engine = AdvancedRiskEngine(
        limits=default_limits,
        high_water_mark=None,
    )

    intent = create_order_intent(
        symbol="SPY",
        quantity=Decimal("10"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(intent, portfolio, simulation)

    assert decision.decision == Decision.APPROVE
    assert "R11" not in decision.violated_rules
    assert engine.high_water_mark == portfolio.total_value  # Initialized
    assert decision.metrics["drawdown_pct"] == 0.0


# --- R12: Time-of-Day Restrictions ---


def test_r12_market_hours_approved(engine, portfolio):
    """R12: Trade during normal market hours should be approved."""
    # 10:00 AM = 30 minutes after open, well before close
    trade_time = datetime(2025, 1, 15, 10, 0, 0)

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.APPROVE
    assert "R12" not in decision.violated_rules
    assert decision.metrics["trade_time"] == "10:00:00"


def test_r12_market_open_rejected(engine, portfolio):
    """R12: Trade within 10 minutes of market open should be rejected."""
    # 9:35 AM = 5 minutes after open (within 10-minute window)
    trade_time = datetime(2025, 1, 15, 9, 35, 0)

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R12" in decision.violated_rules
    assert "Too close to market open (5 min)" in decision.reason
    assert "Wait 5 more minutes" in decision.reason


def test_r12_market_close_rejected(engine, portfolio):
    """R12: Trade within 10 minutes of market close should be rejected."""
    # 3:55 PM = 5 minutes before close (within 10-minute window)
    trade_time = datetime(2025, 1, 15, 15, 55, 0)

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R12" in decision.violated_rules
    assert "Too close to market close (5 min remaining)" in decision.reason
    assert "restricted in final 10 minutes" in decision.reason


def test_r12_exact_market_open_rejected(engine, portfolio):
    """R12: Trade exactly at market open should be rejected."""
    # Exactly 9:30 AM
    trade_time = datetime(2025, 1, 15, 9, 30, 0)

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R12" in decision.violated_rules
    assert "Too close to market open (0 min)" in decision.reason


def test_r12_disabled_allows_open_close(default_limits, portfolio):
    """R12: Disabled time restrictions should allow open/close trades."""
    # Disable R12
    limits = AdvancedRiskLimits(
        enable_time_restrictions=False,
    )

    engine = AdvancedRiskEngine(limits=limits)

    # Try trading at market open
    trade_time = datetime(2025, 1, 15, 9, 30, 0)

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="SPY",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    # Should approve (R12 disabled, other checks pass)
    assert decision.decision == Decision.APPROVE
    assert "R12" not in decision.violated_rules


# --- Combined Tests ---


def test_multiple_rules_violated(engine, portfolio, high_vol_metrics):
    """Multiple rules (R9 + R12) can be violated simultaneously."""
    # High volatility position at market open
    trade_time = datetime(2025, 1, 15, 9, 31, 0)  # 1 min after open

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="GME",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("200"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("30000"),  # Large + high vol = R9 violation
        net_cash_impact=Decimal("-30000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("30"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, high_vol_metrics, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules  # Volatility
    assert "R12" in decision.violated_rules  # Market open
    assert len(decision.violated_rules) == 2


def test_all_advanced_checks_pass(engine, portfolio, low_vol_metrics):
    """All advanced risk checks pass for safe trade."""
    # Safe trade: low vol, good time, normal size, no drawdown
    trade_time = datetime(2025, 1, 15, 11, 0, 0)  # Mid-morning

    intent = OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol="VTI",
            exchange="SMART",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("20"),
        order_type="MKT",
        reason="Test order for risk engine validation",
        strategy_tag="test_strategy",
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        net_cash_impact=Decimal("-5000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("5"),
    )

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, low_vol_metrics, trade_time
    )

    assert decision.decision == Decision.APPROVE
    assert len(decision.violated_rules) == 0
    assert "All advanced risk checks passed" in decision.reason
