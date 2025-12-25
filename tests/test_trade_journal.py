"""
Tests for trade journal module.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile

from packages.trade_journal import (
    TradeJournal,
    TradeRecord,
    TradeStatus,
    TradeType,
    TradeStats,
    get_trade_journal,
)
from packages.broker_ibkr.models import OrderSide


@pytest.fixture
def temp_db():
    """Temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        yield str(db_path)


@pytest.fixture
def journal(temp_db):
    """Fresh trade journal for each test."""
    import packages.trade_journal
    packages.trade_journal._trade_journal = None
    return TradeJournal(temp_db)


class TestTradeJournal:
    """Tests for TradeJournal class."""
    
    def test_record_trade(self, journal):
        """Test recording a new trade."""
        trade_id = journal.record_trade(
            symbol="AAPL",
            action=OrderSide.BUY,
            quantity=100,
            order_id="ORD123",
            trade_type=TradeType.ENTRY,
            notes="Test trade"
        )
        
        assert trade_id > 0
        
        # Verify trade was recorded
        trade = journal.get_trade(trade_id)
        assert trade is not None
        assert trade.symbol == "AAPL"
        assert trade.action == OrderSide.BUY
        assert trade.quantity == 100
        assert trade.order_id == "ORD123"
        assert trade.status == TradeStatus.PENDING
        assert trade.filled_quantity == 0
        assert trade.price is None
    
    def test_update_fill(self, journal):
        """Test updating trade with fill information."""
        trade_id = journal.record_trade(
            symbol="MSFT",
            action=OrderSide.SELL,
            quantity=50
        )
        
        journal.update_fill(
            trade_id=trade_id,
            filled_quantity=50,
            price=Decimal("350.00"),
            commission=Decimal("1.50"),
            status=TradeStatus.FILLED
        )
        
        trade = journal.get_trade(trade_id)
        assert trade.filled_quantity == 50
        assert trade.price == Decimal("350.00")
        assert trade.commission == Decimal("1.50")
        assert trade.status == TradeStatus.FILLED
        assert trade.filled_at is not None
    
    def test_update_pnl(self, journal):
        """Test updating trade P&L."""
        trade_id = journal.record_trade(
            symbol="GOOGL",
            action=OrderSide.BUY,
            quantity=10
        )
        
        journal.update_pnl(trade_id, Decimal("150.00"))
        
        trade = journal.get_trade(trade_id)
        assert trade.pnl == Decimal("150.00")
    
    def test_get_trades_filter_by_symbol(self, journal):
        """Test filtering trades by symbol."""
        journal.record_trade("AAPL", OrderSide.BUY, 100)
        journal.record_trade("MSFT", OrderSide.BUY, 50)
        journal.record_trade("AAPL", OrderSide.SELL, 50)
        
        aapl_trades = journal.get_trades(symbol="AAPL")
        assert len(aapl_trades) == 2
        assert all(t.symbol == "AAPL" for t in aapl_trades)
    
    def test_get_trades_filter_by_status(self, journal):
        """Test filtering trades by status."""
        id1 = journal.record_trade("AAPL", OrderSide.BUY, 100)
        id2 = journal.record_trade("MSFT", OrderSide.BUY, 50)
        
        # Fill one trade
        journal.update_fill(id1, 100, Decimal("150.00"), status=TradeStatus.FILLED)
        
        filled_trades = journal.get_trades(status=TradeStatus.FILLED)
        assert len(filled_trades) == 1
        assert filled_trades[0].trade_id == id1
        
        pending_trades = journal.get_trades(status=TradeStatus.PENDING)
        assert len(pending_trades) == 1
        assert pending_trades[0].trade_id == id2
    
    def test_get_trades_pagination(self, journal):
        """Test trade pagination."""
        # Create 15 trades
        for i in range(15):
            journal.record_trade(f"SYM{i}", OrderSide.BUY, 100)
        
        # Get first page
        page1 = journal.get_trades(limit=10, offset=0)
        assert len(page1) == 10
        
        # Get second page
        page2 = journal.get_trades(limit=10, offset=10)
        assert len(page2) == 5
        
        # No duplicates
        ids1 = {t.trade_id for t in page1}
        ids2 = {t.trade_id for t in page2}
        assert len(ids1 & ids2) == 0
    
    def test_get_stats_empty(self, journal):
        """Test statistics with no trades."""
        stats = journal.get_stats()
        
        assert stats.total_trades == 0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 0
        assert stats.total_pnl == Decimal("0")
        assert stats.win_rate == 0.0
    
    def test_get_stats_with_trades(self, journal):
        """Test statistics calculation."""
        # Create and fill some winning trades
        for i in range(3):
            trade_id = journal.record_trade("AAPL", OrderSide.BUY, 100)
            journal.update_fill(trade_id, 100, Decimal("150.00"), status=TradeStatus.FILLED)
            journal.update_pnl(trade_id, Decimal("100.00"))  # Winning trade
        
        # Create and fill some losing trades
        for i in range(2):
            trade_id = journal.record_trade("MSFT", OrderSide.SELL, 50)
            journal.update_fill(trade_id, 50, Decimal("300.00"), status=TradeStatus.FILLED)
            journal.update_pnl(trade_id, Decimal("-50.00"))  # Losing trade
        
        stats = journal.get_stats()
        
        assert stats.total_trades == 5
        assert stats.winning_trades == 3
        assert stats.losing_trades == 2
        assert stats.total_pnl == Decimal("200.00")  # 3*100 - 2*50
        assert stats.win_rate == 60.0  # 3/5 * 100
        assert stats.avg_win == Decimal("100.00")
        assert stats.avg_loss == Decimal("-50.00")
        assert stats.largest_win == Decimal("100.00")
        assert stats.largest_loss == Decimal("-50.00")
    
    def test_export_csv(self, journal, temp_db):
        """Test CSV export."""
        # Create some trades
        for i in range(5):
            journal.record_trade(f"SYM{i}", OrderSide.BUY, 100)
        
        output_path = Path(temp_db).parent / "export.csv"
        count = journal.export_csv(str(output_path))
        
        assert count == 5
        assert output_path.exists()
        
        # Verify CSV content
        with open(output_path) as f:
            lines = f.readlines()
            assert len(lines) == 6  # Header + 5 trades
            assert "trade_id" in lines[0]
    
    def test_trade_record_to_dict(self, journal):
        """Test TradeRecord serialization."""
        trade_id = journal.record_trade("AAPL", OrderSide.BUY, 100)
        trade = journal.get_trade(trade_id)
        
        data = trade.to_dict()
        
        assert isinstance(data, dict)
        assert data["symbol"] == "AAPL"
        assert data["action"] == "BUY"
        assert data["quantity"] == 100
        assert "submitted_at" in data
    
    def test_trade_stats_to_dict(self, journal):
        """Test TradeStats serialization."""
        stats = journal.get_stats()
        data = stats.to_dict()
        
        assert isinstance(data, dict)
        assert "total_trades" in data
        assert "win_rate" in data
        assert "total_pnl" in data


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_trade_journal_singleton(self, temp_db):
        """Test singleton returns same instance."""
        import packages.trade_journal
        packages.trade_journal._trade_journal = None
        
        journal1 = get_trade_journal(temp_db)
        journal2 = get_trade_journal(temp_db)
        
        assert journal1 is journal2
