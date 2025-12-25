"""Tests for trade simulator."""

from decimal import Decimal

import pytest

from packages.broker_ibkr import (
    Account,
    Cash,
    InstrumentType,
    Instrument,
    OrderSide,
    OrderType,
    Portfolio,
    Position,
    TimeInForce,
)
from packages.schemas import OrderConstraints, OrderIntent
from packages.trade_sim import (
    SimulationConfig,
    SimulationStatus,
    TradeSimulator,
)


@pytest.fixture
def simulator():
    """Create simulator with default config."""
    return TradeSimulator()


@pytest.fixture
def custom_simulator():
    """Create simulator with custom fees."""
    config = SimulationConfig(
        fee_per_share=Decimal("0.01"),
        min_fee=Decimal("2.0"),
        base_slippage_bps=Decimal("10"),
    )
    return TradeSimulator(config)


@pytest.fixture
def portfolio():
    """Create sample portfolio."""
    return Portfolio(
        account_id="DU123456",
        cash=[
            Cash(
                currency="USD",
                total=Decimal("100000.00"),
                available=Decimal("100000.00"),
            ),
        ],
        positions=[
            Position(
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                quantity=Decimal("100"),
                average_cost=Decimal("450.00"),
                market_value=Decimal("46000.00"),
                unrealized_pnl=Decimal("1000.00"),
            ),
        ],
        total_value=Decimal("146000.00"),
    )


@pytest.fixture
def buy_intent():
    """Create sample buy order intent."""
    return OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side=OrderSide.BUY,
        quantity=Decimal("50"),
        order_type=OrderType.MKT,
        reason="Buy AAPL for portfolio diversification and growth exposure",
        strategy_tag="test_buy",
    )


@pytest.fixture
def sell_intent():
    """Create sample sell order intent."""
    return OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="SPY",
            exchange="SMART",
            currency="USD",
        ),
        side=OrderSide.SELL,
        quantity=Decimal("50"),
        order_type=OrderType.MKT,
        reason="Sell SPY to reduce portfolio exposure to equities",
        strategy_tag="test_sell",
    )


