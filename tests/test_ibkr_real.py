"""
Integration tests for IBKRBrokerAdapter.

IMPORTANT: These tests require IBKR Gateway or TWS running on port 7497.
Run manually: pytest tests/test_ibkr_real.py -v -s
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from packages.broker_ibkr.real import IBKRBrokerAdapter
from packages.broker_ibkr.models import Instrument, InstrumentType, OrderSide, OrderType as ModelOrderType
from packages.ibkr_config import IBKRConfig
from packages.schemas.order_intent import OrderIntent
from packages.schemas.approval import ApprovalToken
from packages.schemas.market_data import TimeframeType


# Mark all tests as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def ibkr_config():
    """IBKR configuration for paper trading."""
    return IBKRConfig(
        host="127.0.0.1",
        port=7497,  # Paper trading port
        client_id=1,
        mode="paper",
        readonly_mode=False,
    )


@pytest.fixture
def adapter(ibkr_config):
    """Create IBKR adapter instance."""
    adapter = IBKRBrokerAdapter(config=ibkr_config)
    yield adapter
    # Cleanup
    if adapter.is_connected():
        adapter.disconnect()


def test_connection(adapter):
    """Test connection to IBKR Gateway."""
    # Connect
    adapter.connect()
    assert adapter.is_connected()
    
    # Disconnect
    adapter.disconnect()
    assert not adapter.is_connected()


def test_reconnection(adapter):
    """Test reconnection logic."""
    # Initial connection
    adapter.connect()
    assert adapter.is_connected()
    
    # Force reconnect
    adapter.disconnect()
    adapter.connect()
    assert adapter.is_connected()


def test_get_accounts(adapter):
    """Test account retrieval."""
    adapter.connect()
    
    accounts = adapter.get_accounts()
    
    assert len(accounts) > 0
    assert all(acc.account_id for acc in accounts)
    assert all(acc.status == "active" for acc in accounts)


def test_get_portfolio(adapter):
    """Test portfolio retrieval."""
    adapter.connect()
    
    accounts = adapter.get_accounts()
    assert len(accounts) > 0
    
    account_id = accounts[0].account_id
    portfolio = adapter.get_portfolio(account_id)
    
    assert portfolio.account_id == account_id
    assert portfolio.timestamp
    assert portfolio.cash
    assert portfolio.cash.amount >= 0
    assert isinstance(portfolio.positions, list)
    assert portfolio.total_value >= 0


def test_get_open_orders(adapter):
    """Test open orders retrieval."""
    adapter.connect()
    
    accounts = adapter.get_accounts()
    assert len(accounts) > 0
    
    account_id = accounts[0].account_id
    orders = adapter.get_open_orders(account_id)
    
    # May be empty if no open orders
    assert isinstance(orders, list)
    
    for order in orders:
        assert order.broker_order_id
        assert order.instrument
        assert order.side in [OrderSide.BUY, OrderSide.SELL]
        assert order.quantity > 0


def test_market_snapshot(adapter):
    """Test market data snapshot."""
    adapter.connect()
    
    instrument = Instrument(
        symbol="AAPL",
        type=InstrumentType.STK,
        exchange="SMART",
        currency="USD"
    )
    
    snapshot = adapter.get_market_snapshot(instrument)
    
    assert snapshot.instrument.symbol == instrument.symbol
    # At least one price field should be present
    assert snapshot.bid or snapshot.ask or snapshot.last


def test_market_snapshot_v2(adapter):
    """Test market snapshot v2."""
    adapter.connect()
    
    snapshot = adapter.get_market_snapshot_v2("AAPL")
    
    assert snapshot.instrument == "AAPL"
    assert snapshot.timestamp
    # Should have at least one price
    assert snapshot.bid or snapshot.ask or snapshot.last or snapshot.mid


def test_market_bars(adapter):
    """Test historical bars."""
    adapter.connect()
    
    bars = adapter.get_market_bars(
        instrument="AAPL",
        timeframe="1d",
        limit=5,
        rth_only=True
    )
    
    assert len(bars) > 0
    assert len(bars) <= 5
    
    for bar in bars:
        assert bar.instrument == "AAPL"
        assert bar.timeframe == "1d"
        assert bar.open > 0
        assert bar.high >= bar.open
        assert bar.low <= bar.open
        assert bar.close > 0
        assert bar.volume >= 0


def test_search_instruments(adapter):
    """Test instrument search."""
    adapter.connect()
    
    results = adapter.search_instruments(
        query="AAPL",
        limit=5
    )
    
    assert len(results) > 0
    
    # Should find AAPL
    aapl = next((r for r in results if r.symbol == "AAPL"), None)
    assert aapl is not None
    assert aapl.con_id > 0
    assert aapl.type == "STK"
    assert aapl.currency == "USD"


def test_resolve_instrument_unique(adapter):
    """Test instrument resolution - unique match."""
    adapter.connect()
    
    contract = adapter.resolve_instrument(
        symbol="AAPL",
        type="STK",
        exchange="SMART",
        currency="USD"
    )
    
    assert contract.symbol == "AAPL"
    assert contract.con_id > 0
    assert contract.type == "STK"
    assert contract.currency == "USD"


def test_resolve_instrument_by_conid(adapter):
    """Test instrument resolution by conId."""
    adapter.connect()
    
    # First get AAPL contract
    contract1 = adapter.resolve_instrument(symbol="AAPL")
    assert contract1.con_id > 0
    
    # Now resolve by conId
    contract2 = adapter.resolve_instrument(
        symbol="",  # Not used when conId provided
        con_id=contract1.con_id
    )
    
    assert contract2.con_id == contract1.con_id
    assert contract2.symbol == contract1.symbol


def test_get_contract_by_id(adapter):
    """Test getting contract by ID."""
    adapter.connect()
    
    # AAPL conId (example - may vary)
    # First search to get real conId
    results = adapter.search_instruments("AAPL", limit=1)
    assert len(results) > 0
    con_id = results[0].con_id
    
    contract = adapter.get_contract_by_id(con_id)
    
    assert contract is not None
    assert contract.con_id == con_id
    assert contract.symbol == "AAPL"


def test_submit_market_order(adapter, ibkr_config):
    """Test market order submission (paper trading only!)."""
    # Skip if readonly
    if ibkr_config.readonly_mode:
        pytest.skip("Readonly mode enabled")
    
    adapter.connect()
    
    accounts = adapter.get_accounts()
    account_id = accounts[0].account_id
    
    # Create order intent (small quantity for safety)
    intent = OrderIntent(
        account_id=account_id,
        instrument=Instrument(
            symbol="AAPL",
            type=InstrumentType.STK,
            exchange="SMART",
            currency="USD"
        ),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=ModelOrderType.LMT,
        limit_price=Decimal("100.00"),  # Below market to avoid fill
        reason="Test order for integration testing purposes only",
        strategy_tag="test_strategy",
    )
    
    # Create mock approval token
    token = ApprovalToken(
        id="test-token",
        approved_intent=intent,
        approved_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    
    # Submit order
    order = adapter.submit_order(intent, token)
    
    assert order.broker_order_id
    assert order.instrument.symbol == "AAPL"
    assert order.side == OrderSide.BUY
    assert order.quantity == Decimal("1")
    assert order.order_type == ModelOrderType.LMT
    assert order.limit_price == Decimal("100.00")


def test_get_order_status(adapter, ibkr_config):
    """Test order status retrieval."""
    if ibkr_config.readonly_mode:
        pytest.skip("Readonly mode enabled")
    
    adapter.connect()
    
    accounts = adapter.get_accounts()
    account_id = accounts[0].account_id
    
    # Submit test order first
    intent = OrderIntent(
        account_id=account_id,
        instrument=Instrument(
            symbol="AAPL",
            type=InstrumentType.STK,
            exchange="SMART",
            currency="USD"
        ),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=ModelOrderType.LMT,
        limit_price=Decimal("100.00"),
        reason="Test order for status check integration test",
        strategy_tag="test_strategy",
    )
    
    token = ApprovalToken(
        id="test-token-2",
        approved_intent=intent,
        approved_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    
    submitted_order = adapter.submit_order(intent, token)
    
    # Get status
    order_status = adapter.get_order_status(submitted_order.broker_order_id)
    
    assert order_status.broker_order_id == submitted_order.broker_order_id


def test_readonly_mode_blocks_orders(ibkr_config):
    """Test that readonly mode prevents order submission."""
    # Create adapter with readonly mode
    config = IBKRConfig(
        host=ibkr_config.host,
        port=ibkr_config.port,
        client_id=2,
        mode="paper",
        readonly_mode=True,  # Force readonly
    )
    
    adapter = IBKRBrokerAdapter(config=config)
    adapter.connect()
    
    intent = OrderIntent(
        account_id="test_account",
        instrument=Instrument(
            symbol="AAPL",
            type=InstrumentType.STK,
            exchange="SMART",
            currency="USD"
        ),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=ModelOrderType.MKT,
        reason="Test order that should be blocked by readonly mode",
        strategy_tag="test_strategy",
    )
    
    token = ApprovalToken(
        id="test-token-ro",
        approved_intent=intent,
        approved_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    
    # Should raise PermissionError
    with pytest.raises(PermissionError, match="read-only mode"):
        adapter.submit_order(intent, token)


def test_connection_required(adapter):
    """Test that operations require connection."""
    # Don't connect
    assert not adapter.is_connected()
    
    with pytest.raises(ConnectionError, match="Not connected"):
        adapter.get_accounts()
    
    with pytest.raises(ConnectionError, match="Not connected"):
        adapter.get_portfolio("test")
    
    with pytest.raises(ConnectionError, match="Not connected"):
        adapter.get_market_snapshot_v2("AAPL")
