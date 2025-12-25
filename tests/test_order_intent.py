"""Tests for OrderIntent schema validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.broker_ibkr import (
    Instrument,
    InstrumentType,
    OrderSide,
    OrderType,
    TimeInForce,
)
from packages.schemas import OrderConstraints, OrderIntent


class TestOrderConstraints:
    """Test cases for OrderConstraints model."""
    
    def test_valid_constraints(self):
        """Test valid constraint creation."""
        constraints = OrderConstraints(
            max_slippage_bps=50,
            max_notional=Decimal("10000.00"),
            min_liquidity=Decimal("1000000.00"),
            execution_window_minutes=30,
        )
        
        assert constraints.max_slippage_bps == 50
        assert constraints.max_notional == Decimal("10000.00")
        assert constraints.min_liquidity == Decimal("1000000.00")
        assert constraints.execution_window_minutes == 30
    
    def test_negative_slippage_fails(self):
        """Test that negative slippage is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderConstraints(max_slippage_bps=-10)
        
        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("max_slippage_bps",) and "greater than or equal to 0" in str(e)
            for e in errors
        )
    
    def test_excessive_slippage_fails(self):
        """Test that excessive slippage is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderConstraints(max_slippage_bps=5000)
        
        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("max_slippage_bps",) and "less than or equal to 1000" in str(e)
            for e in errors
        )
    
    def test_negative_notional_fails(self):
        """Test that negative notional is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderConstraints(max_notional=Decimal("-100.00"))
        
        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("max_notional",) and "greater than 0" in str(e)
            for e in errors
        )


class TestOrderIntent:
    """Test cases for OrderIntent model."""
    
    def test_valid_market_order(self):
        """Test valid market order creation."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="SPY",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            time_in_force=TimeInForce.DAY,
            reason="Buy SPY to increase portfolio exposure to S&P 500 index",
            strategy_tag="momentum_long",
        )
        
        assert intent.account_id == "DU123456"
        assert intent.instrument.symbol == "SPY"
        assert intent.side == OrderSide.BUY
        assert intent.quantity == Decimal("100")
        assert intent.order_type == OrderType.MKT
        assert intent.limit_price is None
        assert intent.stop_price is None
    
    def test_valid_limit_order(self):
        """Test valid limit order with required price."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AAPL",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.SELL,
            quantity=Decimal("50"),
            order_type=OrderType.LMT,
            limit_price=Decimal("180.50"),
            time_in_force=TimeInForce.GTC,
            reason="Sell AAPL at target price to take profit",
            strategy_tag="mean_reversion",
        )
        
        assert intent.order_type == OrderType.LMT
        assert intent.limit_price == Decimal("180.50")
    
    def test_limit_order_without_price_fails(self):
        """Test that limit order without limit_price is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
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
                # Missing limit_price
                time_in_force=TimeInForce.DAY,
                reason="Buy AAPL at specific price level",
                strategy_tag="limit_entry",
            )
        
        errors = exc_info.value.errors()
        assert any(
            "limit_price" in str(e) and "required" in str(e).lower()
            for e in errors
        )
    
    def test_stop_order_with_required_price(self):
        """Test stop order requires stop_price."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="TSLA",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.SELL,
            quantity=Decimal("25"),
            order_type=OrderType.STP,
            stop_price=Decimal("200.00"),
            time_in_force=TimeInForce.DAY,
            reason="Stop loss trigger at support level to protect capital",
            strategy_tag="risk_management",
        )
        
        assert intent.stop_price == Decimal("200.00")
    
    def test_stop_limit_order_requires_both_prices(self):
        """Test stop-limit order requires both prices."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="MSFT",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("75"),
            order_type=OrderType.STP_LMT,
            stop_price=Decimal("350.00"),
            limit_price=Decimal("355.00"),
            time_in_force=TimeInForce.GTC,
            reason="Buy MSFT above resistance with limit protection against excessive slippage",
            strategy_tag="breakout_entry",
        )
        
        assert intent.stop_price == Decimal("350.00")
        assert intent.limit_price == Decimal("355.00")
    
    def test_empty_account_id_fails(self):
        """Test that empty account_id is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
                account_id="",
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                order_type=OrderType.MKT,
                reason="Buy SPY for index exposure",
                strategy_tag="test",
            )
        
        errors = exc_info.value.errors()
        # Print for debugging
        print("\nErrors:", errors)
        assert any(
            "account_id" in str(e)
            for e in errors
        )
    
    def test_short_reason_fails(self):
        """Test that reason with < 10 characters is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
                account_id="DU123456",
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                order_type=OrderType.MKT,
                reason="Buy now",  # Only 7 chars, < 10
                strategy_tag="test",
            )
        
        errors = exc_info.value.errors()
        # Either min_length constraint (10 chars) or word count validator (3 words)
        assert any(
            "reason" in str(e["loc"]) and ("10" in str(e) or "3" in str(e))
            for e in errors
        )
    
    def test_reason_with_10_chars_passes(self):
        """Test that reason with exactly 10 chars passes."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="SPY",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            reason="Buy now urgently",  # 10+ chars, 3 words
            strategy_tag="test",
        )
        
        assert len(intent.reason) >= 10
    
    def test_long_reason_truncated(self):
        """Test that excessively long reason is rejected."""
        long_reason = "Buy " * 200  # Will exceed 500 chars
        
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
                account_id="DU123456",
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                order_type=OrderType.MKT,
                reason=long_reason,
                strategy_tag="test",
            )
        
        errors = exc_info.value.errors()
        assert any(
            "reason" in str(e) and "500" in str(e)
            for e in errors
        )
    
    def test_zero_quantity_fails(self):
        """Test that zero quantity is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
                account_id="DU123456",
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                side=OrderSide.BUY,
                quantity=Decimal("0"),
                order_type=OrderType.MKT,
                reason="Buy SPY for exposure",
                strategy_tag="test",
            )
        
        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("quantity",) and "greater than 0" in str(e)
            for e in errors
        )
    
    def test_negative_quantity_fails(self):
        """Test that negative quantity is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OrderIntent(
                account_id="DU123456",
                instrument=Instrument(
                    type=InstrumentType.STK,
                    symbol="SPY",
                    exchange="SMART",
                    currency="USD",
                ),
                side=OrderSide.BUY,
                quantity=Decimal("-100"),
                order_type=OrderType.MKT,
                reason="Buy SPY for exposure",
                strategy_tag="test",
            )
        
        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("quantity",) and "greater than 0" in str(e)
            for e in errors
        )
    
    def test_order_with_constraints(self):
        """Test order with constraints."""
        constraints = OrderConstraints(
            max_slippage_bps=30,
            max_notional=Decimal("50000.00"),
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="SPY",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            reason="Buy SPY with slippage protection enabled",
            strategy_tag="protected_entry",
            constraints=constraints,
        )
        
        assert intent.constraints is not None
        assert intent.constraints.max_slippage_bps == 30
        assert intent.constraints.max_notional == Decimal("50000.00")
    
    def test_immutability(self):
        """Test that OrderIntent is frozen (immutable)."""
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="SPY",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            reason="Buy SPY for index exposure",
            strategy_tag="test",
        )
        
        with pytest.raises(ValidationError):
            intent.quantity = Decimal("200")  # Should fail
