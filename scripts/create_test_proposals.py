"""
Helper script to create test proposals for dashboard testing.

Usage:
    python scripts/create_test_proposals.py [count]
    
Example:
    python scripts/create_test_proposals.py 5
"""

import json
import sys
from decimal import Decimal
from datetime import datetime, timezone
import uuid

# Add project root to path
sys.path.insert(0, ".")

from packages.schemas.approval import OrderProposal, OrderState
from packages.approval_service import ApprovalService


def create_test_intent(symbol: str, side: str, quantity: int, price: Decimal) -> str:
    """Create test OrderIntent JSON."""
    intent = {
        "instrument": {
            "type": "STK",
            "symbol": symbol,
            "exchange": "SMART",
            "currency": "USD"
        },
        "side": side,
        "quantity": quantity,
        "order_type": "LMT",
        "limit_price": str(price),
        "time_in_force": "DAY",
        "reason": f"Test order for {symbol}",
        "strategy_tag": "test",
    }
    return json.dumps(intent, sort_keys=True)


def create_test_simulation(gross_notional: Decimal) -> str:
    """Create test SimulationResult JSON."""
    fee = Decimal("1.00")
    slippage = gross_notional * Decimal("0.0005")  # 5 bps
    net_notional = gross_notional + fee + slippage
    
    sim = {
        "status": "SUCCESS",
        "execution_price": str(gross_notional / 100),  # Assume 100 shares
        "gross_notional": str(gross_notional),
        "estimated_fee": str(fee),
        "estimated_slippage": str(slippage),
        "net_notional": str(net_notional),
        "cash_before": "100000.00",
        "cash_after": str(Decimal("100000.00") - net_notional),
        "exposure_before": "0.00",
        "exposure_after": str(gross_notional),
        "warnings": [],
        "error_message": None,
    }
    return json.dumps(sim, sort_keys=True)


def create_test_risk_decision(approved: bool = True) -> str:
    """Create test RiskDecision JSON."""
    if approved:
        decision = {
            "decision": "APPROVE",
            "reason": "All risk checks passed",
            "violated_rules": [],
            "warnings": [],
            "metrics": {
                "gross_notional": "5000.00",
                "position_pct": "5.00",
            },
        }
    else:
        decision = {
            "decision": "REJECT",
            "reason": "Notional exceeds max_notional limit",
            "violated_rules": ["R1"],
            "warnings": [],
            "metrics": {
                "gross_notional": "60000.00",
                "position_pct": "60.00",
            },
        }
    return json.dumps(decision, sort_keys=True)


def create_test_proposals(count: int = 5):
    """Create test proposals with various states."""
    # Initialize approval service
    service = ApprovalService(max_proposals=100, token_ttl_minutes=5)
    
    test_stocks = [
        ("AAPL", "BUY", 50, Decimal("180.00")),
        ("MSFT", "BUY", 30, Decimal("400.00")),
        ("GOOGL", "SELL", 20, Decimal("140.00")),
        ("TSLA", "BUY", 10, Decimal("250.00")),
        ("NVDA", "BUY", 15, Decimal("500.00")),
        ("META", "BUY", 25, Decimal("380.00")),
        ("AMZN", "SELL", 12, Decimal("175.00")),
        ("SPY", "BUY", 100, Decimal("450.00")),
    ]
    
    proposals_created = []
    
    for i in range(min(count, len(test_stocks))):
        symbol, side, quantity, price = test_stocks[i]
        gross_notional = Decimal(str(quantity)) * price
        
        # Create proposal in RISK_APPROVED state
        intent_json = create_test_intent(symbol, side, quantity, price)
        simulation_json = create_test_simulation(gross_notional)
        risk_decision_json = create_test_risk_decision(approved=True)
        
        proposal = OrderProposal(
            proposal_id=f"test-{uuid.uuid4().hex[:12]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:12]}",
            intent_json=intent_json,
            simulation_json=simulation_json,
            risk_decision_json=risk_decision_json,
            state=OrderState.RISK_APPROVED,
        )
        
        service.store_proposal(proposal)
        proposals_created.append(proposal)
        print(f"✅ Created: {symbol} {side} {quantity} @ ${price} (ID: {proposal.proposal_id[:12]}...)")
    
    # Request approval for half of them
    for i in range(len(proposals_created) // 2):
        proposal = proposals_created[i]
        service.request_approval(proposal.proposal_id)
        print(f"📋 Requested approval: {proposal.proposal_id[:12]}...")
    
    # Grant approval for one
    if len(proposals_created) > 0:
        first_requested = proposals_created[0]
        updated, token = service.grant_approval(
            first_requested.proposal_id,
            reason="Test approval",
            current_time=datetime.now(timezone.utc),
        )
        print(f"✅ Granted approval: {first_requested.proposal_id[:12]}... (Token: {token.token_id[:16]}...)")
    
    # Create one rejected proposal
    if count > len(proposals_created):
        intent_json = create_test_intent("REJECTED", "BUY", 1000, Decimal("100.00"))
        simulation_json = create_test_simulation(Decimal("100000.00"))
        risk_decision_json = create_test_risk_decision(approved=False)
        
        rejected_proposal = OrderProposal(
            proposal_id=f"test-{uuid.uuid4().hex[:12]}",
            correlation_id=f"corr-{uuid.uuid4().hex[:12]}",
            intent_json=intent_json,
            simulation_json=simulation_json,
            risk_decision_json=risk_decision_json,
            state=OrderState.RISK_REJECTED,
        )
        
        service.store_proposal(rejected_proposal)
        print(f"❌ Created rejected: {rejected_proposal.proposal_id[:12]}...")
    
    print(f"\n📊 Summary:")
    print(f"   Total created: {len(proposals_created) + (1 if count > len(proposals_created) else 0)}")
    print(f"   RISK_APPROVED: {len(proposals_created) - len(proposals_created) // 2}")
    print(f"   APPROVAL_REQUESTED: {len(proposals_created) // 2 - 1}")
    print(f"   APPROVAL_GRANTED: 1")
    print(f"   RISK_REJECTED: {1 if count > len(proposals_created) else 0}")
    print(f"\n💡 NOTE: These proposals are in-memory only.")
    print(f"   They will be lost when the API server restarts.")
    print(f"   To persist, the API would need to store proposals in the database.")
    
    return service


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Creating {count} test proposals...\n")
    
    service = create_test_proposals(count)
    
    print(f"\n🚀 Test proposals created!")
    print(f"   Start the dashboard: streamlit run apps/dashboard/main.py")
    print(f"   The proposals are stored in the approval service instance.")
    print(f"   You'll need to inject this service into the running API to see them.")