class TestSimulationConfig:
    """Test simulation configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SimulationConfig()

        assert config.fee_per_share == Decimal("0.005")
        assert config.min_fee == Decimal("1.0")
        assert config.base_slippage_bps == Decimal("5")

    def test_custom_config(self):
        """Test custom configuration."""
        config = SimulationConfig(
            fee_per_share=Decimal("0.01"),
            min_fee=Decimal("2.0"),
            base_slippage_bps=Decimal("10"),
        )

        assert config.fee_per_share == Decimal("0.01")
        assert config.min_fee == Decimal("2.0")
        assert config.base_slippage_bps == Decimal("10")

    def test_config_immutable(self):
        """Test that config is immutable."""
        config = SimulationConfig()

        with pytest.raises(Exception):  # ValidationError or AttributeError
            config.fee_per_share = Decimal("0.02")


class TestTradeSimulator:
    """Test trade simulator."""

    def test_simulate_buy_market_order_success(
        self, simulator, portfolio, buy_intent
    ):
        """Test successful buy market order simulation."""
        market_price = Decimal("180.00")

        result = simulator.simulate(buy_intent, portfolio, market_price)

        assert result.status == SimulationStatus.SUCCESS
        assert result.execution_price == market_price
        assert result.gross_notional == market_price * buy_intent.quantity
        assert result.estimated_fee > 0
        assert result.estimated_slippage >= 0
        assert result.cash_before == portfolio.cash[0].total
        assert result.cash_after < result.cash_before
        assert result.exposure_after > result.exposure_before

    def test_simulate_sell_market_order_success(
        self, simulator, portfolio, sell_intent
    ):
        """Test successful sell market order simulation."""
        market_price = Decimal("460.00")

        result = simulator.simulate(sell_intent, portfolio, market_price)

        assert result.status == SimulationStatus.SUCCESS
        assert result.execution_price == market_price
        assert result.gross_notional == market_price * sell_intent.quantity
        assert result.estimated_fee > 0
        assert result.cash_after > result.cash_before
        assert result.exposure_after < result.exposure_before

    def test_simulate_buy_limit_order(self, simulator, portfolio):
        """Test buy limit order simulation."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            order_type=OrderType.LMT,
            limit_price=Decimal("175.00"),
            reason="Buy AAPL at limit price for cost control",
            strategy_tag="test_limit",
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.SUCCESS
        assert result.execution_price == Decimal("175.00")
        # Limit orders have no slippage
        assert result.estimated_slippage == 0

    def test_simulate_insufficient_cash(self, simulator, portfolio, buy_intent):
        """Test simulation with insufficient cash."""
        # Set market price very high to exceed available cash
        market_price = Decimal("10000.00")

        result = simulator.simulate(buy_intent, portfolio, market_price)

        assert result.status == SimulationStatus.INSUFFICIENT_CASH
        assert result.cash_after < 0
        assert result.error_message is not None
        assert "Insufficient cash" in result.error_message

    def test_simulate_zero_quantity(self, simulator, portfolio):
        """Test simulation with zero quantity."""
        # Create valid intent first, then manually set quantity to 0 to bypass validation
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("10"),  # Valid initially
            order_type=OrderType.MKT,
            reason="Order for testing zero quantity validation",
            strategy_tag="test_zero",
        )
        
        # Bypass Pydantic validation by setting directly
        object.__setattr__(intent, 'quantity', Decimal("0"))
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.INVALID_QUANTITY
        assert result.error_message is not None

    def test_fee_calculation_minimum(self, simulator, portfolio):
        """Test that minimum fee is applied for small orders."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("1"),  # Very small order
            order_type=OrderType.MKT,
            reason="Buy single share for testing minimum fee",
            strategy_tag="test_min_fee",
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        # Should apply minimum fee ($1.00)
        assert result.estimated_fee >= Decimal("1.0")

    def test_fee_calculation_per_share(self, custom_simulator, portfolio):
        """Test per-share fee calculation."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("1000"),
            order_type=OrderType.MKT,
            reason="Buy large quantity for per-share fee testing",
            strategy_tag="test_per_share",
        )
        market_price = Decimal("180.00")

        result = custom_simulator.simulate(intent, portfolio, market_price)

        # Custom config has $0.01 per share
        expected_fee = Decimal("1000") * Decimal("0.01")
        assert result.estimated_fee == expected_fee

    def test_slippage_market_order(self, simulator, portfolio, buy_intent):
        """Test that market orders have slippage."""
        market_price = Decimal("180.00")

        result = simulator.simulate(buy_intent, portfolio, market_price)

        assert result.estimated_slippage > 0

    def test_slippage_limit_order(self, simulator, portfolio):
        """Test that limit orders have no slippage."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            order_type=OrderType.LMT,
            limit_price=Decimal("175.00"),
            reason="Buy AAPL with limit order for no slippage",
            strategy_tag="test_no_slippage",
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.estimated_slippage == 0

    def test_constraint_max_slippage_violated(self, simulator, portfolio):
        """Test constraint violation for max slippage."""
        constraints = OrderConstraints(max_slippage_bps=1)  # Very tight
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            order_type=OrderType.MKT,  # Market order will have slippage
            reason="Buy AAPL with tight slippage constraint for testing",
            strategy_tag="test_constraint",
            constraints=constraints,
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.CONSTRAINT_VIOLATED
        assert "slippage" in result.error_message.lower()

    def test_constraint_max_notional_violated(self, simulator, portfolio):
        """Test constraint violation for max notional."""
        constraints = OrderConstraints(max_notional=Decimal("1000.00"))
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),  # Will exceed max notional
            order_type=OrderType.MKT,
            reason="Buy large AAPL order with notional constraint for testing",
            strategy_tag="test_max_notional",
            constraints=constraints,
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.CONSTRAINT_VIOLATED
        assert "notional" in result.error_message.lower()

    def test_constraint_satisfied(self, simulator, portfolio):
        """Test simulation with satisfied constraints."""
        constraints = OrderConstraints(
            max_slippage_bps=100,  # Generous
            max_notional=Decimal("20000.00"),
        )
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            order_type=OrderType.MKT,
            reason="Buy AAPL with reasonable constraints for testing",
            strategy_tag="test_ok_constraint",
            constraints=constraints,
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.SUCCESS

    def test_large_trade_warning(self, simulator, portfolio):
        """Test warning for large trades."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("500"),  # Large order
            order_type=OrderType.MKT,
            reason="Buy very large AAPL position for portfolio allocation",
            strategy_tag="test_large",
        )
        market_price = Decimal("180.00")

        result = simulator.simulate(intent, portfolio, market_price)

        assert result.status == SimulationStatus.SUCCESS
        assert len(result.warnings) > 0
        assert any("Large trade" in w for w in result.warnings)

    def test_deterministic_results(self, simulator, portfolio, buy_intent):
        """Test that simulator produces deterministic results."""
        market_price = Decimal("180.00")

        result1 = simulator.simulate(buy_intent, portfolio, market_price)
        result2 = simulator.simulate(buy_intent, portfolio, market_price)

        assert result1.execution_price == result2.execution_price
        assert result1.gross_notional == result2.gross_notional
        assert result1.estimated_fee == result2.estimated_fee
        assert result1.estimated_slippage == result2.estimated_slippage
        assert result1.cash_after == result2.cash_after

    def test_cash_calculation_buy(self, simulator, portfolio, buy_intent):
        """Test cash calculation for buy order."""
        market_price = Decimal("180.00")

        result = simulator.simulate(buy_intent, portfolio, market_price)

        # Cash should decrease by net notional
        expected_cash_after = (
            portfolio.cash[0].total - result.net_notional
        )
        assert result.cash_after == expected_cash_after

    def test_cash_calculation_sell(self, simulator, portfolio, sell_intent):
        """Test cash calculation for sell order."""
        market_price = Decimal("460.00")

        result = simulator.simulate(sell_intent, portfolio, market_price)

        # Cash should increase by net notional
        expected_cash_after = (
            portfolio.cash[0].total + result.net_notional
        )
        assert result.cash_after == expected_cash_after

    def test_exposure_calculation_buy(self, simulator, portfolio, buy_intent):
        """Test exposure calculation for buy order."""
        market_price = Decimal("180.00")

        result = simulator.simulate(buy_intent, portfolio, market_price)

        # Exposure should increase by gross notional
        expected_exposure_after = (
            portfolio.total_value + result.gross_notional
        )
        assert result.exposure_after == expected_exposure_after

    def test_exposure_calculation_sell(self, simulator, portfolio, sell_intent):
        """Test exposure calculation for sell order."""
        market_price = Decimal("460.00")

        result = simulator.simulate(sell_intent, portfolio, market_price)

        # Exposure should decrease by gross notional
        expected_exposure_after = (
            portfolio.total_value - result.gross_notional
        )
        assert result.exposure_after == expected_exposure_after
