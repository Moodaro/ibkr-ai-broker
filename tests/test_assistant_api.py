"""Tests for Assistant API endpoints."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from apps.assistant_api.main import app
from packages.audit_store import AuditStore


@pytest.fixture
def audit_store(tmp_path):
    """Create temporary audit store."""
    db_path = tmp_path / "test_audit.db"
    return AuditStore(str(db_path))


@pytest.fixture
def client(audit_store):
    """Create test client with initialized audit store."""
    # Inject audit store and simulator into app
    from apps.assistant_api import main
    from packages.trade_sim import SimulationConfig, TradeSimulator
    
    main.audit_store = audit_store
    main.simulator = TradeSimulator(config=SimulationConfig())
    
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root health check."""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "IBKR AI Broker Assistant"
        assert data["status"] == "healthy"
    
    def test_health_endpoint(self, client):
        """Test detailed health check."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "audit_store" in data


class TestProposeEndpoint:
    """Test /api/v1/propose endpoint."""
    
    def test_propose_valid_market_order(self, client):
        """Test proposing valid market order."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "time_in_force": "DAY",
            "reason": "Buy SPY for S&P 500 index exposure and diversification",
            "strategy_tag": "momentum_long",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        if response.status_code != 200:
            print(f"\nStatus: {response.status_code}")
            print(f"Response: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
        assert "correlation_id" in data
        assert data["intent"]["account_id"] == "DU123456"
        assert data["intent"]["instrument"]["symbol"] == "SPY"
        assert data["intent"]["side"] == "BUY"
        assert data["intent"]["quantity"] == "100"
        assert data["intent"]["order_type"] == "MKT"
        
        # Market orders should have a warning
        assert len(data["warnings"]) > 0
        assert any("slippage" in w.lower() for w in data["warnings"])
    
    def test_propose_valid_limit_order(self, client):
        """Test proposing valid limit order."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "SELL",
            "quantity": "50",
            "order_type": "LMT",
            "limit_price": "180.50",
            "time_in_force": "GTC",
            "reason": "Sell AAPL at target price to lock in gains",
            "strategy_tag": "mean_reversion",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
        assert data["intent"]["order_type"] == "LMT"
        assert data["intent"]["limit_price"] == "180.50"
    
    def test_propose_stop_limit_order(self, client):
        """Test proposing stop-limit order with both prices."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "MSFT",
            "side": "BUY",
            "quantity": "75",
            "order_type": "STP_LMT",
            "stop_price": "350.00",
            "limit_price": "355.00",
            "time_in_force": "GTC",
            "reason": "Buy MSFT above resistance with limit protection against slippage",
            "strategy_tag": "breakout_entry",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
        assert data["intent"]["stop_price"] == "350.00"
        assert data["intent"]["limit_price"] == "355.00"
    
    def test_propose_with_constraints(self, client):
        """Test proposing order with constraints."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "time_in_force": "DAY",
            "reason": "Buy SPY with slippage protection for risk management",
            "strategy_tag": "protected_entry",
            "exchange": "SMART",
            "currency": "USD",
            "max_slippage_bps": 30,
            "max_notional": "50000.00",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert data["validation_passed"] is True
        assert data["intent"]["constraints"] is not None
        assert data["intent"]["constraints"]["max_slippage_bps"] == 30
    
    def test_propose_high_slippage_warning(self, client):
        """Test that high slippage tolerance triggers warning."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "time_in_force": "DAY",
            "reason": "Buy SPY with high slippage tolerance accepted",
            "strategy_tag": "aggressive_entry",
            "exchange": "SMART",
            "currency": "USD",
            "max_slippage_bps": 100,
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["warnings"]) >= 2  # Market order + high slippage
        assert any("100 bps" in w for w in data["warnings"])
    
    def test_propose_empty_account_id_fails(self, client):
        """Test that empty account_id is rejected."""
        proposal = {
            "account_id": "",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "reason": "Buy SPY for exposure",
            "strategy_tag": "test",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 422
        data = response.json()
        assert "correlation_id" in data
        assert "detail" in data
    
    def test_propose_short_reason_fails(self, client):
        """Test that short reason is rejected."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "reason": "Buy now",  # Only 2 words
            "strategy_tag": "test",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 422
        data = response.json()
        assert "correlation_id" in data
    
    def test_propose_limit_without_price_fails(self, client):
        """Test that limit order without limit_price is rejected."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": "50",
            "order_type": "LMT",
            # Missing limit_price
            "time_in_force": "DAY",
            "reason": "Buy AAPL at specific price level",
            "strategy_tag": "limit_entry",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 422
    
    def test_propose_invalid_quantity_fails(self, client):
        """Test that zero/negative quantity is rejected."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "0",
            "order_type": "MKT",
            "reason": "Buy SPY for exposure",
            "strategy_tag": "test",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 422
    
    def test_propose_missing_required_fields_fails(self, client):
        """Test that missing required fields are rejected."""
        proposal = {
            "symbol": "SPY",
            # Missing account_id, side, quantity, etc.
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 422
    
    def test_symbol_uppercase_conversion(self, client):
        """Test that lowercase symbols are converted to uppercase."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "spy",  # Lowercase
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "reason": "Buy SPY for index exposure and diversification",
            "strategy_tag": "test",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert data["intent"]["instrument"]["symbol"] == "SPY"  # Uppercase
    
    def test_correlation_id_in_response(self, client):
        """Test that correlation_id is included in response."""
        proposal = {
            "account_id": "DU123456",
            "symbol": "SPY",
            "side": "BUY",
            "quantity": "100",
            "order_type": "MKT",
            "reason": "Buy SPY for S&P 500 exposure",
            "strategy_tag": "test",
            "exchange": "SMART",
            "currency": "USD",
        }
        
        response = client.post("/api/v1/propose", json=proposal)
        
        assert response.status_code == 200
        data = response.json()
        assert "correlation_id" in data
        assert len(data["correlation_id"]) > 0


class TestSimulateEndpoint:
    """Test /simulate endpoint."""

    def test_simulate_buy_market_order(self, client):
        """Test simulation of a buy market order."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # First create a valid intent
        intent = OrderIntent(
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
            reason="Buy 100 shares of AAPL at market",
            strategy_tag="test",
        )
        
        # Simulate with market price
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "150.00",
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "correlation_id" in data
        
        result = data["result"]
        assert result["status"] == "SUCCESS"
        assert Decimal(result["execution_price"]) == Decimal("150.00")
        assert Decimal(result["gross_notional"]) == Decimal("15000.00")
        assert Decimal(result["estimated_fee"]) > 0
        assert Decimal(result["cash_after"]) < Decimal(result["cash_before"])
    
    def test_simulate_sell_limit_order(self, client):
        """Test simulation of a sell limit order."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="TSLA",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.SELL,
            quantity=Decimal("50"),
            order_type=OrderType.LMT,
            limit_price=Decimal("250.00"),
            reason="Sell 50 TSLA at limit",
            strategy_tag="test",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "245.00",
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        result = data["result"]
        
        assert result["status"] == "SUCCESS"
        assert Decimal(result["execution_price"]) == Decimal("250.00")  # Limit price
        assert Decimal(result["estimated_slippage"]) == 0  # No slippage for limit orders
        assert Decimal(result["cash_after"]) > Decimal(result["cash_before"])  # Cash increases on sell
    
    def test_simulate_insufficient_cash(self, client):
        """Test simulation with insufficient cash."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Large order that exceeds default portfolio cash
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AMZN",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("1000"),
            order_type=OrderType.MKT,
            reason="Large buy order",
            strategy_tag="test",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "150.00",  # 150k total
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        result = data["result"]
        
        assert result["status"] == "INSUFFICIENT_CASH"
        assert result["error_message"] is not None
        assert "Insufficient cash" in result["error_message"]
    
    def test_simulate_with_constraints(self, client):
        """Test simulation with order constraints."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderConstraints, OrderIntent
        
        constraints = OrderConstraints(
            max_slippage_bps=10,  # 0.1% max slippage
            max_notional=Decimal("10000.00"),
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="NVDA",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("20"),
            order_type=OrderType.MKT,
            reason="Buy with constraints",
            strategy_tag="test",
            constraints=constraints,
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "450.00",
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        result = data["result"]
        
        # Should succeed as notional is 9000 < 10000
        assert result["status"] == "SUCCESS"
    
    def test_simulate_constraint_violated(self, client):
        """Test simulation with violated constraints."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderConstraints, OrderIntent
        
        constraints = OrderConstraints(
            max_notional=Decimal("5000.00"),  # Low limit
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="GOOG",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            reason="Buy exceeding max notional",
            strategy_tag="test",
            constraints=constraints,
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "100.00",  # 10k notional
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        result = data["result"]
        
        assert result["status"] == "CONSTRAINT_VIOLATED"
        assert result["error_message"] is not None
        assert "max" in result["error_message"].lower()  # Check for "max" in error message
    
    def test_simulate_missing_market_price_fails(self, client):
        """Test simulation fails without market price."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="MSFT",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            order_type=OrderType.MKT,
            reason="Test market order execution",
            strategy_tag="test",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            # Missing market_price
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 422  # Validation error
    
    def test_simulate_negative_market_price_fails(self, client):
        """Test simulation fails with negative market price."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="FB",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("25"),
            order_type=OrderType.MKT,
            reason="Test market order validation",
            strategy_tag="test",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "-100.00",
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 422  # Validation error
    
    def test_simulate_correlation_id_in_response(self, client):
        """Test that correlation_id is included in simulation response."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="AMD",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            order_type=OrderType.MKT,
            reason="Test correlation ID",
            strategy_tag="test",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "market_price": "120.00",
        }
        
        response = client.post("/api/v1/simulate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert "correlation_id" in data
        assert len(data["correlation_id"]) > 0
