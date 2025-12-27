#!/usr/bin/env python3
"""Quick test dello stack IBKR AI Broker."""

print("=== 🧪 TEST IBKR AI BROKER ===\n")

# Test 1: Broker Fake
print("1️⃣  Test Broker Fake...")
from packages.broker_ibkr.fake import FakeBrokerAdapter

broker = FakeBrokerAdapter()
broker.connect()
portfolio = broker.get_portfolio('DU123456')

print(f"   ✅ Portfolio: ${portfolio.total_value:,.2f}")
cash_total = sum(c.total for c in portfolio.cash)
print(f"   ✅ Cash: ${cash_total:,.2f}")
print(f"   ✅ Positions: {len(portfolio.positions)}")

# Test 2: Market Data
print("\n2️⃣  Test Market Data...")
snapshot = broker.get_market_snapshot_v2('AAPL')
print(f"   ✅ AAPL: Bid ${snapshot.bid} | Ask ${snapshot.ask}")
print(f"   ✅ Last: ${snapshot.last} | Volume: {snapshot.volume:,}")

# Test 3: Simulator
print("\n3️⃣  Test Simulator...")
from packages.trade_sim import TradeSimulator, SimulationConfig
from packages.schemas.order_intent import OrderIntent
from packages.broker_ibkr import Instrument, InstrumentType, OrderSide, OrderType
from decimal import Decimal

simulator = TradeSimulator(config=SimulationConfig())
intent = OrderIntent(
    account_id='DU123456',
    instrument=Instrument(
        symbol='AAPL',
        type=InstrumentType.STK,
        exchange='SMART',
        currency='USD'
    ),
    side=OrderSide.BUY,
    order_type=OrderType.MKT,
    quantity=10,
    reason="Quick test order",
    strategy_tag="test"
)

# Use snapshot price for simulation
market_price = Decimal(str(snapshot.last))
sim_result = simulator.simulate(intent, portfolio, market_price)
print(f"   ✅ Simulation: {sim_result.status}")
print(f"   ✅ Execution price: ${sim_result.execution_price}")
print(f"   ✅ Net cost: ${sim_result.net_notional}")
print(f"   ✅ Cash after: ${sim_result.cash_after:,.2f}")

# Test 4: Risk Engine
print("\n4️⃣  Test Risk Engine...")
from packages.risk_engine import RiskEngine, RiskLimits, TradingHours

limits = RiskLimits()
trading_hours = TradingHours()
risk_engine = RiskEngine(limits=limits, trading_hours=trading_hours)

decision = risk_engine.evaluate(intent, portfolio, sim_result)
print(f"   ✅ Risk Decision: {decision.decision}")
print(f"   ✅ Reason: {decision.reason}")

# Test 5: Audit Store
print("\n5️⃣  Test Audit Store...")
from packages.audit_store import AuditStore, AuditEventCreate, EventType

store = AuditStore('data/audit.db')
store.append_event(AuditEventCreate(
    event_type=EventType.ORDER_PROPOSED,
    correlation_id='test-' + str(portfolio.timestamp),
    data={'test': 'quick_test', 'symbol': 'AAPL'}
))
print("   ✅ Audit event saved")

# Summary
print("\n" + "="*60)
print("✅ TUTTI I TEST PASSATI!")
print("="*60)
print("\n📚 Prossimi step:")
print("   1. Avvia API:      uvicorn apps.assistant_api.main:app --reload --port 8000")
print("   2. Apri browser:   http://localhost:8000/docs")
print("   3. Test endpoint:  GET /api/v1/portfolio?account_id=DU123456")
print("   4. Leggi QUICKSTART.md per il flow completo\n")
