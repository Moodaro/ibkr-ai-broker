"""
Tests for advanced risk engine with volatility-aware sizing (KEY TESTS ONLY).

Tests R9-R12:
- R9: Volatility-adjusted position sizing
- R11: Drawdown protection  
- R12: Time-of-day restrictions
"""

import pytest
from datetime import datetime
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
) -> OrderIntent:
    """Helper to create OrderIntent for tests."""
    return OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            type="STK",
            symbol=symbol,
            exchange="SMART",
        ),
        side=side,
        quantity=quantity,
        order_type="MKT",
        reason="Test order for advanced risk engine validation",
        strategy_tag="test_strategy",
    )


# --- R9: Volatility-Adjusted Position Sizing ---


def test_r9_low_volatility_approved(engine, portfolio):
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

    low_vol_metrics = VolatilityMetrics(symbol_volatility=0.10)  # 10% annual

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, low_vol_metrics
    )

    assert decision.decision == Decision.APPROVE
    assert "R9" not in decision.violated_rules
    assert decision.metrics["symbol_volatility"] == 0.10


def test_r9_high_volatility_rejected(engine, portfolio):
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

    high_vol_metrics = VolatilityMetrics(symbol_volatility=0.50)  # 50% annual

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, high_vol_metrics
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules
    assert "Position risk" in decision.reason
    assert "suggested_position_size" in decision.metrics


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
    assert "drawdown" in decision.reason.lower()
    assert decision.metrics["drawdown_pct"] > 15.0


# --- R12: Time-of-Day Restrictions ---


def test_r12_market_hours_approved(engine, portfolio):
    """R12: Trade during normal market hours should be approved."""
    # 10:00 AM = 30 minutes after open, well before close
    trade_time = datetime(2025, 1, 15, 10, 0, 0)

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

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.APPROVE
    assert "R12" not in decision.violated_rules


def test_r12_market_open_rejected(engine, portfolio):
    """R12: Trade within 10 minutes of market open should be rejected."""
    # 9:35 AM = 5 minutes after open (within 10-minute window)
    trade_time = datetime(2025, 1, 15, 9, 35, 0)

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

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R12" in decision.violated_rules
    assert "market open" in decision.reason.lower()


def test_r12_market_close_rejected(engine, portfolio):
    """R12: Trade within 10 minutes of market close should be rejected."""
    # 3:55 PM = 5 minutes before close (within 10-minute window)
    trade_time = datetime(2025, 1, 15, 15, 55, 0)

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

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, None, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R12" in decision.violated_rules
    assert "market close" in decision.reason.lower()


# --- Combined Tests ---


def test_multiple_rules_violated(engine, portfolio):
    """Multiple rules (R9 + R12) can be violated simultaneously."""
    # High volatility position at market open
    trade_time = datetime(2025, 1, 15, 9, 31, 0)  # 1 min after open

    intent = create_order_intent(
        symbol="GME",
        quantity=Decimal("200"),
        side=OrderSide.BUY,
    )

    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("30000"),  # Large + high vol = R9 violation
        net_cash_impact=Decimal("-30000"),
        estimated_commission=Decimal("1.00"),
        estimated_slippage=Decimal("30"),
    )

    high_vol_metrics = VolatilityMetrics(symbol_volatility=0.50)

    decision = engine.evaluate_advanced(
        intent, portfolio, simulation, high_vol_metrics, trade_time
    )

    assert decision.decision == Decision.REJECT
    assert "R9" in decision.violated_rules  # Volatility
    assert "R12" in decision.violated_rules  # Market open
    assert len(decision.violated_rules) == 2
