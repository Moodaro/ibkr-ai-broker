"""
Trade Journal - Order history and trade tracking.

This module provides comprehensive tracking of all orders and trades,
including execution details, P&L calculation, and historical analysis.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

from packages.broker_ibkr.models import OrderSide
from packages.structured_logging import get_logger


logger = get_logger(__name__)


class TradeStatus(str, Enum):
    """Status of a trade record."""
    PENDING = "pending"  # Order submitted but not filled
    FILLED = "filled"  # Order completely filled
    PARTIAL = "partial"  # Order partially filled
    CANCELLED = "cancelled"  # Order cancelled
    REJECTED = "rejected"  # Order rejected


class TradeType(str, Enum):
    """Type of trade."""
    ENTRY = "entry"  # Opening a position
    EXIT = "exit"  # Closing a position
    ADJUSTMENT = "adjustment"  # Adjusting position size


@dataclass
class TradeRecord:
    """Record of a single trade.
    
    Attributes:
        trade_id: Unique identifier for this trade
        order_id: Broker order ID (if available)
        symbol: Instrument symbol
        action: BUY or SELL
        quantity: Number of shares/contracts
        filled_quantity: Quantity actually filled
        price: Execution price (None if not filled)
        status: Current trade status
        trade_type: Entry, exit, or adjustment
        submitted_at: When order was submitted
        filled_at: When order was filled (None if not filled)
        commission: Trading commission paid
        pnl: Realized P&L (for exit trades)
        notes: Additional notes or metadata
    """
    trade_id: int
    order_id: Optional[str]
    symbol: str
    action: OrderSide
    quantity: int
    filled_quantity: int
    price: Optional[Decimal]
    status: TradeStatus
    trade_type: TradeType
    submitted_at: datetime
    filled_at: Optional[datetime]
    commission: Decimal
    pnl: Optional[Decimal]
    notes: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action.value,
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "price": str(self.price) if self.price else None,
            "status": self.status.value,
            "trade_type": self.trade_type.value,
            "submitted_at": self.submitted_at.isoformat(),
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "commission": str(self.commission),
            "pnl": str(self.pnl) if self.pnl else None,
            "notes": self.notes,
        }


@dataclass
class TradeStats:
    """Aggregate statistics for trade history.
    
    Attributes:
        total_trades: Total number of trades
        winning_trades: Number of profitable trades
        losing_trades: Number of losing trades
        total_pnl: Total realized P&L
        win_rate: Percentage of winning trades
        avg_win: Average profit per winning trade
        avg_loss: Average loss per losing trade
        largest_win: Largest single profit
        largest_loss: Largest single loss
        avg_trade_duration_minutes: Average time from submit to fill
    """
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: Decimal
    win_rate: float
    avg_win: Decimal
    avg_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal
    avg_trade_duration_minutes: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": str(self.total_pnl),
            "win_rate": self.win_rate,
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "largest_win": str(self.largest_win),
            "largest_loss": str(self.largest_loss),
            "avg_trade_duration_minutes": self.avg_trade_duration_minutes,
        }


class TradeJournal:
    """Persistent storage and query interface for trade history.
    
    Stores all trades in SQLite database with indexed queries.
    """
    
    def __init__(self, db_path: str = "data/trade_journal.db"):
        """Initialize trade journal.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_database()
        
        logger.info("trade_journal_initialized", db_path=str(self.db_path))
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                filled_quantity INTEGER NOT NULL,
                price TEXT,
                status TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                filled_at TEXT,
                commission TEXT NOT NULL,
                pnl TEXT,
                notes TEXT
            )
        """)
        
        # Create indexes for common queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol 
            ON trades(symbol)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_submitted_at 
            ON trades(submitted_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status 
            ON trades(status)
        """)
        
        conn.commit()
        conn.close()
    
    def record_trade(
        self,
        symbol: str,
        action: OrderSide,
        quantity: int,
        order_id: Optional[str] = None,
        trade_type: TradeType = TradeType.ENTRY,
        notes: str = ""
    ) -> int:
        """Record a new trade (order submission).
        
        Args:
            symbol: Instrument symbol
            action: BUY or SELL
            quantity: Order quantity
            order_id: Broker order ID
            trade_type: Entry, exit, or adjustment
            notes: Additional notes
        
        Returns:
            trade_id of recorded trade
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO trades (
                order_id, symbol, action, quantity, filled_quantity,
                price, status, trade_type, submitted_at, filled_at,
                commission, pnl, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            symbol,
            action.value,
            quantity,
            0,  # filled_quantity starts at 0
            None,  # price unknown until fill
            TradeStatus.PENDING.value,
            trade_type.value,
            datetime.utcnow().isoformat(),
            None,  # filled_at null until fill
            "0.00",  # commission starts at 0
            None,  # pnl null until calculated
            notes
        ))
        
        trade_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        logger.info(
            "trade_recorded",
            trade_id=trade_id,
            symbol=symbol,
            action=action.value,
            quantity=quantity
        )
        
        return trade_id
    
    def update_fill(
        self,
        trade_id: int,
        filled_quantity: int,
        price: Decimal,
        commission: Decimal = Decimal("0"),
        status: TradeStatus = TradeStatus.FILLED
    ) -> None:
        """Update trade with fill information.
        
        Args:
            trade_id: Trade ID to update
            filled_quantity: Quantity filled
            price: Execution price
            commission: Trading commission
            status: New status (FILLED or PARTIAL)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE trades
            SET filled_quantity = ?,
                price = ?,
                commission = ?,
                status = ?,
                filled_at = ?
            WHERE trade_id = ?
        """, (
            filled_quantity,
            str(price),
            str(commission),
            status.value,
            datetime.utcnow().isoformat(),
            trade_id
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(
            "trade_fill_updated",
            trade_id=trade_id,
            filled_quantity=filled_quantity,
            price=str(price),
            status=status.value
        )
    
    def update_pnl(self, trade_id: int, pnl: Decimal) -> None:
        """Update realized P&L for a trade.
        
        Args:
            trade_id: Trade ID to update
            pnl: Realized profit/loss
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE trades
            SET pnl = ?
            WHERE trade_id = ?
        """, (str(pnl), trade_id))
        
        conn.commit()
        conn.close()
        
        logger.info("trade_pnl_updated", trade_id=trade_id, pnl=str(pnl))
    
    def get_trade(self, trade_id: int) -> Optional[TradeRecord]:
        """Get trade by ID.
        
        Args:
            trade_id: Trade ID to retrieve
        
        Returns:
            TradeRecord or None if not found
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM trades WHERE trade_id = ?
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_trade_record(row)
    
    def get_trades(
        self,
        symbol: Optional[str] = None,
        status: Optional[TradeStatus] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[TradeRecord]:
        """Query trades with filters.
        
        Args:
            symbol: Filter by symbol
            status: Filter by status
            start_date: Filter trades after this date
            end_date: Filter trades before this date
            limit: Maximum number of results
            offset: Pagination offset
        
        Returns:
            List of TradeRecord matching filters
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        if start_date:
            query += " AND submitted_at >= ?"
            params.append(start_date.isoformat())
        
        if end_date:
            query += " AND submitted_at <= ?"
            params.append(end_date.isoformat())
        
        query += " ORDER BY submitted_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_trade_record(row) for row in rows]
    
    def get_stats(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> TradeStats:
        """Calculate aggregate statistics for trades.
        
        Args:
            symbol: Filter by symbol
            start_date: Filter trades after this date
            end_date: Filter trades before this date
        
        Returns:
            TradeStats with calculated metrics
        """
        trades = self.get_trades(
            symbol=symbol,
            status=TradeStatus.FILLED,
            start_date=start_date,
            end_date=end_date,
            limit=10000
        )
        
        if not trades:
            return TradeStats(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=Decimal("0"),
                win_rate=0.0,
                avg_win=Decimal("0"),
                avg_loss=Decimal("0"),
                largest_win=Decimal("0"),
                largest_loss=Decimal("0"),
                avg_trade_duration_minutes=0.0
            )
        
        # Calculate statistics
        total_trades = len(trades)
        trades_with_pnl = [t for t in trades if t.pnl is not None]
        
        winning_trades = [t for t in trades_with_pnl if t.pnl > 0]
        losing_trades = [t for t in trades_with_pnl if t.pnl < 0]
        
        total_pnl = sum((t.pnl for t in trades_with_pnl), Decimal("0"))
        
        win_rate = (
            len(winning_trades) / len(trades_with_pnl) * 100
            if trades_with_pnl else 0.0
        )
        
        avg_win = (
            sum((t.pnl for t in winning_trades), Decimal("0")) / len(winning_trades)
            if winning_trades else Decimal("0")
        )
        
        avg_loss = (
            sum((t.pnl for t in losing_trades), Decimal("0")) / len(losing_trades)
            if losing_trades else Decimal("0")
        )
        
        largest_win = max((t.pnl for t in winning_trades), default=Decimal("0"))
        largest_loss = min((t.pnl for t in losing_trades), default=Decimal("0"))
        
        # Calculate average trade duration
        trades_with_duration = [
            t for t in trades
            if t.filled_at and t.submitted_at
        ]
        
        if trades_with_duration:
            durations = [
                (t.filled_at - t.submitted_at).total_seconds() / 60
                for t in trades_with_duration
            ]
            avg_duration = sum(durations) / len(durations)
        else:
            avg_duration = 0.0
        
        return TradeStats(
            total_trades=total_trades,
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            total_pnl=total_pnl,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_trade_duration_minutes=avg_duration
        )
    
    def _row_to_trade_record(self, row: tuple) -> TradeRecord:
        """Convert database row to TradeRecord.
        
        Args:
            row: Database row tuple
        
        Returns:
            TradeRecord instance
        """
        return TradeRecord(
            trade_id=row[0],
            order_id=row[1],
            symbol=row[2],
            action=OrderSide(row[3]),
            quantity=row[4],
            filled_quantity=row[5],
            price=Decimal(row[6]) if row[6] else None,
            status=TradeStatus(row[7]),
            trade_type=TradeType(row[8]),
            submitted_at=datetime.fromisoformat(row[9]),
            filled_at=datetime.fromisoformat(row[10]) if row[10] else None,
            commission=Decimal(row[11]),
            pnl=Decimal(row[12]) if row[12] else None,
            notes=row[13] or ""
        )
    
    def export_csv(
        self,
        output_path: str,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """Export trade history to CSV file.
        
        Args:
            output_path: Path to output CSV file
            symbol: Filter by symbol
            start_date: Filter trades after this date
            end_date: Filter trades before this date
        
        Returns:
            Number of trades exported
        """
        import csv
        
        trades = self.get_trades(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            limit=100000
        )
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'trade_id', 'order_id', 'symbol', 'action', 'quantity',
                'filled_quantity', 'price', 'status', 'trade_type',
                'submitted_at', 'filled_at', 'commission', 'pnl', 'notes'
            ])
            
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade.to_dict())
        
        logger.info("trade_history_exported", path=output_path, count=len(trades))
        
        return len(trades)


# Singleton instance
_trade_journal: Optional[TradeJournal] = None


def get_trade_journal(db_path: str = "data/trade_journal.db") -> TradeJournal:
    """Get singleton trade journal instance.
    
    Args:
        db_path: Path to database file
    
    Returns:
        TradeJournal instance
    """
    global _trade_journal
    
    if _trade_journal is None:
        _trade_journal = TradeJournal(db_path)
    
    return _trade_journal
