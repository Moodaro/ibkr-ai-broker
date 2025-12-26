"""
Integration tests for RiskEngine with AdvancedRiskEngine (R1-R12).

Tests that basic risk engine (R1-R8) and advanced risk engine (R9-R12)
work together correctly, combining violations and metrics.
"""

from datetime import datetime, time
from decimal import Decimal

import pytest

from packages.broker_ibkr import Portfolio, Position, Account, Cash
from packages.broker_ibkr.models import (
    Instrument,
    InstrumentType,
    OrderSide,
    OrderType,
)
from packages.risk_engine import (
    AdvancedRiskEngine,
    AdvancedRiskLimits,
    Decision,
    RiskEngine,
    RiskLimits,
    TradingHours,
    VolatilityMetrics,
)
from packages.schemas import OrderIntent
from packages.trade_sim.models import SimulationResult, SimulationStatus


@pytest.fixture
def basic_limits():
    """Basic risk limits (R1-R8)."""
    return RiskLimits(
        max_notional=Decimal("50000"),
        max_position_pct=Decimal("10"),
        max_sector_exposure_pct=Decimal("30"),
        max_slippage_bps=Decimal("50"),
        min_daily_volume=100000,
        max_daily_trades=50,
        max_daily_loss=Decimal("5000"),
    )


@pytest.fixture
def trading_hours():
    """Trading hours configuration."""
    return TradingHours(
        market_open_utc="14:30",
        market_close_utc="21:00",
        allow_pre_market=False,
        allow_after_hours=False,
    )


@pytest.fixture
def advanced_limits():
    """Advanced risk limits (R9-R12)."""
    return AdvancedRiskLimits(
        max_position_volatility=0.02,  # 2% max portfolio risk
        volatility_scaling_enabled=True,
        min_position_size=Decimal("100"),
        max_position_size=Decimal("50000"),
        max_drawdown_pct=10.0,  # 10% max drawdown
        enable_drawdown_halt=True,
        avoid_market_open_minutes=10,
        avoid_market_close_minutes=10,
        enable_time_restrictions=True,
    )


@pytest.fixture
def portfolio():
    """Sample portfolio."""
    return Portfolio(
        account_id="DU12345",
        cash=[
            Cash(
                currency="USD",
                total=Decimal("50000"),
                available=Decimal("50000"),
            )
        ],
        positions=[],
        total_value=Decimal("100000"),
    )


@pytest.fixture
def sample_intent():
    """Sample order intent."""
    return OrderIntent(
        account_id="DU12345",
        instrument=Instrument(
            symbol="AAPL",
            type=InstrumentType.STK,
            currency="USD",
            exchange="NASDAQ",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("50"),
        order_type=OrderType.MKT,
        reason="Integration test order for R1-R12",
        strategy_tag="test_integration",
    )


def test_integrated_engine_all_checks_pass(
    basic_limits, trading_hours, advanced_limits, portfolio, sample_intent
):
    """Test that order passes all R1-R12 checks."""
    # Setup integrated engine
    advanced_engine = AdvancedRiskEngine(
        limits=advanced_limits,
        market_open_time="09:30",
        market_close_time="16:00",
    )
    
    engine = RiskEngine(
        limits=basic_limits,
        trading_hours=trading_hours,
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
        advanced_engine=advanced_engine,
    )
    
    # Simulation: $5000 position, low volatility
    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        estimated_fee=Decimal("5"),
        estimated_slippage=Decimal("10"),
        execution_price=Decimal("100"),
    )
    
    # Low volatility metrics
    volatility_metrics = VolatilityMetrics(
        symbol_volatility=0.15,  # 15% annual volatility
    )
    
    # Evaluate during market hours (15:00 UTC = 10:00 ET)
    current_time = datetime(2025, 12, 26, 15, 0, 0)
    
    decision = engine.evaluate(
        intent=sample_intent,
        portfolio=portfolio,
        simulation=simulation,
        current_time=current_time,
        volatility_metrics=volatility_metrics,
    )
    
    # All checks pass
    assert decision.decision == Decision.APPROVE
    assert decision.violated_rules == []
    assert "R1-R8 + R9-R12" in decision.reason
    # Advanced metrics should be present
    assert "symbol_volatility" in decision.metrics or len(decision.metrics) > 0


def test_engine_without_advanced_backward_compatible(
    basic_limits, trading_hours, portfolio, sample_intent
):
    """Test that RiskEngine works without AdvancedRiskEngine (backward compatible)."""
    # No advanced engine
    engine = RiskEngine(
        limits=basic_limits,
        trading_hours=trading_hours,
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
        # advanced_engine=None (default)
    )
    
    simulation = SimulationResult(
        status=SimulationStatus.SUCCESS,
        gross_notional=Decimal("5000"),
        estimated_fee=Decimal("5"),
        estimated_slippage=Decimal("10"),
    )
    
    # No volatility metrics needed
    current_time = datetime(2025, 12, 26, 15, 0, 0)
    
    decision = engine.evaluate(
        intent=sample_intent,
        portfolio=portfolio,
        simulation=simulation,
        current_time=current_time,
        # volatility_metrics not provided
    )
    
    # Only R1-R8 evaluated
    assert decision.decision == Decision.APPROVE
    assert decision.violated_rules == []
    assert "R1-R8)" in decision.reason  # No R9-R12 suffix
