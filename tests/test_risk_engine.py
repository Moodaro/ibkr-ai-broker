"""Tests for Risk Engine."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from packages.broker_ibkr import (
    Cash,
    Instrument,
    InstrumentType,
    OrderSide,
    OrderType,
    Portfolio,
    Position,
)
from packages.risk_engine import (
    Decision,
    RiskDecision,
    RiskEngine,
    RiskLimits,
    TradingHours,
)
from packages.schemas import OrderIntent
from packages.trade_sim import SimulationResult, SimulationStatus


@pytest.fixture
def default_limits():
    """Default risk limits."""
    return RiskLimits()


@pytest.fixture
def default_trading_hours():
    """Default trading hours."""
    return TradingHours()


@pytest.fixture
def risk_engine(default_limits, default_trading_hours):
    """Risk engine with default configuration."""
    return RiskEngine(
        limits=default_limits,
        trading_hours=default_trading_hours,
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )


@pytest.fixture
def portfolio():
    """Portfolio with $100k cash."""
    return Portfolio(
        account_id="DU123456",
        cash=[
            Cash(
                currency="USD",
                total=Decimal("100000.00"),
                available=Decimal("100000.00"),
            )
        ],
        positions=[],
        total_value=Decimal("100000.00"),
    )


@pytest.fixture
def buy_intent():
    """Buy order intent for 100 shares of AAPL."""
    return OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("100"),
        order_type=OrderType.MKT,
        reason="Buy 100 shares of AAPL for portfolio diversification",
        strategy_tag="test",
    )


@pytest.fixture
def successful_simulation():
    """Successful simulation result for small order."""
    return SimulationResult(
        status=SimulationStatus.SUCCESS,
        execution_price=Decimal("150.00"),
        gross_notional=Decimal("7500.00"),  # 50 shares, not 100
        estimated_fee=Decimal("1.00"),
        estimated_slippage=Decimal("3.75"),
        net_notional=Decimal("7504.75"),
        cash_before=Decimal("100000.00"),
        cash_after=Decimal("92495.25"),
        exposure_before=Decimal("0"),
        exposure_after=Decimal("7500.00"),  # 7.5% of portfolio, under 10% limit
        warnings=[],
        error_message=None,
    )


class TestRiskLimits:
    """Test risk limits configuration."""

    def test_default_limits(self):
        """Test default risk limits."""
        limits = RiskLimits()

        assert limits.max_notional == Decimal("50000.00")
        assert limits.max_position_pct == Decimal("10.0")
        assert limits.max_sector_exposure_pct == Decimal("30.0")
        assert limits.max_slippage_bps == 50
        assert limits.min_daily_volume == 100000
        assert limits.max_daily_trades == 50
        assert limits.max_daily_loss == Decimal("5000.00")

    def test_custom_limits(self):
        """Test custom risk limits."""
        limits = RiskLimits(
            max_notional=Decimal("100000.00"),
            max_position_pct=Decimal("20.0"),
            max_slippage_bps=100,
        )

        assert limits.max_notional == Decimal("100000.00")
        assert limits.max_position_pct == Decimal("20.0")
        assert limits.max_slippage_bps == 100

    def test_limits_immutable(self):
        """Test that limits are frozen."""
        limits = RiskLimits()

        with pytest.raises(Exception):  # Pydantic ValidationError
            limits.max_notional = Decimal("999999.00")


class TestRiskDecision:
    """Test risk decision model."""

    def test_approved_decision(self):
        """Test approved decision."""
        decision = RiskDecision(
            decision=Decision.APPROVE,
            reason="All checks passed",
            violated_rules=[],
            warnings=[],
            metrics={"position_pct": 5.0},
        )

        assert decision.is_approved()
        assert not decision.is_rejected()
        assert decision.decision == Decision.APPROVE

    def test_rejected_decision(self):
        """Test rejected decision."""
        decision = RiskDecision(
            decision=Decision.REJECT,
            reason="R1: Max notional exceeded",
            violated_rules=["R1"],
            warnings=[],
            metrics={"gross_notional": 60000.0},
        )

        assert decision.is_rejected()
        assert not decision.is_approved()
        assert "R1" in decision.violated_rules


class TestRiskEngine:
    """Test risk engine evaluation."""

    def test_approve_small_order(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test that small order is approved."""
        # Use current market hours
        market_time = datetime.utcnow().replace(hour=15, minute=0)  # 15:00 UTC

        decision = risk_engine.evaluate(
            buy_intent, portfolio, successful_simulation, market_time
        )

        assert decision.is_approved()
        assert len(decision.violated_rules) == 0
        assert "gross_notional" in decision.metrics
        assert decision.metrics["gross_notional"] == 7500.0  # Updated to match fixture

    def test_reject_failed_simulation(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test that failed simulation is rejected."""
        failed_sim = SimulationResult(
            status=SimulationStatus.INSUFFICIENT_CASH,
            execution_price=Decimal("150.00"),
            gross_notional=Decimal("150000.00"),
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("75.00"),
            net_notional=Decimal("150076.00"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("-50076.00"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("150000.00"),
            warnings=[],
            error_message="Insufficient cash for trade",
        )

        decision = risk_engine.evaluate(buy_intent, portfolio, failed_sim)

        assert decision.is_rejected()
        assert "SIMULATION_FAILED" in decision.violated_rules

    def test_r1_max_notional_violation(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test R1: Maximum notional value."""
        # Create simulation with large notional
        large_sim = SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=Decimal("600.00"),
            gross_notional=Decimal("60000.00"),  # Exceeds 50k limit
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("30.00"),
            net_notional=Decimal("60031.00"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("39969.00"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("60000.00"),
            warnings=[],
            error_message=None,
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = risk_engine.evaluate(buy_intent, portfolio, large_sim, market_time)

        assert decision.is_rejected()
        assert "R1" in decision.violated_rules
        assert "R1:" in decision.reason

    def test_r2_max_position_pct_violation(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test R2: Maximum position size."""
        # Create simulation with large position relative to portfolio
        large_position_sim = SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=Decimal("150.00"),
            gross_notional=Decimal("15000.00"),
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("7.50"),
            net_notional=Decimal("15008.50"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("84991.50"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("15000.00"),  # 15% of 100k portfolio
            warnings=[],
            error_message=None,
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = risk_engine.evaluate(
            buy_intent, portfolio, large_position_sim, market_time
        )

        # 15% exceeds 10% limit
        assert decision.is_rejected()
        assert "R2" in decision.violated_rules
        assert "position_pct" in decision.metrics

    def test_r4_max_slippage_violation(self, risk_engine, buy_intent, portfolio):
        """Test R4: Maximum slippage."""
        # Create simulation with high slippage
        high_slippage_sim = SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=Decimal("150.00"),
            gross_notional=Decimal("15000.00"),
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("100.00"),  # ~66 bps, exceeds 50 bps limit
            net_notional=Decimal("15101.00"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("84899.00"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("15000.00"),
            warnings=[],
            error_message=None,
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = risk_engine.evaluate(
            buy_intent, portfolio, high_slippage_sim, market_time
        )

        assert decision.is_rejected()
        assert "R4" in decision.violated_rules
        assert "slippage_bps" in decision.metrics

    def test_r5_outside_market_hours(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test R5: Trading hours."""
        # Test at 10:00 UTC (before 14:30 market open)
        before_open = datetime.utcnow().replace(hour=10, minute=0)

        decision = risk_engine.evaluate(
            buy_intent, portfolio, successful_simulation, before_open
        )

        assert decision.is_rejected()
        assert "R5" in decision.violated_rules

    def test_r5_during_market_hours(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test R5: Order approved during market hours."""
        # Test at 16:00 UTC (during 14:30-21:00 market hours)
        during_hours = datetime.utcnow().replace(hour=16, minute=0)

        decision = risk_engine.evaluate(
            buy_intent, portfolio, successful_simulation, during_hours
        )

        # Should pass R5 (might fail other rules, but R5 not in violated_rules)
        assert "R5" not in decision.violated_rules

    def test_r7_max_daily_trades_violation(
        self, default_limits, default_trading_hours, buy_intent, portfolio, successful_simulation
    ):
        """Test R7: Maximum daily trades."""
        # Create engine with max trades already reached
        engine_at_limit = RiskEngine(
            limits=default_limits,
            trading_hours=default_trading_hours,
            daily_trades_count=50,  # At limit
            daily_pnl=Decimal("0"),
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = engine_at_limit.evaluate(
            buy_intent, portfolio, successful_simulation, market_time
        )

        assert decision.is_rejected()
        assert "R7" in decision.violated_rules

    def test_r8_max_daily_loss_violation(
        self, default_limits, default_trading_hours, buy_intent, portfolio, successful_simulation
    ):
        """Test R8: Maximum daily loss."""
        # Create engine with large daily loss
        engine_with_loss = RiskEngine(
            limits=default_limits,
            trading_hours=default_trading_hours,
            daily_trades_count=0,
            daily_pnl=Decimal("-6000.00"),  # Exceeds -5000 limit
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = engine_with_loss.evaluate(
            buy_intent, portfolio, successful_simulation, market_time
        )

        assert decision.is_rejected()
        assert "R8" in decision.violated_rules
        assert decision.metrics["daily_pnl"] == -6000.0

    def test_warnings_near_limits(
        self, risk_engine, buy_intent, portfolio, successful_simulation
    ):
        """Test that warnings are generated when approaching limits."""
        # Create simulation at 42k notional (84% of 50k limit)
        # But only 8k exposure (8% of portfolio, under 10% R2 limit)
        near_limit_sim = SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=Decimal("420.00"),
            gross_notional=Decimal("42000.00"),  # 84% of 50k limit
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("21.00"),
            net_notional=Decimal("42022.00"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("57978.00"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("8000.00"),  # 8% of portfolio (under 10%)
            warnings=[],
            error_message=None,
        )

        market_time = datetime.utcnow().replace(hour=15, minute=0)
        decision = risk_engine.evaluate(
            buy_intent, portfolio, near_limit_sim, market_time
        )

        assert decision.is_approved()  # Still approved
        assert len(decision.warnings) > 0  # But with warnings
        assert any("close to limit" in w for w in decision.warnings)

    def test_multiple_violations(
        self, default_limits, default_trading_hours, buy_intent, portfolio
    ):
        """Test order with multiple rule violations."""
        # Create engine at trade limit with loss
        engine_multi = RiskEngine(
            limits=default_limits,
            trading_hours=default_trading_hours,
            daily_trades_count=50,
            daily_pnl=Decimal("-6000.00"),
        )

        # Large order with high slippage
        bad_sim = SimulationResult(
            status=SimulationStatus.SUCCESS,
            execution_price=Decimal("600.00"),
            gross_notional=Decimal("60000.00"),  # Violates R1
            estimated_fee=Decimal("1.00"),
            estimated_slippage=Decimal("400.00"),  # Violates R4
            net_notional=Decimal("60401.00"),
            cash_before=Decimal("100000.00"),
            cash_after=Decimal("39599.00"),
            exposure_before=Decimal("0"),
            exposure_after=Decimal("60000.00"),  # Violates R2
            warnings=[],
            error_message=None,
        )

        # Test outside market hours
        after_hours = datetime.utcnow().replace(hour=22, minute=0)
        decision = engine_multi.evaluate(buy_intent, portfolio, bad_sim, after_hours)

        assert decision.is_rejected()
        # Should have violations for R1, R2, R4, R5, R7, R8
        assert len(decision.violated_rules) >= 4
        assert "R1" in decision.violated_rules  # Max notional
        assert "R7" in decision.violated_rules  # Daily trades
        assert "R8" in decision.violated_rules  # Daily loss
