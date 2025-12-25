"""
End-to-end test for complete order flow.

Tests the full workflow from order proposal to filled execution:
1. Create OrderIntent
2. Simulate order
3. Evaluate risk
4. Store proposal
5. Request approval
6. Grant approval (get token)
7. Submit order to broker
8. Poll until FILLED
9. Verify audit trail
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import pytest
import uuid

from packages.approval_service import ApprovalService
from packages.audit_store import AuditStore, AuditQuery, EventType
from packages.broker_ibkr.fake import FakeBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType, Cash, Portfolio, Position, OrderStatus
from packages.order_submission import OrderSubmitter
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours, Decision
from packages.schemas.approval import OrderProposal, OrderState
from packages.schemas.order_intent import OrderIntent
from packages.trade_sim import TradeSimulator, SimulationConfig


@pytest.fixture
def audit_store(tmp_path):
    """Create temporary audit store."""
    db_path = tmp_path / "test_e2e_audit.db"
    return AuditStore(str(db_path))


@pytest.fixture
def approval_service():
    """Create approval service."""
    return ApprovalService(max_proposals=100, token_ttl_minutes=5)


@pytest.fixture
def broker():
    """Create fake broker adapter."""
    adapter = FakeBrokerAdapter(account_id="DU123456")
    adapter.connect()
    return adapter


@pytest.fixture
def simulator():
    """Create trade simulator."""
    return TradeSimulator(config=SimulationConfig())


@pytest.fixture
def risk_engine():
    """Create risk engine."""
    return RiskEngine(
        limits=RiskLimits(
            max_notional=Decimal("100000"),  # Allow up to 100k per order
            max_position_pct=Decimal("100.0"),  # Max 100% position
            max_single_trade=Decimal("100000"),
        ),
        trading_hours=TradingHours(
            allow_pre_market=True,  # Allow trading anytime for tests
            allow_after_hours=True,
        ),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )


@pytest.fixture
def order_submitter(broker, approval_service, audit_store):
    """Create order submitter."""
    return OrderSubmitter(
        broker=broker,
        approval_service=approval_service,
        audit_store=audit_store,
    )


@pytest.fixture
def mock_portfolio():
    """Create mock portfolio."""
    return Portfolio(
        account_id="DU123456",
        positions=[
            Position(
                instrument=Instrument(
                    type=InstrumentType.ETF,
                    symbol="SPY",
                    exchange="ARCA",
                    currency="USD",
                ),
                quantity=Decimal("100"),
                average_cost=Decimal("450.00"),
                market_value=Decimal("46000.00"),
                unrealized_pnl=Decimal("1000.00"),
            ),
        ],
        cash=[
            Cash(
                currency="USD",
                available=Decimal("50000.00"),
                total=Decimal("50000.00"),
            )
        ],
        total_value=Decimal("96000.00"),
    )


def test_complete_order_flow_to_filled(
    audit_store,
    approval_service,
    broker,
    simulator,
    risk_engine,
    order_submitter,
    mock_portfolio,
):
    """Test complete E2E flow from proposal to filled."""
    correlation_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc)
    
    # Step 1: Create OrderIntent
    order_intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="AAPL",
            exchange="NASDAQ",
            currency="USD",
        ),
        side="SELL",  # Sell to reduce exposure
        quantity=Decimal("2"),  # Small quantity
        order_type="MKT",
        time_in_force="DAY",
        reason="E2E test order for portfolio rebalancing",
        strategy_tag="test-e2e",
        constraints={},
    )
    
    # Step 2: Simulate order
    sim_result = simulator.simulate(
        portfolio=mock_portfolio,
        intent=order_intent,
        market_price=Decimal("190.00"),
    )
    
    assert sim_result.status == "SUCCESS"
    assert sim_result.gross_notional == Decimal("380.00")  # 2 shares * $190
    
    # Step 3: Evaluate risk
    risk_decision = risk_engine.evaluate(
        intent=order_intent,
        portfolio=mock_portfolio,
        simulation=sim_result,
    )
    
    assert risk_decision.decision == Decision.APPROVE
    
    # Step 4: Store proposal
    proposal_id = str(uuid.uuid4())
    proposal = OrderProposal(
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        intent_json=order_intent.model_dump_json(exclude_none=True),
        simulation_json=sim_result.model_dump_json(exclude_none=True),
        risk_decision_json=risk_decision.model_dump_json(exclude_none=True),
        state=OrderState.RISK_APPROVED,
    )
    approval_service.store_proposal(proposal)
    
    # Step 5: Request approval
    approval_service.request_approval(proposal_id)
    updated_proposal = approval_service.get_proposal(proposal_id)
    assert updated_proposal.state == OrderState.APPROVAL_REQUESTED
    
    # Step 6: Grant approval (get token)
    approved_proposal, token = approval_service.grant_approval(
        proposal_id,
        reason="E2E test approval",
        current_time=current_time,
    )
    
    assert approved_proposal.state == OrderState.APPROVAL_GRANTED
    assert token.is_valid(current_time)
    
    # Step 7: Submit order to broker
    open_order = order_submitter.submit_order(
        proposal_id=proposal_id,
        token_id=token.token_id,
        correlation_id=correlation_id,
        current_time=current_time,
    )
    
    assert open_order.broker_order_id is not None
    assert open_order.status == OrderStatus.SUBMITTED
    assert open_order.instrument.symbol == "AAPL"
    assert open_order.quantity == Decimal("2")
    
    # Verify proposal transitioned to SUBMITTED
    submitted_proposal = approval_service.get_proposal(proposal_id)
    assert submitted_proposal.state == OrderState.SUBMITTED
    assert submitted_proposal.broker_order_id == open_order.broker_order_id
    
    # Step 8: Simulate fill
    broker.simulate_fill(open_order.broker_order_id, fill_price=Decimal("190.50"))
    
    # Step 9: Poll until FILLED
    filled_order = order_submitter.poll_order_until_terminal(
        broker_order_id=open_order.broker_order_id,
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        max_polls=10,
        poll_interval_seconds=0,
    )
    
    assert filled_order.status == OrderStatus.FILLED
    assert filled_order.filled_quantity == Decimal("2")
    assert filled_order.average_fill_price == Decimal("190.50")
    
    # Verify proposal transitioned to FILLED
    final_proposal = approval_service.get_proposal(proposal_id)
    assert final_proposal.state == OrderState.FILLED
    
    # Step 10: Verify complete audit trail
    query = AuditQuery(correlation_id=correlation_id)
    events = audit_store.query_events(query)
    
    # Should have events for each major step
    event_types = [e.event_type for e in events]
    
    assert EventType.ORDER_SUBMITTED in event_types
    assert EventType.ORDER_FILLED in event_types
    
    # Verify order submitted event has correct data
    submitted_events = [e for e in events if e.event_type == EventType.ORDER_SUBMITTED]
    assert len(submitted_events) > 0
    
    submitted_event = submitted_events[0]
    assert submitted_event.data["proposal_id"] == proposal_id
    assert submitted_event.data["broker_order_id"] == open_order.broker_order_id
    assert submitted_event.data["symbol"] == "AAPL"
    assert submitted_event.data["quantity"] == "2"
    
    # Verify order filled event
    filled_events = [e for e in events if e.event_type == EventType.ORDER_FILLED]
    assert len(filled_events) > 0
    
    filled_event = filled_events[0]
    assert filled_event.data["proposal_id"] == proposal_id
    assert filled_event.data["broker_order_id"] == open_order.broker_order_id


def test_order_flow_with_risk_rejection(
    approval_service,
    simulator,
    mock_portfolio,
):
    """Test flow stops at risk rejection."""
    correlation_id = str(uuid.uuid4())
    
    # Create order that violates risk limits
    order_intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="TSLA",
            exchange="NASDAQ",
            currency="USD",
        ),
        side="BUY",
        quantity=Decimal("1000"),  # Too large
        order_type="MKT",
        time_in_force="DAY",
        reason="Test order that should be rejected",
        strategy_tag="test-rejection",
        constraints={},
    )
    
    # Simulate
    sim_result = simulator.simulate(
        portfolio=mock_portfolio,
        intent=order_intent,
        market_price=Decimal("250.00"),
    )
    
    # Risk engine with tight limits
    risk_engine = RiskEngine(
        limits=RiskLimits(
            max_notional=Decimal("10000"),  # Will reject 250k trade
            max_position_pct=Decimal("10.0"),
        ),
        trading_hours=TradingHours(
            allow_pre_market=True,
            allow_after_hours=True,
        ),
        daily_trades_count=0,
        daily_pnl=Decimal("0"),
    )
    
    risk_decision = risk_engine.evaluate(
        intent=order_intent,
        portfolio=mock_portfolio,
        simulation=sim_result,
    )
    
    # Should be rejected
    assert risk_decision.decision == Decision.REJECT
    
    # Store proposal in RISK_REJECTED state
    proposal_id = str(uuid.uuid4())
    proposal = OrderProposal(
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        intent_json=order_intent.model_dump_json(exclude_none=True),
        simulation_json=sim_result.model_dump_json(exclude_none=True),
        risk_decision_json=risk_decision.model_dump_json(exclude_none=True),
        state=OrderState.RISK_REJECTED,
    )
    approval_service.store_proposal(proposal)
    
    # Cannot request approval for rejected proposal
    with pytest.raises(ValueError, match="Must be RISK_APPROVED"):
        approval_service.request_approval(proposal_id)
    
    # Verify proposal stuck in RISK_REJECTED
    final_proposal = approval_service.get_proposal(proposal_id)
    assert final_proposal.state == OrderState.RISK_REJECTED


def test_order_flow_with_denial(
    approval_service,
    simulator,
    risk_engine,
    mock_portfolio,
):
    """Test flow stops at human denial."""
    correlation_id = str(uuid.uuid4())
    
    order_intent = OrderIntent(
        account_id="DU123456",
        instrument=Instrument(
            type=InstrumentType.STK,
            symbol="NVDA",
            exchange="NASDAQ",
            currency="USD",
        ),
        side="SELL",
        quantity=Decimal("5"),
        order_type="LMT",
        limit_price=Decimal("500.00"),
        time_in_force="DAY",
        reason="Test order to be denied",
        strategy_tag="test-denial",
        constraints={},
    )
    
    # Simulate and risk check pass
    sim_result = simulator.simulate(
        portfolio=mock_portfolio,
        intent=order_intent,
        market_price=Decimal("490.00"),
    )
    
    risk_decision = risk_engine.evaluate(
        intent=order_intent,
        portfolio=mock_portfolio,
        simulation=sim_result,
    )
    
    assert risk_decision.decision == Decision.APPROVE
    
    # Store and request approval
    proposal_id = str(uuid.uuid4())
    proposal = OrderProposal(
        proposal_id=proposal_id,
        correlation_id=correlation_id,
        intent_json=order_intent.model_dump_json(exclude_none=True),
        simulation_json=sim_result.model_dump_json(exclude_none=True),
        risk_decision_json=risk_decision.model_dump_json(exclude_none=True),
        state=OrderState.RISK_APPROVED,
    )
    approval_service.store_proposal(proposal)
    approval_service.request_approval(proposal_id)
    
    # Human denies
    denied_proposal = approval_service.deny_approval(
        proposal_id,
        reason="Market conditions unfavorable"
    )
    
    assert denied_proposal.state == OrderState.APPROVAL_DENIED
    assert denied_proposal.approval_reason == "Market conditions unfavorable"
    
    # Cannot grant approval after denial
    with pytest.raises(ValueError, match="Must be APPROVAL_REQUESTED"):
        approval_service.grant_approval(proposal_id)
