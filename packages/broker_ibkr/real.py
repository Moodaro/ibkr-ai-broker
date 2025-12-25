"""
Real IBKR Broker Adapter using ib_insync.

Implements BrokerAdapter Protocol for actual Interactive Brokers connectivity.
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
import structlog
from ib_insync import IB, Stock, Contract, Order as IBOrder, MarketOrder, LimitOrder
from ib_insync import util

from packages.broker_ibkr.adapter import BrokerAdapter
from packages.broker_ibkr.models import (
    Account,
    Instrument,
    MarketSnapshot,
    OpenOrder,
    Portfolio,
    Position,
    Cash,
    InstrumentType,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderStatus,
)
from packages.schemas.approval import ApprovalToken
from packages.schemas.order_intent import OrderIntent
from packages.schemas.market_data import (
    MarketSnapshot as MarketSnapshotV2,
    MarketBar,
    TimeframeType,
)
from packages.schemas.instrument import (
    InstrumentContract,
    SearchCandidate,
    InstrumentTypeEnum,
    InstrumentResolutionError,
)
from packages.ibkr_connection import ConnectionManager, get_connection_manager
from packages.ibkr_config import IBKRConfig, get_ibkr_config


logger = structlog.get_logger(__name__)


class IBKRBrokerAdapter(BrokerAdapter):
    """
    Real IBKR broker adapter using ib_insync.
    
    Features:
    - Async operations with ib_insync
    - Automatic connection management
    - Position and account data retrieval
    - Market data subscriptions
    - Order submission and tracking
    - Instrument search and resolution
    """
    
    def __init__(
        self,
        config: Optional[IBKRConfig] = None,
        conn_manager: Optional[ConnectionManager] = None
    ):
        """
        Initialize IBKR broker adapter.
        
        Args:
            config: IBKR configuration (uses global if None)
            conn_manager: Connection manager (uses global if None)
        """
        self.config = config or get_ibkr_config()
        self.conn_manager = conn_manager or get_connection_manager(self.config)
        self._order_cache: dict[str, OpenOrder] = {}
    
    @property
    def ib(self) -> IB:
        """Get IB connection instance."""
        return self.conn_manager.ib
    
    def connect(self) -> None:
        """Establish connection to broker."""
        asyncio.run(self.conn_manager.connect())
    
    def disconnect(self) -> None:
        """Disconnect from broker."""
        asyncio.run(self.conn_manager.disconnect())
    
    def is_connected(self) -> bool:
        """Check if connected to broker."""
        return self.conn_manager.is_connected()
    
    def get_accounts(self) -> List[Account]:
        """Get list of accounts."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        managed_accounts = self.ib.managedAccounts()
        
        return [
            Account(
                account_id=account_id,
                account_type="paper" if self.config.is_paper else "live",
                status="active"
            )
            for account_id in managed_accounts
        ]
    
    def get_portfolio(self, account_id: str) -> Portfolio:
        """Get complete portfolio snapshot."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # Get positions
        ib_positions = self.ib.positions(account=account_id)
        positions = []
        
        for ib_pos in ib_positions:
            contract = ib_pos.contract
            instrument_type = contract.secType
            # Map IBKR secType to InstrumentType
            if instrument_type not in [t.value for t in InstrumentType]:
                instrument_type = "STK"  # Default to stock
            
            positions.append(Position(
                instrument=Instrument(
                    symbol=contract.symbol,
                    type=InstrumentType(instrument_type),
                    exchange=contract.exchange or contract.primaryExchange,
                    currency=contract.currency,
                ),
                quantity=Decimal(str(ib_pos.position)),
                average_cost=Decimal(str(ib_pos.avgCost)),
                market_value=Decimal(str(ib_pos.marketValue)) if hasattr(ib_pos, 'marketValue') else Decimal("0"),
                unrealized_pnl=Decimal(str(ib_pos.unrealizedPNL)) if hasattr(ib_pos, 'unrealizedPNL') else Decimal("0"),
                realized_pnl=Decimal("0"),  # Not available in position
            ))
        
        # Get cash balance
        account_values = self.ib.accountValues(account=account_id)
        cash_available = Decimal("0")
        cash_total = Decimal("0")
        
        for av in account_values:
            if av.tag == "TotalCashValue":
                cash_total = Decimal(str(av.value))
            elif av.tag == "AvailableFunds":
                cash_available = Decimal(str(av.value))
        
        cash = [Cash(
            currency="USD",
            available=cash_available,
            total=cash_total,
        )]
        
        # Calculate total value
        total_value = cash_total + sum(p.market_value for p in positions)
        
        return Portfolio(
            account_id=account_id,
            cash=cash,
            positions=positions,
            total_value=total_value,
        )
    
    def get_open_orders(self, account_id: str) -> List[OpenOrder]:
        """Get open orders for account."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        trades = self.ib.openTrades()
        open_orders = []
        
        for trade in trades:
            if trade.order.account != account_id:
                continue
            
            contract = trade.contract
            order = trade.order
            
            # Map IBKR secType to InstrumentType
            instrument_type = contract.secType
            if instrument_type not in [t.value for t in InstrumentType]:
                instrument_type = "STK"
            
            # Map order action to OrderSide
            side = OrderSide.BUY if order.action.upper() == "BUY" else OrderSide.SELL
            
            # Map order type
            order_type_str = order.orderType.upper()
            if order_type_str == "MKT":
                order_type = OrderType.MKT
            elif order_type_str == "LMT":
                order_type = OrderType.LMT
            elif order_type_str == "STP":
                order_type = OrderType.STP
            elif order_type_str == "STP LMT":
                order_type = OrderType.STP_LMT
            else:
                order_type = OrderType.MKT  # Default
            
            # Map status
            status_str = trade.orderStatus.status.lower()
            if status_str in ["submitted", "presubmitted"]:
                status = OrderStatus.SUBMITTED
            elif status_str in ["filled", "completed"]:
                status = OrderStatus.FILLED
            elif status_str == "cancelled":
                status = OrderStatus.CANCELLED
            elif status_str in ["rejected", "error"]:
                status = OrderStatus.REJECTED
            else:
                status = OrderStatus.PENDING
            
            open_orders.append(OpenOrder(
                order_id=f"ibkr-{trade.order.orderId}",
                broker_order_id=str(trade.order.orderId),
                account_id=account_id,
                instrument=Instrument(
                    symbol=contract.symbol,
                    con_id=contract.conId,
                    type=InstrumentType(instrument_type),
                    exchange=contract.exchange or contract.primaryExchange,
                    currency=contract.currency,
                ),
                side=side,
                quantity=Decimal(str(order.totalQuantity)),
                order_type=order_type,
                limit_price=Decimal(str(order.lmtPrice)) if order.lmtPrice else None,
                stop_price=Decimal(str(order.auxPrice)) if order.auxPrice else None,
                time_in_force=TimeInForce.DAY,  # Default
                status=status,
                filled_quantity=Decimal(str(trade.orderStatus.filled)),
                average_fill_price=Decimal(str(trade.orderStatus.avgFillPrice)) if trade.orderStatus.avgFillPrice else None,
            ))
        
        return open_orders
    
    def get_market_snapshot(self, instrument: Instrument) -> MarketSnapshot:
        """Get market data snapshot for instrument."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # Create contract
        contract = self._create_contract(instrument)
        
        # Request market data
        ticker = self.ib.reqMktData(contract, snapshot=True)
        self.ib.sleep(2)  # Wait for data
        
        # Update instrument with conId if not present
        if not instrument.con_id and contract.conId:
            instrument = Instrument(
                symbol=instrument.symbol,
                type=instrument.type,
                con_id=contract.conId,
                exchange=instrument.exchange,
                currency=instrument.currency,
                description=instrument.description,
            )
        
        return MarketSnapshot(
            instrument=instrument,
            bid=Decimal(str(ticker.bid)) if ticker.bid and ticker.bid > 0 else None,
            ask=Decimal(str(ticker.ask)) if ticker.ask and ticker.ask > 0 else None,
            last=Decimal(str(ticker.last)) if ticker.last and ticker.last > 0 else None,
            close=Decimal(str(ticker.close)) if ticker.close and ticker.close > 0 else None,
            volume=int(ticker.volume) if ticker.volume else 0,
        )
    
    def submit_order(
        self,
        order_intent: OrderIntent,
        approval_token: ApprovalToken,
    ) -> OpenOrder:
        """Submit order to broker."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        if self.config.readonly_mode:
            raise PermissionError("Cannot submit orders in read-only mode")
        
        # Create contract from instrument
        contract = self._create_contract(order_intent.instrument)
        
        # Create order based on type
        if order_intent.order_type == OrderType.MKT:
            ib_order = MarketOrder(
                action=order_intent.side.value,  # "BUY" or "SELL"
                totalQuantity=float(order_intent.quantity)
            )
        elif order_intent.order_type == OrderType.LMT:
            if not order_intent.limit_price:
                raise ValueError("Limit price required for limit orders")
            ib_order = LimitOrder(
                action=order_intent.side.value,
                totalQuantity=float(order_intent.quantity),
                lmtPrice=float(order_intent.limit_price)
            )
        else:
            raise ValueError(f"Unsupported order type: {order_intent.order_type}")
        
        # Submit order
        trade = self.ib.placeOrder(contract, ib_order)
        self.ib.sleep(1)  # Wait for acknowledgment
        
        # Map status
        status_str = trade.orderStatus.status.lower() if trade.orderStatus else "submitted"
        if status_str in ["submitted", "presubmitted"]:
            status = OrderStatus.SUBMITTED
        elif status_str in ["filled", "completed"]:
            status = OrderStatus.FILLED
        elif status_str == "cancelled":
            status = OrderStatus.CANCELLED
        elif status_str in ["rejected", "error"]:
            status = OrderStatus.REJECTED
        else:
            status = OrderStatus.PENDING
        
        open_order = OpenOrder(
            order_id=f"ibkr-{trade.order.orderId}",
            broker_order_id=str(trade.order.orderId),
            account_id=order_intent.account_id,
            instrument=order_intent.instrument,
            side=order_intent.side,
            quantity=order_intent.quantity,
            order_type=order_intent.order_type,
            limit_price=order_intent.limit_price,
            stop_price=order_intent.stop_price,
            time_in_force=order_intent.time_in_force,
            status=status,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
        )
        
        self._order_cache[open_order.broker_order_id] = open_order
        
        logger.info(
            "order_submitted",
            broker_order_id=open_order.broker_order_id,
            symbol=order_intent.instrument.symbol,
            side=order_intent.side,
            quantity=str(order_intent.quantity)
        )
        
        return open_order
    
    def get_order_status(self, broker_order_id: str) -> OpenOrder:
        """Get current order status from broker."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # Try cache first
        if broker_order_id in self._order_cache:
            cached_order = self._order_cache[broker_order_id]
            
            # Update from live data
            trades = self.ib.trades()
            for trade in trades:
                if str(trade.order.orderId) == broker_order_id:
                    # Map status
                    status_str = trade.orderStatus.status.lower()
                    if status_str in ["submitted", "presubmitted"]:
                        status = OrderStatus.SUBMITTED
                    elif status_str in ["filled", "completed"]:
                        status = OrderStatus.FILLED
                    elif status_str == "cancelled":
                        status = OrderStatus.CANCELLED
                    elif status_str in ["rejected", "error"]:
                        status = OrderStatus.REJECTED
                    else:
                        status = OrderStatus.PENDING
                    
                    # Update cached order (need to recreate since frozen)
                    updated_order = OpenOrder(
                        order_id=cached_order.order_id,
                        broker_order_id=cached_order.broker_order_id,
                        account_id=cached_order.account_id,
                        instrument=cached_order.instrument,
                        side=cached_order.side,
                        quantity=cached_order.quantity,
                        order_type=cached_order.order_type,
                        limit_price=cached_order.limit_price,
                        stop_price=cached_order.stop_price,
                        time_in_force=cached_order.time_in_force,
                        status=status,
                        filled_quantity=Decimal(str(trade.orderStatus.filled)),
                        average_fill_price=Decimal(str(trade.orderStatus.avgFillPrice)) if trade.orderStatus.avgFillPrice else None,
                    )
                    self._order_cache[broker_order_id] = updated_order
                    return updated_order
            
            return cached_order
        
        raise ValueError(f"Order {broker_order_id} not found")
    
    def get_market_snapshot_v2(
        self,
        instrument: str,
        fields: Optional[List[str]] = None
    ) -> MarketSnapshotV2:
        """Get current market snapshot (v2 schema)."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # Create basic stock contract
        contract = Stock(instrument, exchange="SMART", currency="USD")
        
        # Request market data
        ticker = self.ib.reqMktData(contract, snapshot=True)
        self.ib.sleep(2)
        
        return MarketSnapshotV2(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=float(ticker.bid) if ticker.bid and ticker.bid > 0 else None,
            ask=float(ticker.ask) if ticker.ask and ticker.ask > 0 else None,
            last=float(ticker.last) if ticker.last and ticker.last > 0 else None,
            mid=((ticker.bid + ticker.ask) / 2) if (ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0) else None,
            volume=int(ticker.volume) if ticker.volume else None,
            bid_size=int(ticker.bidSize) if ticker.bidSize else None,
            ask_size=int(ticker.askSize) if ticker.askSize else None,
            high=float(ticker.high) if ticker.high and ticker.high > 0 else None,
            low=float(ticker.low) if ticker.low and ticker.low > 0 else None,
            open=float(ticker.open) if hasattr(ticker, 'open') and ticker.open and ticker.open > 0 else None,
            close=float(ticker.close) if ticker.close and ticker.close > 0 else None,
        )
    
    def get_market_bars(
        self,
        instrument: str,
        timeframe: TimeframeType,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        rth_only: bool = True
    ) -> List[MarketBar]:
        """Get historical OHLCV bars."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # Create contract
        contract = Stock(instrument, exchange="SMART", currency="USD")
        
        # Map timeframe to IB duration and bar size
        duration_map = {
            "1m": "1 D",
            "5m": "1 D",
            "15m": "1 D",
            "30m": "1 W",
            "1h": "1 M",
            "4h": "1 M",
            "1d": "1 Y",
        }
        
        bar_size_map = {
            "1m": "1 min",
            "5m": "5 mins",
            "15m": "15 mins",
            "30m": "30 mins",
            "1h": "1 hour",
            "4h": "4 hours",
            "1d": "1 day",
        }
        
        duration = duration_map.get(timeframe, "1 D")
        bar_size = bar_size_map.get(timeframe, "1 hour")
        
        # Request historical data
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime=end or datetime.utcnow(),
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=rth_only,
            formatDate=1
        )
        
        result = []
        for bar in bars[-limit:]:
            result.append(MarketBar(
                timestamp=bar.date,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=int(bar.volume),
                timeframe=timeframe,
                instrument=instrument,
            ))
        
        return result
    
    def search_instruments(
        self,
        query: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchCandidate]:
        """Search for instruments."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        if not query or len(query.strip()) == 0:
            raise ValueError("Query cannot be empty")
        
        # Search using qualifyContracts
        contract = Stock(query.upper())
        if exchange:
            contract.exchange = exchange
        if currency:
            contract.currency = currency
        
        try:
            qualified = self.ib.qualifyContracts(contract)
            
            results = []
            for c in qualified[:limit]:
                # Calculate simple match score
                score = 1.0 if c.symbol == query.upper() else 0.9
                
                results.append(SearchCandidate(
                    con_id=c.conId,
                    symbol=c.symbol,
                    type=c.secType,
                    exchange=c.exchange or c.primaryExchange,
                    currency=c.currency,
                    name=c.longName if hasattr(c, 'longName') else None,
                    match_score=score
                ))
            
            return results
        
        except Exception as e:
            logger.error("instrument_search_failed", query=query, error=str(e))
            return []
    
    def resolve_instrument(
        self,
        symbol: str,
        type: Optional[InstrumentTypeEnum] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        con_id: Optional[int] = None
    ) -> InstrumentContract:
        """Resolve instrument to exact contract."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        # If conId provided, use it directly
        if con_id:
            contract = self.get_contract_by_id(con_id)
            if contract:
                return contract
            raise InstrumentResolutionError(f"Contract {con_id} not found")
        
        # Search and resolve
        candidates = self.search_instruments(
            query=symbol,
            type=type,
            exchange=exchange,
            currency=currency,
            limit=5
        )
        
        if not candidates:
            raise InstrumentResolutionError(
                f"No contracts found matching '{symbol}'",
                candidates=[]
            )
        
        if len(candidates) == 1:
            # Single match - return it
            c = candidates[0]
            return InstrumentContract(
                con_id=c.con_id,
                symbol=c.symbol,
                type=c.type,
                exchange=c.exchange,
                currency=c.currency,
                name=c.name,
            )
        
        # Multiple matches - check for exact match
        exact_matches = [c for c in candidates if c.symbol == symbol.upper()]
        if len(exact_matches) == 1:
            c = exact_matches[0]
            return InstrumentContract(
                con_id=c.con_id,
                symbol=c.symbol,
                type=c.type,
                exchange=c.exchange,
                currency=c.currency,
                name=c.name,
            )
        
        # Ambiguous - raise with candidates
        raise InstrumentResolutionError(
            f"Ambiguous symbol '{symbol}' - {len(candidates)} matches found",
            candidates=candidates
        )
    
    def get_contract_by_id(self, con_id: int) -> Optional[InstrumentContract]:
        """Get instrument contract by ID."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR")
        
        if con_id <= 0:
            raise ValueError("conId must be positive")
        
        try:
            contract = Contract(conId=con_id)
            qualified = self.ib.qualifyContracts(contract)
            
            if qualified:
                c = qualified[0]
                return InstrumentContract(
                    con_id=c.conId,
                    symbol=c.symbol,
                    type=c.secType,
                    exchange=c.exchange or c.primaryExchange,
                    currency=c.currency,
                    name=c.longName if hasattr(c, 'longName') else None,
                )
            
            return None
        
        except Exception as e:
            logger.error("get_contract_failed", con_id=con_id, error=str(e))
            return None
    
    def _create_contract(self, instrument: Instrument) -> Contract:
        """Create IB contract from Instrument."""
        if instrument.con_id:
            return Contract(conId=instrument.con_id)
        
        # Map InstrumentType to secType
        sec_type = instrument.type.value if isinstance(instrument.type, InstrumentType) else instrument.type
        
        if sec_type == "STK":
            return Stock(
                symbol=instrument.symbol,
                exchange=instrument.exchange or "SMART",
                currency=instrument.currency or "USD"
            )
        else:
            # Generic contract
            return Contract(
                symbol=instrument.symbol,
                secType=sec_type,
                exchange=instrument.exchange or "SMART",
                currency=instrument.currency or "USD"
            )
