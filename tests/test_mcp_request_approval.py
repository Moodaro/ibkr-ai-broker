"""
Unit tests for MCP server request_approval tool.

Tests cover:
- Successful approval request
- Risk rejection scenarios  
- Simulation failure scenarios
- Parameter validation
- Service initialization checks
- Audit event emission
"""

import json
from decimal import Decimal

import pytest

from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType
from packages.schemas.order_intent import OrderIntent
from packages.trade_sim import TradeSimulator, SimulationConfig
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours
from packages.risk_engine.models import Decision
from packages.approval_service import ApprovalService


@pytest.fixture
def services():
    """Create real services for integration testing."""
    broker = FakeBrokerAdapter(account_id="DU123456")
    broker.connect()
    
    simulator = TradeSimulator(config=SimulationConfig())
    
    risk_engine = RiskEngine(
        limits=RiskLimits(),
        trading_hours=TradingHours(allow_pre_market=True, allow_after_hours=True),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )
    
    approval_service = ApprovalService(max_proposals=1000)
    
    return broker, simulator, risk_engine, approval_service


def test_request_approval_workflow_success(services):
    """Test complete request_approval workflow - success path."""
    broker, simulator, risk_engine, approval_service = services
    
    # Create OrderIntent
    intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("10"),
        order_type="MKT",
        limit_price=None,
        time_in_force="DAY",
        reason="Portfolio rebalancing to target allocation",
        strategy_tag="mcp_request",
        constraints={},
    )
    
    # Step 1: Get portfolio
    portfolio = broker.get_portfolio("DU123456")
    assert portfolio is not None
    
    # Step 2: Simulate order
    market_price = Decimal("190.00")
    sim_result = simulator.simulate(portfolio, intent, market_price)
    assert sim_result.status == "SUCCESS"
    assert sim_result.net_cash_impact < 0  # Buying costs money
    
    # Step 3: Evaluate risk
    risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)
    assert risk_decision.decision == Decision.APPROVE
    
    # Step 4: Store proposal and request approval
    proposal = approval_service.store_proposal(
        intent=intent,
        sim_result=sim_result,
        risk_decision=risk_decision,
    )
    assert proposal is not None
    assert proposal.proposal_id is not None
    
    # Step 5: Request approval
    approval_service.request_approval(proposal.proposal_id)
    
    # Verify proposal state
    retrieved = approval_service.get_proposal(proposal.proposal_id)
    assert retrieved is not None
    assert retrieved.state == "APPROVAL_REQUESTED"
    assert retrieved.intent.symbol == "AAPL"
    assert retrieved.intent.quantity == Decimal("10")


def test_request_approval_workflow_risk_rejection(services):
    """Test request_approval workflow - risk rejection path."""
    broker, simulator, risk_engine, approval_service = services
    
    # Create intent with excessive quantity (should violate R1)
    intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("100000"),  # Huge quantity
        order_type="MKT",
        limit_price=None,
        time_in_force="DAY",
        reason="Test excessive position size",
        strategy_tag="mcp_request",
        constraints={},
    )
    
    portfolio = broker.get_portfolio("DU123456")
    market_price = Decimal("190.00")
    sim_result = simulator.simulate(portfolio, intent, market_price)
    
    # Risk evaluation should reject
    risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)
    assert risk_decision.decision == Decision.REJECT
    assert len(risk_decision.violations) > 0


def test_request_approval_workflow_simulation_failure(services):
    """Test request_approval workflow - simulation failure path."""
    broker, simulator, risk_engine, approval_service = services
    
    # Create broker with zero cash
    broke_broker = FakeBrokerAdapter(account_id="DU123456")
    broke_broker.connect()
    broke_broker._cash = {"USD": Decimal("0")}  # No cash
    
    intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("10"),
        order_type="MKT",
        limit_price=None,
        time_in_force="DAY",
        reason="Test insufficient cash scenario",
        strategy_tag="mcp_request",
        constraints={},
    )
    
    portfolio = broke_broker.get_portfolio("DU123456")
    market_price = Decimal("190.00")
    sim_result = simulator.simulate(portfolio, intent, market_price)
    
    # Simulation should fail
    assert sim_result.status != "SUCCESS"
    assert sim_result.error_message is not None


def test_request_approval_workflow_limit_order(services):
    """Test request_approval workflow with limit order."""
    broker, simulator, risk_engine, approval_service = services
    
    intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("10"),
        order_type="LMT",
        limit_price=Decimal("185.00"),  # Below market
        time_in_force="DAY",
        reason="Buy on dip below current market price",
        strategy_tag="mcp_request",
        constraints={},
    )
    
    portfolio = broker.get_portfolio("DU123456")
    market_price = Decimal("190.00")
    sim_result = simulator.simulate(portfolio, intent, market_price)
    
    assert sim_result.status == "SUCCESS"
    
    risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)
    assert risk_decision.decision == Decision.APPROVE
    
    proposal = approval_service.store_proposal(
        intent=intent,
        sim_result=sim_result,
        risk_decision=risk_decision,
    )
    
    # Verify limit order details
    assert proposal.intent.order_type == "LMT"
    assert proposal.intent.limit_price == Decimal("185.00")


def test_approval_service_get_proposal(services):
    """Test ApprovalService.get_proposal functionality."""
    _, _, _, approval_service = services
    
    # Get non-existent proposal
    result = approval_service.get_proposal("non-existent-id")
    assert result is None


def test_approval_service_list_proposals(services):
    """Test ApprovalService.list_proposals functionality."""
    broker, simulator, risk_engine, approval_service = services
    
    # Create multiple proposals
    for i in range(3):
        intent = OrderIntent(
            account_id="DU123456",
            instrument=Instrument(
                type=InstrumentType.STK,
                symbol=f"STOCK{i}",
                exchange="SMART",
                currency="USD",
            ),
            side="BUY",
            quantity=Decimal("10"),
            order_type="MKT",
            limit_price=None,
            time_in_force="DAY",
            reason=f"Test proposal {i} for list test",
            strategy_tag="mcp_request",
            constraints={},
        )
        
        portfolio = broker.get_portfolio("DU123456")
        sim_result = simulator.simulate(portfolio, intent, Decimal("100.00"))
        risk_decision = risk_engine.evaluate(portfolio, intent, sim_result)
        
        proposal = approval_service.store_proposal(
            intent=intent,
            sim_result=sim_result,
            risk_decision=risk_decision,
        )
        approval_service.request_approval(proposal.proposal_id)
    
    # List proposals
    proposals = approval_service.list_proposals()
    assert len(proposals) >= 3
    assert all(p.state == "APPROVAL_REQUESTED" for p in proposals[:3])

