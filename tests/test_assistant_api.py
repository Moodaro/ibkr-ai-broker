"""Tests for Assistant API endpoints."""

from decimal import Decimal
import uuid

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
def approval_service():
    """Create approval service for testing."""
    from packages.approval_service import ApprovalService
    return ApprovalService(max_proposals=100, token_ttl_minutes=5)


@pytest.fixture
def client(audit_store, approval_service):
    """Create test client with initialized services."""
    # Inject services into app
    from apps.assistant_api import main
    from packages.trade_sim import SimulationConfig, TradeSimulator
    
    main.audit_store = audit_store
    main.simulator = TradeSimulator(config=SimulationConfig())
    main.approval_service = approval_service
    
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


class TestRiskEvaluateEndpoint:
    """Test /api/v1/risk/evaluate endpoint."""
    
    @staticmethod
    def _make_simulation(
        gross_notional: str,
        execution_price: str,
        estimated_fee: str = "3.00",
        estimated_slippage: str = "2.25",
        cash_before: str = "100000.00",
        exposure_before: str = "0.00",
    ) -> dict:
        """Helper to create simulation dict."""
        gross = Decimal(gross_notional)
        fee = Decimal(estimated_fee)
        slippage = Decimal(estimated_slippage)
        cash_b = Decimal(cash_before)
        exposure_b = Decimal(exposure_before)
        
        net_notional = gross + fee + slippage  # For BUY orders
        cash_after = cash_b - net_notional
        exposure_after = exposure_b + gross
        
        return {
            "status": "SUCCESS",
            "execution_price": execution_price,
            "gross_notional": gross_notional,
            "estimated_fee": estimated_fee,
            "estimated_slippage": estimated_slippage,
            "net_notional": str(net_notional),
            "cash_before": cash_before,
            "cash_after": str(cash_after),
            "exposure_before": exposure_before,
            "exposure_after": str(exposure_after),
            "warnings": [],
            "error_message": None,
        }
    
    def test_evaluate_approve_small_order(self, client):
        """Test risk evaluation approves small order within all limits."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine in app
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
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
            quantity=Decimal("10"),
            order_type=OrderType.LMT,
            limit_price=Decimal("450.00"),
            reason="Small test order within limits",
            strategy_tag="test",
        )
        
        # Simulation result for $4500 order (10 shares @ $450)
        simulation = self._make_simulation(
            gross_notional="4500.00",
            execution_price="450.00",
            estimated_fee="2.50",
            estimated_slippage="2.25",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        if response.status_code != 200:
            print(f"\nStatus: {response.status_code}")
            print(f"Response: {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        assert "decision" in data
        assert "correlation_id" in data
        assert data["decision"]["decision"] == "APPROVE"
        assert len(data["decision"]["violated_rules"]) == 0
    
    def test_evaluate_reject_r1_max_notional(self, client):
        """Test risk evaluation rejects order exceeding max notional (R1)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_notional=Decimal("50000")),
            trading_hours=TradingHours(),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="TSLA",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("200"),
            order_type=OrderType.LMT,
            limit_price=Decimal("300.00"),
            reason="Large order exceeding notional limit",
            strategy_tag="test",
        )
        
        # Simulation result for $60k order (200 shares @ $300)
        simulation = self._make_simulation(
            gross_notional="60000.00",
            execution_price="300.00",
            estimated_fee="10.00",
            estimated_slippage="90.00",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R1" in data["decision"]["violated_rules"]
        assert "notional" in data["decision"]["reason"].lower()
    
    def test_evaluate_reject_r2_max_position_pct(self, client):
        """Test risk evaluation rejects order exceeding max position % (R2)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_position_pct=Decimal("10")),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
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
            quantity=Decimal("30"),
            order_type=OrderType.LMT,
            limit_price=Decimal("500.00"),
            reason="Order creating 15% position",
            strategy_tag="test",
        )
        
        # Simulation result for $15k order (15% of $100k portfolio)
        simulation = self._make_simulation(
            gross_notional="15000.00",
            execution_price="500.00",
            estimated_fee="5.00",
            estimated_slippage="15.00",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R2" in data["decision"]["violated_rules"]
        assert "position" in data["decision"]["reason"].lower()
    
    def test_evaluate_reject_r4_max_slippage(self, client):
        """Test risk evaluation rejects order with excessive slippage (R4)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_slippage_bps=Decimal("50")),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="ILLIQUID",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MKT,
            reason="Illiquid stock with high slippage",
            strategy_tag="test",
        )
        
        # Simulation with 66 bps slippage (exceeds 50 bps limit)
        simulation = self._make_simulation(
            gross_notional="10000.00",
            execution_price="100.00",
            estimated_fee="5.00",
            estimated_slippage="66.00",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R4" in data["decision"]["violated_rules"]
        assert "slippage" in data["decision"]["reason"].lower()
    
    def test_evaluate_reject_r5_outside_hours(self, client):
        """Test risk evaluation rejects order outside market hours (R5)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine with strict trading hours
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(),
            trading_hours=TradingHours(
                allow_pre_market=False,
                allow_after_hours=False,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
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
            quantity=Decimal("10"),
            order_type=OrderType.MKT,
            reason="Order outside market hours",
            strategy_tag="test",
        )
        
        # Simulation at 10:00 UTC (before market open at 14:30 UTC)
        simulation = self._make_simulation(
            gross_notional="1800.00",
            execution_price="180.00",
            estimated_fee="1.00",
            estimated_slippage="0.90",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R5" in data["decision"]["violated_rules"]
        assert "market hours" in data["decision"]["reason"].lower() or "trading hours" in data["decision"]["reason"].lower()
    
    def test_evaluate_reject_r7_max_daily_trades(self, client):
        """Test risk evaluation rejects order when max daily trades reached (R7)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine with 50 trades already executed today
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_daily_trades=50),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=50,  # At limit
            daily_pnl=Decimal("0"),
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
            quantity=Decimal("10"),
            order_type=OrderType.MKT,
            reason="51st trade of the day",
            strategy_tag="test",
        )
        
        simulation = self._make_simulation(
            gross_notional="4500.00",
            execution_price="450.00",
            estimated_fee="2.50",
            estimated_slippage="2.25",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R7" in data["decision"]["violated_rules"]
        assert "trade limit" in data["decision"]["reason"].lower()
    
    def test_evaluate_reject_r8_max_daily_loss(self, client):
        """Test risk evaluation rejects order when max daily loss exceeded (R8)."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine with $6k daily loss
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_daily_loss=Decimal("5000")),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("-6000"),  # Exceeded loss limit
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
            quantity=Decimal("10"),
            order_type=OrderType.MKT,
            reason="Order after daily loss limit",
            strategy_tag="test",
        )
        
        simulation = self._make_simulation(
            gross_notional="4500.00",
            execution_price="450.00",
            estimated_fee="2.50",
            estimated_slippage="2.25",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "REJECT"
        assert "R8" in data["decision"]["violated_rules"]
        assert "daily loss" in data["decision"]["reason"].lower() or "circuit breaker" in data["decision"]["reason"].lower()
    
    def test_evaluate_warnings_near_limits(self, client):
        """Test risk evaluation generates warnings when approaching limits."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(max_notional=Decimal("50000")),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
        )
        
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol="TSLA",
                exchange="SMART",
                currency="USD",
            ),
            side=OrderSide.BUY,
            quantity=Decimal("140"),
            order_type=OrderType.LMT,
            limit_price=Decimal("300.00"),
            reason="Order at 84% of notional limit",
            strategy_tag="test",
        )
        
        # $42k order (84% of $50k limit, should trigger warning)
        simulation = self._make_simulation(
            gross_notional="42000.00",
            execution_price="300.00",
            estimated_fee="7.00",
            estimated_slippage="50.40",
            exposure_before="8000.00",  # Only 8% exposure to avoid R2 violation
        )
        simulation["exposure_after"] = "8000.00"  # Keep exposure low
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["decision"] == "APPROVE"
        assert len(data["decision"]["warnings"]) > 0
        assert any("notional" in w.lower() and "limit" in w.lower() for w in data["decision"]["warnings"])
    
    def test_evaluate_missing_fields(self, client):
        """Test risk evaluation with missing required fields."""
        # Missing simulation field
        request = {
            "intent": {
                "account_id": "DU123456",
                "instrument": {
                    "type": "STK",
                    "symbol": "SPY",
                    "exchange": "SMART",
                    "currency": "USD",
                },
                "side": "BUY",
                "quantity": "10",
                "order_type": "MKT",
                "reason": "Test",
                "strategy_tag": "test",
            },
            "portfolio_value": "100000.00",
            # Missing simulation
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 422  # Validation error
    
    def test_evaluate_correlation_id(self, client):
        """Test risk evaluation returns correlation ID."""
        from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
        from packages.schemas import OrderIntent
        
        # Initialize risk engine
        from apps.assistant_api import main
        from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
        
        main.risk_engine = RiskEngine(
            limits=RiskLimits(),
            trading_hours=TradingHours(
                allow_pre_market=True,
                allow_after_hours=True,
            ),
            daily_trades_count=0,
            daily_pnl=Decimal("0"),
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
            quantity=Decimal("10"),
            order_type=OrderType.MKT,
            reason="Test correlation ID",
            strategy_tag="test",
        )
        
        simulation = self._make_simulation(
            gross_notional="4500.00",
            execution_price="450.00",
            estimated_fee="2.50",
            estimated_slippage="2.25",
        )
        
        request = {
            "intent": intent.model_dump(mode="json"),
            "simulation": simulation,
            "portfolio_value": "100000.00",
        }
        
        response = client.post("/api/v1/risk/evaluate", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert "correlation_id" in data
        assert len(data["correlation_id"]) > 0


class TestApprovalEndpoints:
    """Tests for approval flow endpoints."""
    
    @staticmethod
    def _create_approved_proposal(approval_service, intent_json, simulation_json, risk_decision_json):
        """Helper to create and store an approved proposal."""
        from packages.schemas.approval import OrderProposal, OrderState
        
        proposal = OrderProposal(
            proposal_id=f"test-proposal-{uuid.uuid4().hex[:8]}",
            correlation_id=f"test-corr-{uuid.uuid4().hex[:8]}",
            intent_json=intent_json,
            simulation_json=simulation_json,
            risk_decision_json=risk_decision_json,
            state=OrderState.RISK_APPROVED,
        )
        approval_service.store_proposal(proposal)
        return proposal
    
    def test_request_approval_success(self, client, approval_service):
        """Test POST /api/v1/approval/request with valid proposal."""
        import json
        
        # Create approved proposal
        intent = {
            "instrument": {"type": "STK", "symbol": "AAPL", "exchange": "SMART", "currency": "USD"},
            "side": "BUY",
            "quantity": 10,
            "order_type": "MKT",
            "time_in_force": "DAY",
            "reason": "Test",
        }
        simulation = {
            "status": "SUCCESS",
            "execution_price": "150.00",
            "gross_notional": "1500.00",
            "estimated_fee": "1.00",
            "estimated_slippage": "0.75",
            "net_notional": "1501.75",
            "cash_before": "100000.00",
            "cash_after": "98498.25",
            "exposure_before": "0.00",
            "exposure_after": "1500.00",
            "warnings": [],
            "error_message": None,
        }
        risk = {
            "decision": "APPROVE",
            "reason": "All checks passed",
            "violated_rules": [],
            "warnings": [],
            "metrics": {},
        }
        
        proposal = self._create_approved_proposal(
            approval_service,
            json.dumps(intent),
            json.dumps(simulation),
            json.dumps(risk),
        )
        
        # Request approval
        request = {"proposal_id": proposal.proposal_id}
        response = client.post("/api/v1/approval/request", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == proposal.proposal_id
        assert data["state"] == "APPROVAL_REQUESTED"
        assert "correlation_id" in data
    
    def test_request_approval_not_found(self, client):
        """Test request approval fails when proposal not found."""
        request = {"proposal_id": "nonexistent"}
        response = client.post("/api/v1/approval/request", json=request)
        
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()
    
    def test_grant_approval_success(self, client, approval_service):
        """Test POST /api/v1/approval/grant generates token."""
        import json
        
        # Create and request approval
        intent = {
            "instrument": {"type": "STK", "symbol": "MSFT", "exchange": "SMART", "currency": "USD"},
            "side": "BUY",
            "quantity": 5,
            "order_type": "LMT",
            "limit_price": 300.00,
            "time_in_force": "DAY",
            "reason": "Test",
        }
        simulation = {
            "status": "SUCCESS",
            "execution_price": "300.00",
            "gross_notional": "1500.00",
            "estimated_fee": "1.00",
            "estimated_slippage": "0.50",
            "net_notional": "1501.50",
            "cash_before": "100000.00",
            "cash_after": "98498.50",
            "exposure_before": "0.00",
            "exposure_after": "1500.00",
            "warnings": [],
            "error_message": None,
        }
        risk = {
            "decision": "APPROVE",
            "reason": "All checks passed",
            "violated_rules": [],
            "warnings": [],
            "metrics": {},
        }
        
        proposal = self._create_approved_proposal(
            approval_service,
            json.dumps(intent),
            json.dumps(simulation),
            json.dumps(risk),
        )
        approval_service.request_approval(proposal.proposal_id)
        
        # Grant approval
        request = {"proposal_id": proposal.proposal_id, "reason": "Looks good"}
        response = client.post("/api/v1/approval/grant", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == proposal.proposal_id
        assert "token" in data
        assert len(data["token"]) > 0
        assert "expires_at" in data
        assert "correlation_id" in data
    
    def test_grant_approval_wrong_state(self, client, approval_service):
        """Test grant approval fails if not requested first."""
        import json
        
        # Create proposal but don't request approval
        intent = {"instrument": {"type": "STK", "symbol": "TSLA", "exchange": "SMART", "currency": "USD"}, "side": "BUY", "quantity": 1, "order_type": "MKT", "time_in_force": "DAY", "reason": "Test"}
        simulation = {"status": "SUCCESS", "execution_price": "200.00", "gross_notional": "200.00", "estimated_fee": "1.00", "estimated_slippage": "0.25", "net_notional": "201.25", "cash_before": "100000.00", "cash_after": "99798.75", "exposure_before": "0.00", "exposure_after": "200.00", "warnings": [], "error_message": None}
        risk = {"decision": "APPROVE", "reason": "OK", "violated_rules": [], "warnings": [], "metrics": {}}
        
        proposal = self._create_approved_proposal(
            approval_service,
            json.dumps(intent),
            json.dumps(simulation),
            json.dumps(risk),
        )
        
        # Try to grant without requesting
        request = {"proposal_id": proposal.proposal_id}
        response = client.post("/api/v1/approval/grant", json=request)
        
        assert response.status_code == 400
        assert "APPROVAL_REQUESTED" in response.json()["detail"]
    
    def test_deny_approval_success(self, client, approval_service):
        """Test POST /api/v1/approval/deny."""
        import json
        
        # Create and request approval
        intent = {"instrument": {"type": "STK", "symbol": "GOOGL", "exchange": "SMART", "currency": "USD"}, "side": "SELL", "quantity": 10, "order_type": "MKT", "time_in_force": "DAY", "reason": "Test"}
        simulation = {"status": "SUCCESS", "execution_price": "140.00", "gross_notional": "1400.00", "estimated_fee": "1.00", "estimated_slippage": "0.70", "net_notional": "1401.70", "cash_before": "100000.00", "cash_after": "98598.30", "exposure_before": "0.00", "exposure_after": "1400.00", "warnings": [], "error_message": None}
        risk = {"decision": "APPROVE", "reason": "OK", "violated_rules": [], "warnings": [], "metrics": {}}
        
        proposal = self._create_approved_proposal(
            approval_service,
            json.dumps(intent),
            json.dumps(simulation),
            json.dumps(risk),
        )
        approval_service.request_approval(proposal.proposal_id)
        
        # Deny approval
        request = {"proposal_id": proposal.proposal_id, "reason": "Changed my mind"}
        response = client.post("/api/v1/approval/deny", json=request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == proposal.proposal_id
        assert data["state"] == "APPROVAL_DENIED"
        assert "Changed my mind" in data["message"]
    
    def test_deny_approval_requires_reason(self, client, approval_service):
        """Test deny approval requires reason field."""
        import json
        
        # Create and request approval
        intent = {"instrument": {"type": "STK", "symbol": "AMZN", "exchange": "SMART", "currency": "USD"}, "side": "BUY", "quantity": 1, "order_type": "MKT", "time_in_force": "DAY", "reason": "Test"}
        simulation = {"status": "SUCCESS", "execution_price": "180.00", "gross_notional": "180.00", "estimated_fee": "1.00", "estimated_slippage": "0.09", "net_notional": "181.09", "cash_before": "100000.00", "cash_after": "99818.91", "exposure_before": "0.00", "exposure_after": "180.00", "warnings": [], "error_message": None}
        risk = {"decision": "APPROVE", "reason": "OK", "violated_rules": [], "warnings": [], "metrics": {}}
        
        proposal = self._create_approved_proposal(
            approval_service,
            json.dumps(intent),
            json.dumps(simulation),
            json.dumps(risk),
        )
        approval_service.request_approval(proposal.proposal_id)
        
        # Try to deny without reason
        request = {"proposal_id": proposal.proposal_id}
        response = client.post("/api/v1/approval/deny", json=request)
        
        assert response.status_code == 422  # Validation error
    
    def test_get_pending_proposals_empty(self, client):
        """Test GET /api/v1/approval/pending with no proposals."""
        response = client.get("/api/v1/approval/pending")
        
        assert response.status_code == 200
        data = response.json()
        assert "proposals" in data
        assert "count" in data
        assert isinstance(data["proposals"], list)
    
    def test_get_pending_proposals_with_data(self, client, approval_service):
        """Test GET /api/v1/approval/pending returns pending proposals."""
        import json
        
        # Create multiple proposals
        for i in range(3):
            intent = {"instrument": {"type": "STK", "symbol": f"STOCK{i}", "exchange": "SMART", "currency": "USD"}, "side": "BUY", "quantity": 10, "order_type": "MKT", "time_in_force": "DAY", "reason": f"Test {i}"}
            simulation = {"status": "SUCCESS", "execution_price": "100.00", "gross_notional": "1000.00", "estimated_fee": "1.00", "estimated_slippage": "0.50", "net_notional": "1001.50", "cash_before": "100000.00", "cash_after": "98998.50", "exposure_before": "0.00", "exposure_after": "1000.00", "warnings": [], "error_message": None}
            risk = {"decision": "APPROVE", "reason": "OK", "violated_rules": [], "warnings": [], "metrics": {}}
            
            proposal = self._create_approved_proposal(
                approval_service,
                json.dumps(intent),
                json.dumps(simulation),
                json.dumps(risk),
            )
            if i < 2:
                approval_service.request_approval(proposal.proposal_id)
        
        response = client.get("/api/v1/approval/pending")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["proposals"]) == 3  # 2 APPROVAL_REQUESTED + 1 RISK_APPROVED
        assert data["count"] == 3
        
        # Check structure
        first = data["proposals"][0]
        assert "proposal_id" in first
        assert "state" in first
        assert "symbol" in first
        assert "side" in first
    
    def test_get_pending_proposals_limit(self, client, approval_service):
        """Test GET /api/v1/approval/pending respects limit parameter."""
        import json
        
        # Create 5 proposals
        for i in range(5):
            intent = {"instrument": {"type": "STK", "symbol": f"TEST{i}", "exchange": "SMART", "currency": "USD"}, "side": "BUY", "quantity": 1, "order_type": "MKT", "time_in_force": "DAY", "reason": f"Test {i}"}
            simulation = {"status": "SUCCESS", "execution_price": "50.00", "gross_notional": "50.00", "estimated_fee": "1.00", "estimated_slippage": "0.03", "net_notional": "51.03", "cash_before": "100000.00", "cash_after": "99948.97", "exposure_before": "0.00", "exposure_after": "50.00", "warnings": [], "error_message": None}
            risk = {"decision": "APPROVE", "reason": "OK", "violated_rules": [], "warnings": [], "metrics": {}}
            
            self._create_approved_proposal(
                approval_service,
                json.dumps(intent),
                json.dumps(simulation),
                json.dumps(risk),
            )
        
        response = client.get("/api/v1/approval/pending?limit=2")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["proposals"]) == 2
        assert data["count"] == 2

